#!/usr/bin/env python3
"""Stage 3 helper: turn the database-verification output into a triage worklist,
and assemble the final reports once triage verdicts exist.

The web searching itself is done by the interactive LLM agent, not this script. The flow is:

    python triage.py worklist [--pending]   # -> out/triage_worklist.json (what to check)
    python triage.py status                 # per-paper done / pending counts
    # ... the agent investigates each entry and records verdicts in
    #     out/triage_verdicts.json  as  {"<paper_id>:<number>": {category, finding}} ...
    python triage.py report                 # -> out/reports/*.md

Stage 3 can run on papers already finished by Stages 1+2 while the audit keeps going:
worklist/report read each per-paper JSON the audit has written, and verdicts accumulate
per `<paper_id>:<number>`, so `worklist --pending` surfaces only newly-finished work.

A reference needs triage when its db_verification.status is not "verified".

Verdict categories (severity):
    real-published / real-grey-literature / real-preprint-or-unpublished   (low)
    partial-match        (title close, but author/year/venue off: a citation error)  (medium)
    likely-hallucinated  (no matching record found)                                  (high)
    unclear              (no confident verdict; leave for a human)                    (-)
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

try:
    import fcntl  # POSIX file locking (macOS/Linux -- hallucite's supported platforms)
except ImportError:  # pragma: no cover -- non-POSIX fallback
    fcntl = None

FLAG_CATEGORIES = ("likely-hallucinated", "partial-match", "unclear")
SEVERITY = {
    "real-published": "low", "real-grey-literature": "low",
    "real-preprint-or-unpublished": "low", "partial-match": "medium",
    "likely-hallucinated": "high", "unclear": "-",
}

# Structured fabrication signals recorded alongside a verdict, so the title-first rule is enforced
# by the tool (not just trusted) and the report can show *why* a reference is flagged. See
# `_enforce_title_first` for the gate and `is_fabrication` for the desk-reject heuristic.
#   title_match   -- does a publication bearing the cited TITLE exist? (the decisive signal, T)
#                    yes | no | unsure | na   (na: a non-publication resource, e.g. a web page)
#   matched_title -- the real publication's actual title (required when title_match == "yes")
#   authors_match -- the cited author set/order vs. that publication (signal A)
#   venue_match   -- the cited venue/year/volume vs. reality (signal V)
#   doi_status    -- resolves | 404 | mismatch | none | unsure (signal D)
_SIGNAL_ENUMS = {
    "title_match": {"yes", "no", "unsure", "na"},
    "authors_match": {"yes", "no", "partial", "unsure", "na"},
    "venue_match": {"yes", "no", "partial", "unsure", "na"},
    "doi_status": {"resolves", "404", "mismatch", "none", "unsure"},
}
_SIGNAL_KEYS = set(_SIGNAL_ENUMS) | {"matched_title"}


def _validate_signals(signals: dict) -> dict:
    """Reject unknown keys / out-of-vocabulary enum values so a typo in a signal cannot quietly
    defeat the title-first gate or the desk-reject heuristic."""
    if not isinstance(signals, dict):
        raise SystemExit("--signals must be a JSON object")
    unknown = set(signals) - _SIGNAL_KEYS
    if unknown:
        raise SystemExit(f"unknown signal key(s) {sorted(unknown)}; allowed: {sorted(_SIGNAL_KEYS)}")
    for key, vocab in _SIGNAL_ENUMS.items():
        val = signals.get(key)
        if val is not None and val not in vocab:
            raise SystemExit(f"signal {key}={val!r} invalid; expected one of {sorted(vocab)}")
    if signals.get("matched_title") is not None and not isinstance(signals["matched_title"], str):
        raise SystemExit("signal matched_title must be a string")
    return signals


def _enforce_title_first(category: str, signals: dict | None) -> None:
    """The adversarial title-check, enforced at record time. A `partial-match` asserts the cited
    work exists, so it must name the real publication it matched; `likely-hallucinated` asserts the
    cited title names no real work. This makes it impossible to file a fabricated title as a mere
    citation error (or vice versa) -- the conflation that misclassified a hallucinated reference and
    forced a long manual correction. 'unsure' has its own home: `unclear`."""
    s = signals or {}
    tm = s.get("title_match")
    if category == "partial-match":
        if tm not in {"yes", "na"}:
            raise SystemExit(
                "partial-match requires --signals with title_match=yes (the cited title names a "
                "real publication) or na (a non-publication resource such as a web page). If no "
                "work bears the cited title use likely-hallucinated; if you cannot tell use unclear.")
        if tm == "yes" and not (s.get("matched_title") or "").strip():
            raise SystemExit(
                "partial-match with title_match=yes requires signals.matched_title naming the real "
                "publication you matched (proves the cited title actually matches a real work).")
    elif category == "likely-hallucinated":
        if tm != "no":
            raise SystemExit(
                "likely-hallucinated requires --signals with title_match=no (no publication bears "
                "the cited title). If a work with the cited title exists use partial-match; if you "
                "cannot tell use unclear.")
    elif category == "unclear":
        if tm == "no":
            raise SystemExit(
                "unclear with title_match=no is contradictory: title_match=no asserts your search "
                "established that no publication bears the cited title, which is the "
                "likely-hallucinated verdict. If the search was not conclusive, record "
                "title_match=unsure; if it was, record likely-hallucinated.")


def is_fabrication(verdict: dict) -> bool:
    """Desk-reject heuristic: a `likely-hallucinated` verdict whose cited title names no real
    publication (signal T). That signal alone is the fabrication signature -- a real author group
    attached to an invented title (with the real authors and even the real venue otherwise intact)
    is the hardest and most important case to catch, so requiring a compounding signal would miss
    it. A fabricated author constellation (A), an impossible venue (V), or a dead/misresolving DOI
    (D) strengthen the case and are shown in the report, but are not required. The category gate
    matters too: only a verdict that *asserts* fabrication may desk-reject -- a hedged verdict
    must never be escalated past what its own category claims. Distinct from an honest slipped
    field on a real, locatable work (title_match=yes): a citation error, not a fabrication."""
    return (verdict.get("category") == "likely-hallucinated"
            and (verdict.get("signals") or {}).get("title_match") == "no")


def _signals_line(signals: dict | None) -> str | None:
    """One-line `title=… · authors=… · venue=… · doi=…` summary for the reports (omits unset keys)."""
    if not signals:
        return None
    order = ["title_match", "authors_match", "venue_match", "doi_status"]
    labels = {"title_match": "title", "authors_match": "authors",
              "venue_match": "venue", "doi_status": "doi"}
    parts = [f"{labels[k]}={signals[k]}" for k in order if signals.get(k) is not None]
    return " · ".join(parts) if parts else None


def _natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _ref_fp(raw: str) -> str:
    """Short fingerprint of a reference's raw text, stored alongside a verdict so the report can
    warn when a re-audit changed the reference the verdict was recorded against (numbering shifts)."""
    return hashlib.sha1((raw or "").encode("utf-8")).hexdigest()[:12]


def _verdict_is_stale(verdict: dict | None, ref: dict) -> bool:
    """True when the verdict was recorded against different reference text than `ref` now carries
    -- a re-audit renumbered the bibliography (author-year indices are extraction-order, so any
    extractor change can shift them). A stale verdict describes some *other* reference: applying
    it here would print an accusation against the wrong entry, so every consumer must treat the
    reference as un-triaged, not merely warn."""
    return bool(verdict and verdict.get("ref_hash")
                and verdict["ref_hash"] != _ref_fp(ref.get("raw_citation") or ""))


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a concurrent reader never sees a partial file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_verdicts(out_dir: Path) -> dict:
    path = out_dir / "triage_verdicts.json"
    return json.loads(path.read_text()) if path.exists() else {}


@contextlib.contextmanager
def _verdicts_lock(out_dir: Path):
    """Exclusive cross-process lock guarding the verdicts read-modify-write.

    `record` loads triage_verdicts.json, adds one key, and rewrites the whole file. Two concurrent
    records (parallel Stage 3 workers) otherwise interleave load/load/write/write and the second
    write drops the first's key -- a lost update. `_atomic_write` prevents torn *reads* but not lost
    updates, so the load+write must be serialized. The lock lives on a sidecar `.lock` file, not on
    the json itself: `_atomic_write` swaps the json via os.replace (a new inode), which would
    silently drop a lock held on the old one. On a platform without fcntl the lock degrades to a
    no-op (single-process use is unaffected)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / "triage_verdicts.json.lock"
    if fcntl is None:  # pragma: no cover -- non-POSIX fallback
        yield
        return
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _record_verdict(out_dir: Path, key: str, entry: dict) -> int:
    """Insert one verdict under an exclusive lock so concurrent records cannot lose each other's
    keys. Returns the total verdict count after the write."""
    path = out_dir / "triage_verdicts.json"
    with _verdicts_lock(out_dir):
        data = _load_verdicts(out_dir)
        data[key] = entry
        _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))
        return len(data)


