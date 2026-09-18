"""The mutation run: revert one fix at a time and require the smoke suite to fail.

A guard that asserts a helper the pipeline is free to ignore, or pins a constant by reading it back
from the module, passes whether or not the fix it names is in place. Seven fixes were once found
revertible with the suite green. Each entry below names a fix by the text that carries it and the
text that reverts it; the runner swaps them in, runs the suite, and puts the file back whatever
happens. Add an entry with every fix that gets a guard, and re-run:

    mutations.py                       # every entry
    mutations.py "lenient tier"        # entries whose label contains the text
    mutations.py --jobs 4 "dblp:"      # four at a time

Every entry must end in `suite FAILS`; an entry the runner cannot find in the file is reported as
SKIPPED, which means the fix has been rewritten and the entry needs updating.

The run never touches the working tree. It copies the tracked tree into a scratch directory per
worker, reverts one fix inside a copy, and runs the suite there, so entries run in parallel and
the tree stays free to edit and to measure against while they do. What it measures is the snapshot
taken when it started, which is the honest answer either way: a tree edited mid-run would otherwise
fail a suite run for a reason that has nothing to do with the revert, and that reads as "this fix
is guarded" -- the one conclusion this run exists to prevent.

Two things make it quick enough to run after every fix, which is the point: the copies run
concurrently (`--jobs`, defaulting to the machine's cores less two), and each suite run stops at
its first failing check (`SMOKE_FAIL_FAST`), since the only question here is whether any check
noticed. Serially and in full it was about 84 s an entry.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[2]
SMOKE = SCRIPTS / "tests" / "run_smoke.py"
P = SCRIPTS / "pdf_references.py"
R = SCRIPTS / "reference_parser.py"
D = SCRIPTS / "dblp_check.py"
A = SCRIPTS / "audit_references.py"
T = SCRIPTS / "triage.py"
V = SCRIPTS / "verifier.py"
VR = SCRIPTS / "verification_results.py"
F = SCRIPTS / "fetch_dblp_dump.py"

# (label, file, the text as fixed, the text reverted)
MUTATIONS = [
    ("extract: continuation lines opening with digits vote numeric", P,
     "        elif _NUM.match(s):             # \"12.\" / \"12  ...\" (also lineno-prefixed continuations)\n"
     "            if opens:\n                num += 1",
     "        elif _NUM.match(s):\n            num += 1"),
    ("extract: an entry needs a (year) even under a hanging indent", P,
     "        elif entry_col is not None and opens and _ENTRY_HEAD.match(s):\n            ay += 1",
     "        elif False:\n            ay += 1"),
    ("extract: _AUTHORYEAR gates entries under a hanging indent", P,
     "                starts = indent <= entry_col and bool(_ENTRY_HEAD.match(s))",
     "                starts = indent <= entry_col and bool(_AUTHORYEAR.match(s))"),
    ("extract: the right column is not aligned to the left", P,
     "    le, re_ = _text_edge(left), _text_edge(right)\n"
     "    if le is None or re_ is None or le == re_:\n        return right",
     "    return right\n    le, re_ = _text_edge(left), _text_edge(right)\n"
     "    if le is None or re_ is None or le == re_:\n        return right"),
    ("extract: the author biographies are not cut off", P,
     "    if entry_col is not None:\n        section = _hanging_block(section, entry_col)",
     "    pass"),
    ("parse: a hyphenated initial ends the author sentence", R,
     'r"(?:^|[\\s(\\[.\\-])(?:[A-Z]|proc|', 'r"(?:^|[\\s(\\[.])(?:[A-Z]|proc|'),
    ("parse: Elsevier's ', in:' venue stays in the title", R,
     '    t = _TRAILING_IN_VENUE.sub("", t)\n', ''),
    ("parse: hyphenated initials are not initials-led", R,
     '_INITIALS_LED = re.compile(r"^(?:and\\s+)?[A-Z]\\.(?:\\s*-?\\s*[A-Z]\\.)*\\s+\\S")',
     '_INITIALS_LED = re.compile(r"^(?:and\\s+)?[A-Z]\\.(?:\\s*[A-Z]\\.)*\\s+\\S")'),
    ("parse: a dotted lowercase initial is rejected", R,
     '_INITIALS_ONLY = re.compile(r"^(?=.*[A-Z])(?:[A-Z]\\.?[\\s-]*|[a-z]\\.[\\s-]*){1,4}$")',
     '_INITIALS_ONLY = re.compile(r"^(?:[A-Z]\\.?[\\s-]*){1,4}$")'),
    ("parse: `URL https://` is the identifier's label, not a title word", R,
     '(?:\\burl\\s+)?https?://', 'https?://'),
    ("parse: a ? or ! is judged on the text up to the next mark", R,
     '        nm = re.search(r"[?!](?=\\s)", nxt)\n        if nm:\n            nxt = nxt[:nm.end()]\n',
     ''),
    ("parse: the quoted opener's venue test stops at `, in:`", R,
     '_TRAILING_IN_VENUE.sub("", after[:_sentence_end(after)])', 'after[:_sentence_end(after)]'),
    ("parse: a roman numeral heading is not a sentence", R,
     'or _ROMAN_HEAD.match(text[start:m.end()].lstrip())', 'or False'),
    ("parse: the role after IEEE's names is not the title", R,
     '    rest = _LEADING_ROLE.sub("", ", ".join(fields[taken:]))',
     '    rest = ", ".join(fields[taken:])'),
    ("parse: an `et al.,` entry delimits its fields with commas", R,
     '        if m.group(0).rstrip().endswith(",") and rest[:1] not in _OPEN_Q:', '        if False:'),
    ("parse: a bare publisher field ends the title", R,
     'or _BARE_VENUE.match(tail)', 'or False'),
    ("parse: volume (issue) (year) is a venue on its own", R,
     '    if _VOLUME_ISSUE_YEAR.search(s):\n        return True\n', ''),
    ("parse: a DOI broken on its own period is rejoined", R,
     'or _continues(raw, rest.group(1))', 'or False'),
    ("parse: a two-character DOI suffix is a cut", R,
     '    if len(_doi_suffix(doi)) <= 2:\n        return True\n', ''),
    ("dblp: the edition suffix stays on the record", D,
     '    candidate = _EDITION_SUFFIX.sub("", candidate or "")\n', ''),
    ("dblp: a parenthesised alias stays in the name", D,
     '    tokens = re.split(r"[\\s.,]+", name.replace("(", " ").replace(")", " "))',
     '    tokens = re.split(r"[\\s.,]+", name)'),
    ("dblp: no leave-a-pair-out retrieval fallback", D,
     "            for q in _glued_query(title) + _dropped_pair_queries(title):",
     "            for q in _glued_query(title):"),
    ("dblp: the lenient tier is a wildcard", D,
     "    return matched >= 1 or not _lists_people(candidate)", "    return True"),
    ("dblp: a byline of one-word names reads as a group", D,
     "    return len(entries) >= 2 or any(len(a.split()) >= 2 for a in entries)",
     "    return any(len(a.split()) >= 2 for a in entries)"),
    ("dblp: an umlaut does not read as its transliteration", D,
     "    if _UMLAUT.search(composed):", "    if False:"),
    ("dblp: the nearest title needs no cited person on it", D,
     '        if authors_match(list(authors), candidate["authors"], record_complete=True):',
     "        if True:"),
    ("dblp: the nearest title may be three word edits away", D,
     "_NEAREST_EDITS = 2", "_NEAREST_EDITS = 3"),
    ("dblp: the cited DOI does not choose among shared-title records", D,
     "                            not doi_match(c, dois),\n", ""),
    ("dblp: the cited page range does not choose among shared-title records", D,
     "                            not pages_match(c, raw),\n", ""),
    ("dblp: the cited volume does not choose among shared-title records", D,
     "                            not volume_match(c, raw),\n", ""),
    ("dblp: the year is read before the locator the citation prints", D,
     "                            not doi_match(c, dois),\n"
     "                            not pages_match(c, raw),\n"
     "                            not volume_match(c, raw),\n"
     "                            str(c.year) not in years))",
     "                            str(c.year) not in years,\n"
     "                            not doi_match(c, dois),\n"
     "                            not pages_match(c, raw),\n"
     "                            not volume_match(c, raw)))"),
    ("dblp: the year the citation prints does not choose among shared-title records", D,
     "                            str(c.year) not in years))",
     "                            False))"),
    ("dblp: the preprint may come before the published record", D,
     '    out.sort(key=lambda c: ((c.venue or "").strip().lower() == "corr",\n',
     "    out.sort(key=lambda c: (False,\n"),
    ("dblp: the locator outranks the published record", D,
     '    out.sort(key=lambda c: ((c.venue or "").strip().lower() == "corr",\n'
     "                            not doi_match(c, dois),",
     "    out.sort(key=lambda c: (not doi_match(c, dois),\n"
     '                            (c.venue or "").strip().lower() == "corr",'),
    ("verifier: the search API's refusal is never put to OAI-PMH", V,
     '        for arxiv_id in [i for i in ids if outcome_of.get(i) != "ok"][:_ARXIV_OAI_CAP]:',
     "        for arxiv_id in []:"),
    ("verifier: the OAI-PMH fallback is unbounded", V,
     "[:_ARXIV_OAI_CAP]:", "[:]:"),
    ("verifier: an OAI-PMH idDoesNotExist reads as a failure", V,
     '        return None, "not_found" if (error.get("code") or "") == "idDoesNotExist" else ERROR',
     "        return None, ERROR"),
    ("verifier: a malformed contact still raises CrossRef concurrency", V,
     '        self.mailto = mailto if is_contact(mailto) else ""',
     "        self.mailto = mailto"),
    ("audit: the candidate lookup sends a contact the verifier would drop", A,
     '    if is_contact(mailto):\n        params["mailto"] = mailto',
     '    if mailto:\n        params["mailto"] = mailto'),
    ("verifier: the contact check is stricter than CrossRef's", V,
     '    return "@" in value and bool(value.split("@", 1)[0].strip())',
     '    return "@" in value and "." in value.split("@", 1)[1]'),
    ("verifier: the citation's years never reach the mirror", V,
     '        candidates = title_candidates(self.dblp_path, title, cited_years(raw), raw,\n'
     '                                      getattr(ref, "doi", None))',
     "        candidates = title_candidates(self.dblp_path, title)"),
    ("verifier: the citation's text and DOI never reach the mirror", V,
     '        candidates = title_candidates(self.dblp_path, title, cited_years(raw), raw,\n'
     '                                      getattr(ref, "doi", None))',
     "        candidates = title_candidates(self.dblp_path, title, cited_years(raw))"),
    ("fetch: the download is installed without checking it at all", F,
     "    refusal = accept(scratch, digest, checksum)\n    if refusal:\n        scratch.unlink(missing_ok=True)\n        return refusal",
     '    refusal = ""'),
    ("verifier: OpenAlex is not asked whether the byline was cut", V,
     '_OPENALEX_FIELDS = "id,doi,title,display_name,type,authorships,is_authors_truncated,is_retracted"',
     '_OPENALEX_FIELDS = "id,doi,title,display_name,type,authorships,is_retracted"'),
    ("verifier: arXiv is asked unpaced between batches", V,
     "_ARXIV_PAUSE = 3.0", "_ARXIV_PAUSE = 0.0"),
    ("verifier: arXiv batches one identifier per request", V,
     "_ARXIV_BATCH = 100", "_ARXIV_BATCH = 1"),
    ("verifier: an identifier a batch omitted is never re-asked alone", V,
     "_ARXIV_RECHECK = 20", "_ARXIV_RECHECK = 0"),
    ("verifier: the harvesting fallback is unbounded", V,
     "_ARXIV_OAI_CAP = 60", "_ARXIV_OAI_CAP = 100000"),
    ("fetch: the snapshot walk looks back one month only", F,
     "_LOOKBACK_MONTHS = 6", "_LOOKBACK_MONTHS = 1"),
    ("fetch: the download's digest is not of the bytes it wrote", F,
     "            digest.update(chunk)", "            pass"),
    ("verifier: the OAI-PMH fallback asks unpaced", V,
     '        time.sleep(_ARXIV_PAUSE)\n        params = {"verb": "GetRecord"',
     '        params = {"verb": "GetRecord"'),
    ("fetch: only the current month's snapshot is looked for", F,
     "    for back in range(_LOOKBACK_MONTHS):", "    for back in range(1):"),
    ("fetch: a checksum the release disagrees with is swapped in", F,
     "    if expected and digest != expected:", "    if False:"),
    ("fetch: a saved web page is ingested as a dump", F,
     r'    if magic != b"\x1f\x8b":', "    if False:"),
    ("verification_results: a bare percent sign in argparse help text", VR,
     "reproducible, and the 89.4%% of ", "reproducible, and the 89.4% of "),
    ("verifier: OpenAlex's cut byline reads as complete", V,
     '    if names and item.get("is_authors_truncated"):\n        names.append("et al.")\n', ""),
    ("verifier: a retraction OpenAlex marks is dropped", V,
     "    retracted = bool(item.get(\"is_retracted\")) or bool(_RETRACTED_TITLE.match(raw_title))",
     "    retracted = bool(_RETRACTED_TITLE.match(raw_title))"),
    ("verifier: a 200 from OpenAlex without `results` reads as a negative", V,
     '                if outcome != "ok" or not isinstance(payload, dict) or "results" not in payload:',
     '                if outcome != "ok":'),
    ("verifier: OpenAlex keeps asking after the day's budget is gone", V,
     "            if not title or refused_in_a_row >= _OPENALEX_GIVE_UP_AFTER:",
     "            if not title:"),
    ("verifier: OpenAlex retries a refusal", V,
     "                    self.user_agent, 0)", "                    self.user_agent, self.rate_limit_retries)"),
    ("verifier: OpenAlex's title travels unquoted", V,
     """                params = {"filter": 'title.search:"' + _FILTER_BREAKS.sub(" ", form) + '"',""",
     """                params = {"filter": "title.search:" + form,"""),
    ("verifier: a quotation mark stays inside OpenAlex's quoted filter value", V,
     "_FILTER_BREAKS = re.compile(\"[\\\"\\u201c\\u201d\\u201e\\u201f\\u00ab\\u00bb?]\")",
     "_FILTER_BREAKS = re.compile(\"[\\\"]\")"),
    ("verifier: a question mark stays in OpenAlex's filter value", V,
     "_FILTER_BREAKS = re.compile(\"[\\\"\\u201c\\u201d\\u201e\\u201f\\u00ab\\u00bb?]\")",
     "_FILTER_BREAKS = re.compile(\"[\\\"\\u201c\\u201d\\u201e\\u201f\\u00ab\\u00bb]\")"),
    ("verifier: a review of the book is the book", V,
     '                records = [_openalex_record(w) for w in payload.get("results") or []\n'
     '                           if w.get("type") not in _OPENALEX_NOT_THE_WORK]',
     '                records = [_openalex_record(w) for w in payload.get("results") or []]'),
    ("verifier: the retraction marker stays in an OpenAlex title", V,
     '    title = _plain(_RETRACTED_TITLE.sub("", raw_title))', '    title = _plain(raw_title)'),
    ("verifier: OpenAlex is not asked by the subtitle head", V,
     "    if _subtitle_head(title):\n        head = _SUBTITLE.split(title, maxsplit=1)[0].strip()\n"
     "        if head and head not in forms:\n            forms.append(head)\n", ""),
    ("triage: authors_absent is not read off the matched record", T,
     '    return absent_authors((ref.get("parsed") or {}).get("authors") or [], dv["found_authors"])',
     '    return []'),
    ("audit: a configured CrossRef contact is ignored", A,
     '    return os.environ.get("CROSSREF_MAILTO", "").strip()', '    return ""'),
    ("audit: the nearest title is asked for whatever the mirror said", A,
     '        if any(r.get("db") == DBLP and r.get("status") == NO_MATCH\n'
     '               for r in v.get("db_results") or []):',
     "        if True:"),
    ("triage: a skipped backend is not reported as never asked", T,
     '            if r.get("status") == "skipped"]', "            if False]"),
    ("triage: every resolved title reads as the cited one", T,
     '                    "cited_title": titles_match(cited, title) if title else None})',
     '                    "cited_title": True if title else None})'),
]


def _snapshot(into: Path) -> Path:
    """The tracked tree, copied. Working-tree content, not HEAD: what is being measured is what is
    on disk right now, uncommitted edits included."""
    listing = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"],
                             capture_output=True, text=True, check=True).stdout
    for rel in listing.split("\0"):
        if not rel:
            continue
        src, dst = REPO / rel, into / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        # The plugin layout is held together by symlinks (`plugins/hallucite -> ..`), which git
        # tracks as links. Copied by content they become directories and the copy loops; recreated
        # as links they point where they did, which is what the packaging tiers read.
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        elif src.exists():
            shutil.copy2(src, dst)
    return into


def _run_entry(entry, workdir: Path) -> tuple[str, bool, str]:
    """(label, ok, detail) for one revert, run entirely inside `workdir`."""
    label, path, fixed, reverted = entry
    rel = path.relative_to(REPO)
    target = workdir / rel
    src = target.read_text(encoding="utf-8")
    if src.count(fixed) != 1:
        return label, False, f"SKIPPED: the fixed text occurs {src.count(fixed)} times"
    try:
        target.write_text(src.replace(fixed, reverted), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(workdir / rel.parts[0] / "hallucite" / "scripts" / "tests"
                                 / "run_smoke.py")],
            capture_output=True, text=True,
            env={**os.environ, "SMOKE_FAIL_FAST": "1"}, cwd=str(workdir))
    finally:
        target.write_text(src, encoding="utf-8")
    failed = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("FAIL")]
    if proc.returncode != 0:
        return label, True, f"suite FAILS ({len(failed)} check(s)): {failed[0][:110] if failed else ''}"
    return label, False, "suite PASSES: the fix is revertible, add a guard"


def main() -> int:
    argv = sys.argv[1:]
    jobs = max(1, (os.cpu_count() or 4) - 2)
    if "--jobs" in argv:
        i = argv.index("--jobs")
        jobs = max(1, int(argv[i + 1]))
        del argv[i:i + 2]
    entries = [e for e in MUTATIONS if not argv or any(o in e[0] for o in argv)]
    if not entries:
        print("no entry matches")
        return 1
    jobs = min(jobs, len(entries))

    with tempfile.TemporaryDirectory(prefix="hallucite-mutations-") as tmp:
        root = Path(tmp)
        print(f"{len(entries)} entr(y|ies), {jobs} at a time, in copies of the tracked tree",
              flush=True)
        workdirs = [_snapshot(root / f"w{i}") for i in range(jobs)]
        queue: list = list(entries)
        bad = 0

        def worker(workdir: Path) -> list[tuple[str, bool, str]]:
            out = []
            while True:
                try:
                    entry = queue.pop()
                except IndexError:
                    return out
                out.append(_run_entry(entry, workdir))

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            for got in pool.map(worker, workdirs):
                for label, ok, detail in got:
                    print(f"{label:60s} -> {detail}", flush=True)
                    bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