def load_papers(out_dir: Path) -> list[dict]:
    """Per-paper JSON records in out_dir (any filename), naturally sorted. A file is a paper record
    iff it parses to a dict with a "references" list plus usable "paper_id" (str), "pdf_path"
    (str), and "num_references" (int) fields -- the consumers read them, and status/report would
    crash on a missing or null one. This excludes the pipeline's own outputs (summary / worklist /
    verdicts) by content -- so a paper whose name happens to collide with one of those is still
    included -- and skips any stray/unreadable .json rather than crashing the whole run. A
    near-miss (a "references" dict whose other fields are missing or malformed, e.g. after an
    audit schema drift) is skipped with a warning, not silently, so a whole corpus cannot vanish
    from Stage 3 undiagnosed."""
    out: list[dict] = []
    for f in sorted(out_dir.glob("*.json"), key=lambda f: _natural_key(f.name)):
        try:
            rec = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            print(f"warning: skipping unreadable JSON {f.name}", file=sys.stderr)
            continue
        if not (isinstance(rec, dict) and isinstance(rec.get("references"), list)):
            continue
        bad = [k for k, t in (("paper_id", str), ("pdf_path", str), ("num_references", int))
               if not isinstance(rec.get(k), t)]
        if bad:
            print(f"warning: skipping {f.name}: looks like a paper record but lacks "
                  f"valid {', '.join(bad)}", file=sys.stderr)
            continue
        out.append(rec)
    return out


def is_retracted(ref: dict) -> bool:
    return bool((ref.get("db_verification") or {}).get("retraction_info"))


def is_degraded(ref: dict) -> bool:
    """True when a backend failed to answer for this reference, so its unverified status is not
    a clean negative -- the databases that would have matched it may never have been asked."""
    return bool((ref.get("db_verification") or {}).get("degraded"))


def _matched_records(dv: dict) -> list[dict]:
    """The records individual backends matched, with the authors they hold. A `mismatch` means some
    backend found a candidate and disagreed about its fields -- that candidate, and how it differs,
    is the whole evidence base for the verdict, so it has to travel with the worklist entry."""
    out = []
    for r in dv.get("db_results") or []:
        if r.get("status") not in (None, "no_match", "skipped", "error", "rate_limited"):
            out.append({"db": r.get("db"), "status": r.get("status"),
                        "paper_url": r.get("paper_url"),
                        "found_authors": r.get("found_authors") or []})
    return out


def needs_triage(ref: dict) -> bool:
    # Needs triage iff the validator checked the reference (db_verification present) but did not
    # confirm it. Defined by negation of "verified" rather than a hard-coded list of failure
    # statuses, so a status such as hallucinator's "mismatch" can no longer fall through the list
    # and be silently dropped from the worklist and the report.
    dv = ref.get("db_verification")
    return dv is not None and dv.get("status") != "verified"


def ref_label(ref: dict) -> str:
    """How to name a reference in a report. Falls back to the tool-internal index for records
    written before the audit stored a label."""
    return ref.get("label") or f"#{ref.get('original_number')}"


def ref_key(ref: dict) -> str:
    """The label plus, when they differ, the internal index that `triage record` takes. Numeric
    bibliographies print their numbers, so label and key coincide there and nothing is repeated."""
    label, num = ref_label(ref), ref.get("original_number")
    return label if label in (f"[{num}]", f"#{num}") else f"{label} [#{num}]"


def label_note(paper: dict) -> str | None:
    """A line explaining the reference handles, when the paper's bibliography does not print
    numbers. Without it a reader hunts the PDF for a "#22" that was never there."""
    kinds = {r.get("label_kind") for r in paper.get("references") or []}
    if kinds <= {"printed"} or not kinds:
        return None
    return ("This bibliography is not numbered, so references are named by their citation key as "
            "the paper cites them. A trailing `[#n]` is hallucite's own index for that entry -- "
            "it appears nowhere in the paper, and is only what `triage record` takes as its "
            "`<number>` argument.")


def _title_key(ref: dict) -> str | None:
    """A comparison key for a reference's title, or None when there is too little to compare.

    Normalizes away the differences that make one bibliography entry appear twice rather than
    once: capitalization ("stack overflow" / "Stack Overflow"), punctuation, and the hyphen
    `pdftotext` leaves behind where a word was broken across lines ("architec-tural"). Hyphens go
    entirely rather than selectively, so a real compound compares equal to its line-broken form.
    Short titles are skipped, since a stub is not evidence of anything."""
    title = ((ref.get("parsed") or {}).get("title") or "").lower()
    key = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", title.replace("-", ""))).strip()
    return key if len(key) >= 20 else None


def _full_key(ref: dict) -> str:
    """A comparison key for the whole citation -- authors, title, venue, volume, pages -- with the
    disambiguation letter dropped, so "(2021a)" and "(2021b)" compare equal. Normalized like
    `_title_key`, so a line-break hyphen or a capitalized venue word cannot split a match."""
    raw = re.sub(r"\((\d{4})[a-z]\)", r"(\1)", ref.get("raw_citation") or "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", raw.lower().replace("-", ""))).strip()


def duplicate_groups(paper: dict) -> list[dict]:
    """Bibliography entries that cite the same authors and title under different citation keys,
    grouped in citation order and classified by how much of the citation matches.

    Two kinds, and the distinction is the whole point -- one is a fact, the other is a question:

    * `kind="duplicate"` -- every bibliographic field matches: authors, title, venue, volume,
      pages. Two distinct articles cannot share a journal, volume, and article number, so this is
      one work entered twice. Say so; there is nothing to weigh.
    * `kind="conflict"` -- the authors and title match but the venue, volume, or pages do not. Now
      it is genuinely open: either one work whose entries disagree about where it appeared, or
      separate works (an extended version, a preprint) sharing a title. Only what each citation key
      is used for in the text settles it.

    Neither is a fabrication, and neither is reachable by database verification -- every entry in
    such a group verifies perfectly well on its own, so only a whole-bibliography pass finds them.
    """
    groups: dict[str, list[dict]] = {}
    for ref in paper.get("references") or []:
        key = _title_key(ref)
        if key:
            groups.setdefault(key, []).append(ref)

    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        exact: dict[str, list[dict]] = {}
        for ref in members:
            exact.setdefault(_full_key(ref), []).append(ref)
        # Report the identical-in-every-field subsets as duplicates, and only what is left over as
        # a conflict, so a group that is part certain and part open reports both truthfully.
        dupes = [subset for subset in exact.values() if len(subset) > 1]
        for subset in dupes:
            out.append({"kind": "duplicate", "refs": subset})
        if len(exact) > 1:
            out.append({"kind": "conflict",
                        "refs": [subset[0] for subset in exact.values()]})
    return out


def cmd_worklist(out_dir: Path, pending: bool = False, paper_id: str | None = None) -> None:
    recorded = _load_verdicts(out_dir) if pending else {}
    papers = load_papers(out_dir)
    if paper_id is not None:
        # Fan-out safety: a parallel Stage 3 worker gets the slice for exactly one paper, so it
        # never has to self-filter a shared worklist by paper_id. Match by exact string equality
        # and fail loudly on an id that no audited paper carries -- a substring/prefix slip (asking
        # for "...paper6" when only "...paper66" exists, or vice versa) errors out instead of
        # silently writing another paper's references.
        known = {paper["paper_id"] for paper in papers}
        if paper_id not in known:
            raise SystemExit(
                f"no audited paper with paper_id == {paper_id!r}; "
                f"known paper_ids: {', '.join(sorted(known, key=_natural_key)) or '(none)'}")
        papers = [paper for paper in papers if paper["paper_id"] == paper_id]
    items = []
    for paper in papers:
        for ref in paper["references"]:
            if not needs_triage(ref):
                continue
            if pending:
                v = recorded.get(f"{paper['paper_id']}:{ref['original_number']}")
                # A stale verdict (recorded against different reference text, before a re-audit
                # renumbered the bibliography) does not count as done: the reference resurfaces
                # so it actually gets re-triaged, matching what report shows for it.
                if v is not None and not _verdict_is_stale(v, ref):
                    continue
            dv = ref["db_verification"]
            p = ref.get("parsed") or {}
            items.append({
                "paper_id": paper["paper_id"],
                "number": ref["original_number"],
                "label": ref_label(ref),
                "degraded": is_degraded(ref),
                "label_kind": ref.get("label_kind"),
                "status": dv["status"],
                "title": p.get("title"),
                "authors": p.get("authors", []),
                "doi": p.get("doi"),
                "arxiv_id": p.get("arxiv_id"),
                "failed_dbs": dv.get("failed_dbs", []),
                "raw_citation": ref["raw_citation"],
                # What a "mismatch" actually matched. Without it the triager re-derives from
                # scratch what the validator already had -- and cannot see that the candidate is
                # sometimes an unrelated work (a thesis carrying the same title as its paper),
                # which is what makes a mismatch a false positive rather than a citation error.
                "matched": _matched_records(dv),
                # Closest real records from CrossRef's fuzzy bibliographic search: leads to confirm
                # or reject. An empty list is itself informative -- nothing resembles this title.
                "candidates": ref.get("candidates", []),
            })
    # Per-paper slices go to their own file so concurrent workers never share (or clobber) the
    # corpus-wide triage_worklist.json.
    dest = out_dir / (f"triage_worklist-{paper_id}.json" if paper_id is not None
                      else "triage_worklist.json")
    _atomic_write(dest, json.dumps(items, indent=2, ensure_ascii=False))
    by_paper: dict[str, int] = {}
    for it in items:
        by_paper[it["paper_id"]] = by_paper.get(it["paper_id"], 0) + 1
    label = "pending " if pending else ""
    print(f"{len(items)} {label}references need triage across {len(by_paper)} papers "
          f"-> {dest}")
    for pid, n in sorted(by_paper.items(), key=lambda kv: _natural_key(kv[0])):
        print(f"  {pid}: {n}")


def _verify_sheet(paper: dict, items: list) -> str:
    """A manual-verification checklist for one paper's flagged references, with one-click
    search links so a human can confirm or refute each quickly."""
    def q(s: str) -> str:
        return urllib.parse.quote(s or "")
    lines = [f"# Manual verification: {paper['paper_id']}", "",
             f"- PDF: `{paper['pdf_path']}`",
             f"- {len(items)} reference(s) need a human check. Fill in each **Verdict** line.", ""]
    for ref, v in sorted(items, key=lambda x: ref_num(x[0])):
        p = ref.get("parsed") or {}
        title = p.get("title") or ""
        query = title or ref["raw_citation"][:120]
        links = [f"[Scholar](https://scholar.google.com/scholar?q={q(query)})",
                 f"[Google](https://www.google.com/search?q={q(query)})"]
        if p.get("doi"):
            links.append(f"[DOI](https://doi.org/{p['doi']})")
        if p.get("arxiv_id"):
            links.append(f"[arXiv](https://arxiv.org/abs/{p['arxiv_id']})")
        lines += [
            f"## {ref_key(ref)} -- {v['category']} (severity {SEVERITY.get(v['category'], '-')})",
            "",
            f"- **Verdict:** ____  (real / hallucinated / citation-error)",
            f"- Title: {title or '(not parsed)'}",
            f"- Authors: {', '.join(p.get('authors') or []) or '(not parsed)'}"
            + (f" · DOI: {p['doi']}" if p.get('doi') else "")
            + (f" · arXiv: {p['arxiv_id']}" if p.get('arxiv_id') else ""),
            f"- Raw citation: {ref['raw_citation']}",
        ]
        if is_fabrication(v):
            lines.append("- **Fabrication signal: cited title names no real publication "
                         "(desk-reject candidate).**")
        lines += _signal_report_lines(v)
        lines += [
            f"- Triage finding: {v.get('finding', '')}",
            f"- Search: " + " · ".join(links),
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _lint_reports(paths):
    """Auto-fix each generated report in place with the co-located Markdown linter, so the
    files this tool writes are valid Markdown by default. Best-effort: returns None (skips)
    if the vendored lint_markdown.py is not present next to this script."""
    linter = Path(__file__).resolve().parent / "lint_markdown.py"
    if not linter.is_file():
        return None
    clean = 0
    for p in paths:
        r = subprocess.run([sys.executable, str(linter), "--fix", str(p)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            clean += 1
        elif r.stdout:
            sys.stderr.write(r.stdout)
    return clean, len(paths)


def _signal_report_lines(verdict: dict | None) -> list[str]:
    """Markdown lines exposing the discriminating facts for a flagged reference: the matched real
    title (or its absence) and the one-line signal summary. This is what makes a fabricated-title
    verdict legible at a glance instead of buried in prose."""
    if not verdict:
        return []
    s = verdict.get("signals")
    if not s:
        return ["- Signals: (not recorded)"] if verdict.get("category") in FLAG_CATEGORIES else []
    out = []
    tm = s.get("title_match")
    if tm == "yes" and (s.get("matched_title") or "").strip():
        out.append(f"- Matched title: {s['matched_title'].strip()}")
    elif tm == "no":
        out.append("- Matched title: none — no publication bears the cited title")
    line = _signals_line(s)
    if line:
        out.append(f"- Signals: {line}")
    return out


def _warn_signal_contradiction(pid: str, number, verdict: dict | None) -> None:
    """Defend against hand-edited verdicts the record gate never saw: a partial-match whose signals
    say the title was not found is the exact contradiction that caused the original misfile."""
    if not verdict:
        return
    s = verdict.get("signals") or {}
    if verdict.get("category") == "partial-match" and s.get("title_match") == "no":
        print(f"warning: {pid}:{number} is partial-match but title_match=no (the cited title names "
              f"no publication) -- this should be likely-hallucinated; re-triage it.", file=sys.stderr)


def cmd_report(out_dir: Path) -> None:
    reports = out_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    verdicts = _load_verdicts(out_dir)

    # Remove previously generated reports first, so a re-categorized or removed flag cannot leave
    # an orphan behind (e.g. a stale verify-<pid>.md still claiming a human check is needed).
    for old in list(reports.glob("reference-check-*.md")) + list(reports.glob("verify-*.md")):
        old.unlink()
    (reports / "potential-hallucinations.md").unlink(missing_ok=True)

    flagged: list[tuple[dict, dict, dict]] = []  # (paper, ref, verdict)
    all_retracted: list[tuple[dict, dict]] = []  # (paper, ref) matched to a retracted record
    all_dupes: list[tuple[dict, list[dict]]] = []  # (paper, group of same-title references)
    written: list = []
    today = dt.date.today().isoformat()

    for paper in load_papers(out_dir):
        pid = paper["paper_id"]
        verified = [r for r in paper["references"]
                    if (r.get("db_verification") or {}).get("status") == "verified"]
        triage = [r for r in paper["references"] if needs_triage(r)]
        retracted = [r for r in paper["references"] if is_retracted(r)]
        pending = [r for r in paper["references"] if r.get("db_verification") is None]
        dupes = duplicate_groups(paper)

        lines = [f"# Reference check: {pid}", "",
                 f"- PDF: `{paper['pdf_path']}`",
                 f"- References: {paper['num_references']}",
                 f"- Verified by database: {len(verified)}",
                 f"- Needs triage (not in any database): {len(triage)}"]
        if pending:
            lines.append(f"- Not verified (--no-verify): {len(pending)}")
        if retracted:
            lines.append(f"- **RETRACTED: {len(retracted)}**")
        if dupes:
            nd = sum(1 for g in dupes if g["kind"] == "duplicate")
            nc = len(dupes) - nd
            parts = ([f"{nd} duplicated work(s)"] if nd else []) + \
                    ([f"{nc} conflicting group(s)"] if nc else [])
            lines.append("- Repeated bibliography entries: " + ", ".join(parts))
        lines.append("")
        note = label_note(paper)
        if note:
            lines += [note, ""]

        if triage:
            lines += ["## Triage", ""]
            for r in triage:
                v = verdicts.get(f"{pid}:{r['original_number']}")
                # A stale verdict belongs to whatever reference carried this number before the
                # re-audit; printing its category (or fabrication banner) here would flag the
                # wrong entry in the very files a reviewer acts on. Treat the reference as
                # un-triaged in the report, not just in a stderr warning.
                stale = _verdict_is_stale(v, r)
                if stale:
                    print(f"warning: verdict {pid}:{r['original_number']} was recorded against "
                          f"different reference text (re-audit changed it?); it is shown as "
                          f"stale and the reference as pending -- re-triage it.", file=sys.stderr)
                    v = None
                cat = v["category"] if v else "(pending)"
                sev = SEVERITY.get(cat, "-")
                htitle = ((r["parsed"] or {}).get("title") or r["raw_citation"][:70]).rstrip(" .,;:!?")
                _warn_signal_contradiction(pid, r["original_number"], v)
                lines.append(f"### {ref_key(r)} {htitle}")
                lines.append("")
                lines.append(f"- Raw: {r['raw_citation']}")
                dv = r["db_verification"]
                degraded = " **(degraded: " + ", ".join(dv.get("failed_dbs") or []) \
                    + " did not answer -- not a clean negative)**" if is_degraded(r) else ""
                lines.append(f"- DB status: {dv['status']}{degraded}")
                for m in _matched_records(dv):
                    lines.append(f"- Matched by {m['db']} ({m['status']}): {m['paper_url'] or '-'}"
                                 + (f" -- authors there: {', '.join(m['found_authors'])}"
                                    if m["found_authors"] else ""))
                for c in r.get("candidates") or []:
                    lines.append(
                        f"- CrossRef candidate (title similarity {c['title_similarity']}): "
                        f"{c['title']} -- {c.get('venue') or 'n/a'} {c.get('year') or ''} "
                        f"doi:{c.get('doi') or '-'}")
                lines.append(f"- Category: **{cat}** (severity: {sev})")
                if stale:
                    lines.append("- **Stale verdict:** a verdict was recorded here against "
                                 "different reference text (a re-audit renumbered this "
                                 "bibliography). It is not shown; re-triage this reference.")
                if v and is_fabrication(v):
                    lines.append("- **Fabrication signal: the cited title names no real "
                                 "publication (desk-reject candidate).**")
                if v and v.get("finding"):
                    lines.append(f"- Finding: {v['finding']}")
                lines += _signal_report_lines(v)
                lines.append("")
                if v and cat in FLAG_CATEGORIES:
                    flagged.append((paper, r, v))

        if retracted:
            lines += ["## Retracted references (cited despite retraction)", ""]
            for r in retracted:
                p = r.get("parsed") or {}
                rinfo = (r.get("db_verification") or {}).get("retraction_info") or {}
                htitle = (p.get("title") or r["raw_citation"][:70]).rstrip(" .,;:!?")
                lines += [f"### {ref_key(r)} {htitle}", "",
                          f"- Raw: {r['raw_citation']}",
                          f"- DB status: {(r.get('db_verification') or {}).get('status')}"]
                if rinfo.get("retraction_doi"):
                    lines.append(f"- Retraction DOI: {rinfo['retraction_doi']}")
                if rinfo.get("retraction_source"):
                    lines.append(f"- Source: {rinfo['retraction_source']}")
                lines.append("")
                all_retracted.append((paper, r))

        if dupes:
            lines += ["## Repeated bibliography entries", ""]
            for group in sorted(dupes, key=lambda g: ref_num(g["refs"][0])):
                refs = group["refs"]
                keys = ", ".join(ref_label(r) for r in refs)
                title = ((refs[0]["parsed"] or {}).get("title") or "").rstrip(" .,;:!?")
                if group["kind"] == "duplicate":
                    lines += [f"### Duplicate: {keys}", "",
                              "These entries are identical in every field -- authors, title, "
                              "venue, volume, and pages. Two distinct works cannot share a venue, "
                              "volume, and article number, so this is one work entered more than "
                              "once under different citation keys. Fix the bibliography and point "
                              "the in-text citations at a single key.", ""]
                else:
                    lines += [f"### Conflicting: {keys}", "",
                              "Same authors and title, but the venue, volume, or pages disagree. "
                              "Either one work whose entries disagree about where it appeared, or "
                              "separate works (an extended version, a preprint) sharing a title -- "
                              "check what each key is cited for in the text before changing "
                              "anything.", ""]
                lines.append(f"Cited title: {title}")
                lines.append("")
                for r in refs:
                    lines.append(f"- **{ref_label(r)}** -- {r['raw_citation']}")
                lines.append("")
                all_dupes.append((paper, group))

        report_path = reports / f"reference-check-{pid}.md"
        _atomic_write(report_path, "\n".join(lines).rstrip("\n") + "\n")
        written.append(report_path)

    # Corpus rollup for human review.
    roll = ["# Potentially hallucinated references", "",
            f"Generated: {today}", ""]
    if all_retracted:
        roll += [f"## Retracted references still cited ({len(all_retracted)})", "",
                 "Matched to a record flagged as retracted; confirm each and treat it as serious.", ""]
        for paper, r in sorted(all_retracted,
                               key=lambda x: (_natural_key(x[0]["paper_id"]), ref_num(x[1]))):
            title = (r.get("parsed") or {}).get("title") or r["raw_citation"][:80]
            roll.append(f"- **{paper['paper_id']}** {ref_key(r)}: {title}")
        roll.append("")
    if all_dupes:
        dup = [(pp, g) for pp, g in all_dupes if g["kind"] == "duplicate"]
        con = [(pp, g) for pp, g in all_dupes if g["kind"] == "conflict"]
        roll += [f"## Repeated bibliography entries ({len(all_dupes)} groups)", "",
                 "Not fabrications: every entry below verifies on its own, which is why only a "
                 "whole-bibliography pass finds them.", ""]
        if dup:
            roll += [f"**Duplicates ({len(dup)})** -- identical in every field, so one work "
                     "entered more than once under different citation keys.", ""]
            for paper, g in sorted(dup, key=lambda x: (_natural_key(x[0]["paper_id"]),
                                                       ref_num(x[1]["refs"][0]))):
                keys = ", ".join(ref_label(r) for r in g["refs"])
                title = ((g["refs"][0]["parsed"] or {}).get("title") or "").rstrip(" .,;:!?")
                roll.append(f"- **{paper['paper_id']}** {keys}: {title}")
            roll.append("")
        if con:
            roll += [f"**Conflicting ({len(con)})** -- same authors and title, but the venue, "
                     "volume, or pages disagree; check the in-text usage of each key.", ""]
            for paper, g in sorted(con, key=lambda x: (_natural_key(x[0]["paper_id"]),
                                                       ref_num(x[1]["refs"][0]))):
                keys = ", ".join(ref_label(r) for r in g["refs"])
                title = ((g["refs"][0]["parsed"] or {}).get("title") or "").rstrip(" .,;:!?")
                roll.append(f"- **{paper['paper_id']}** {keys}: {title}")
            roll.append("")
    if not flagged:
        roll.append("No references were flagged as likely-hallucinated, partial-match, or unclear.")
    else:
        # Group by paper; rank papers by their count of high-severity (likely-hallucinated) flags.
        by_paper: dict[str, list] = {}
        for paper, ref, v in flagged:
            by_paper.setdefault(paper["paper_id"], []).append((paper, ref, v))

        def sev_counts(items):
            c = {"high": 0, "medium": 0, "other": 0}
            for _, _, v in items:
                s = SEVERITY.get(v["category"], "-")
                c["high" if s == "high" else "medium" if s == "medium" else "other"] += 1
            return c

        ranked = sorted(by_paper.items(),
                        key=lambda kv: (-sev_counts(kv[1])["high"], -len(kv[1]), kv[0]))

        hi = sum(1 for _, _, v in flagged if SEVERITY.get(v["category"]) == "high")
        med = sum(1 for _, _, v in flagged if SEVERITY.get(v["category"]) == "medium")
        roll += [f"**{len(flagged)} references flagged** for human review across "
                 f"{len(by_paper)} papers: **{hi} likely-hallucinated**, {med} partial-match "
                 f"(citation errors), {len(flagged) - hi - med} unclear.", "",
                 "| Paper | likely-hallucinated | partial-match | unclear |",
                 "|---|---|---|---|"]
        for pid, items in ranked:
            c = sev_counts(items)
            roll.append(f"| {pid} | {c['high']} | {c['medium']} | {c['other']} |")
        roll.append("")

        # Desk-reject candidates: papers with a reference whose cited title names no real
        # publication, compounded by a fabricated author constellation, venue, or DOI. These are the
        # references that are hard to explain as honest error.
        fab = [(paper, ref, v) for paper, ref, v in flagged if is_fabrication(v)]
        if fab:
            fab_papers = sorted({p["paper_id"] for p, _, _ in fab}, key=_natural_key)
            roll += [f"## Desk-reject candidates ({len(fab_papers)})", "",
                     "References whose cited **title matches no real publication** -- a fabrication "
                     "signature, not a citation error. The signal line shows any compounding author, "
                     "venue, or DOI problems. Confirm each before acting.", ""]
            for paper, ref, v in sorted(fab, key=lambda x: (_natural_key(x[0]["paper_id"]), ref_num(x[1]))):
                title = (ref["parsed"] or {}).get("title") or ref["raw_citation"][:80]
                roll.append(f"- **{paper['paper_id']}** {ref_key(ref)}: {title}")
                sline = _signals_line(v.get("signals"))
                if sline:
                    roll.append(f"  - Signals: {sline}")
            roll.append("")

        for pid, items in ranked:
            roll.append(f"## {pid}")
            roll.append("")
            for paper, ref, v in sorted(items, key=lambda x: ref_num(x[1])):
                title = (ref["parsed"] or {}).get("title") or ""
                roll.append(f"- **{ref_key(ref)} -- {v['category']}** "
                            f"(severity {SEVERITY.get(v['category'], '-')}): {title}")
                roll.append(f"  - Raw: {ref['raw_citation']}")
                for extra in _signal_report_lines(v):
                    roll.append(f"  {extra}")
                roll.append(f"  - Finding: {v.get('finding', '')}")
            roll.append("")
    rollup_path = reports / "potential-hallucinations.md"
    _atomic_write(rollup_path, "\n".join(roll).rstrip("\n") + "\n")
    written.append(rollup_path)

    # One manual-verification sheet per paper that has flagged references.
    vby: dict = {}
    for paper, ref, v in flagged:
        vby.setdefault(paper["paper_id"], (paper, []))[1].append((ref, v))
    for pid, (paper, its) in vby.items():
        verify_path = reports / f"verify-{pid}.md"
        _atomic_write(verify_path, _verify_sheet(paper, its))
        written.append(verify_path)

    lint_summary = _lint_reports(written)
    print(f"Wrote to {reports}/: per-paper reference-check reports, "
          f"potential-hallucinations.md, and {len(vby)} verify-*.md sheets ({len(flagged)} flagged).")
    if lint_summary is not None:
        clean, total = lint_summary
        suffix = "" if clean == total else " (residual findings above)"
        print(f"Markdown lint: {clean}/{total} report(s) clean{suffix}")


def ref_num(ref: dict) -> int:
    return ref["original_number"]


def cmd_record(out_dir: Path, paper_id: str, number: str, category: str, finding: str,
               signals: dict | None = None) -> None:
    if category not in SEVERITY:
        raise SystemExit(f"unknown category {category!r}; expected one of {sorted(SEVERITY)}")
    if signals is not None:
        _validate_signals(signals)
    # Title-first gate: partial-match / likely-hallucinated cannot be recorded without signals that
    # back the category (a named matched title, or an explicit "no publication has this title").
    _enforce_title_first(category, signals)
    if signals and category.startswith("real-") and signals.get("title_match") == "no":
        print(f"warning: {paper_id}:{number} recorded as {category} but title_match=no "
              f"(no publication bears the cited title?); re-check -- this looks fabricated.",
              file=sys.stderr)
    # Reject typo'd keys: a verdict whose paper_id:number matches no audited reference would
    # sit in triage_verdicts.json forever and never appear in any report -- a triage result
    # silently discarded. Worklists are machine-generated, so an unknown key is an error.
    papers = load_papers(out_dir)
    refs = {f"{p['paper_id']}:{r['original_number']}": r.get("raw_citation", "")
            for p in papers for r in p["references"]}
    degraded = {f"{p['paper_id']}:{r['original_number']}"
                for p in papers for r in p["references"] if is_degraded(r)}
    key = f"{paper_id}:{number}"
    # A degraded check means some databases never answered for this reference, so its "not_found"
    # is not evidence of anything. The web search has to carry a fabrication verdict on its own.
    if category == "likely-hallucinated" and key in degraded:
        print(f"warning: {key} is being recorded as likely-hallucinated, but its database "
              f"verification was degraded (a backend failed to answer), so the absence of a "
              f"database record is not evidence here. Confirm the verdict rests entirely on your "
              f"own searches, or use 'unclear'.", file=sys.stderr)
    if not refs:
        raise SystemExit(f"no audited paper records found in {out_dir}/ -- run the audit before "
                         f"recording verdicts.")
    if key not in refs:
        raise SystemExit(f"{key} matches no reference in {out_dir}/ -- the verdict would never "
                         f"appear in any report. Re-check the paper_id and number (the worklist "
                         f"entry's `number` field).")
    entry = {"category": category, "finding": finding,
             "ref_hash": _ref_fp(refs[key])}
    if signals:
        entry["signals"] = signals
    total = _record_verdict(out_dir, key, entry)
    print(f"recorded {paper_id}:{number} = {category} ({total} verdicts total)")


def cmd_status(out_dir: Path) -> None:
    recorded = _load_verdicts(out_dir)
    rows = []
    for paper in load_papers(out_dir):
        pid = paper["paper_id"]
        needs = [r for r in paper["references"] if needs_triage(r)]
        # A stale verdict counts as pending, consistent with worklist --pending and report.
        done = sum(1 for r in needs
                   if (v := recorded.get(f"{pid}:{r['original_number']}")) is not None
                   and not _verdict_is_stale(v, r))
        rows.append((pid, paper["num_references"], len(needs), done, len(needs) - done))
    print(f"{'paper':<28}{'refs':>6}{'needs':>7}{'done':>6}{'pending':>9}")
    for pid, refs, needs, done, pend in sorted(rows, key=lambda r: _natural_key(r[0])):
        mark = "  complete" if needs and pend == 0 else ""
        print(f"{pid:<28}{refs:>6}{needs:>7}{done:>6}{pend:>9}{mark}")
    tn = sum(r[2] for r in rows)
    td = sum(r[3] for r in rows)
    print(f"\n{len(rows)} papers | needs review: {tn} | recorded: {td} | pending: {tn - td}")


def main() -> int:
    p = argparse.ArgumentParser(description="Stage 3 triage worklist / status / record / report.")
    sub = p.add_subparsers(dest="command", required=True)
    wl = sub.add_parser("worklist")
    wl.add_argument("--out", default="out")
    wl.add_argument("--pending", action="store_true",
                    help="only references not already recorded in triage_verdicts.json")
    wl.add_argument("--paper", default=None,
                    help="emit only this paper_id's references (exact match) to "
                         "triage_worklist-<paper_id>.json; errors if the id is unknown. "
                         "Hand one slice to each parallel Stage 3 worker so it never self-filters.")
    sub.add_parser("status").add_argument("--out", default="out")
    sub.add_parser("report").add_argument("--out", default="out")
    rec = sub.add_parser("record")
    rec.add_argument("paper_id")
    rec.add_argument("number")
    rec.add_argument("category")
    rec.add_argument("finding")
    rec.add_argument("--signals", default=None,
                     help='JSON object of fabrication signals, e.g. '
                          '\'{"title_match":"no","authors_match":"yes","venue_match":"no",'
                          '"doi_status":"none"}\'. Required for partial-match (title_match=yes|na, '
                          'plus matched_title when yes) and likely-hallucinated (title_match=no).')
    rec.add_argument("--out", default="out")
    args = p.parse_args()
    out = Path(args.out)
    if args.command == "worklist":
        cmd_worklist(out, pending=args.pending, paper_id=args.paper)
    elif args.command == "status":
        cmd_status(out)
    elif args.command == "report":
        cmd_report(out)
    else:
        signals = None
        if args.signals is not None:
            try:
                signals = json.loads(args.signals)
            except json.JSONDecodeError as ex:
                raise SystemExit(f"--signals is not valid JSON: {ex}")
        cmd_record(out, args.paper_id, args.number, args.category, args.finding, signals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
