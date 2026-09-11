#!/usr/bin/env python3
"""Stages 1+2 of the hallucinated-reference audit: extract references from paper
PDF files and verify them against academic databases (offline DBLP + CrossRef/
arXiv/Semantic Scholar/...), with no LLM involvement.

Reference extraction is `lineno`-aware (see pdf_references.py); each extracted
reference is parsed by `reference_parser` and verified by `verifier`, both of which implement
`VERIFICATION-SPEC.md` against the offline DBLP mirror plus CrossRef, DOI resolution, arXiv
and Semantic Scholar.

Writes one JSON record per paper to the output directory, plus a corpus-level
summary.json. References the databases did not confirm (any status other than
"verified" -- e.g. not_found, mismatch, unparsed) are what the later interactive
LLM triage step investigates.

Usage (or run `mise run audit` from the repo root):
    python audit_references.py <pdf-file-or-dir> [options]

Options:
    --dblp PATH         Offline DBLP SQLite database
                        (default: $HALLUCITE_DBLP, else ~/hallucite/dblp.db)
    --out DIR           Output directory (default: out)
    --mailto EMAIL      CrossRef polite-pool contact (optional; recommended for CrossRef)
    --s2-api-key KEY    Semantic Scholar key ($S2_API_KEY). Without one S2 rate-limits,
                        leaving references degraded and the worklist varying between runs
    --offline           No network: disable the online database backends.
                        The offline DBLP mirror stays live.
    --disable-dbs LIST  Comma-separated DB names to disable
    --no-verify         Extract only; skip database verification (fast, offline)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time
import traceback
import unicodedata
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

import reference_parser
from dblp_check import nearest_title, record_context
from verifier import DBLP, NO_MATCH, Verifier
from pdf_references import _parse, extract_references

SCHEMA_VERSION = "1.0"

# Offline DBLP database location. Defaults to ~/hallucite/dblp.db in the user's home (kept out of
# the repo: it is ~2.5 GB). Override with $HALLUCITE_DBLP to relocate it without editing this
# script, the mise tasks, or the skill.
DEFAULT_DBLP = os.environ.get("HALLUCITE_DBLP") or str(Path.home() / "hallucite" / "dblp.db")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a concurrent reader (e.g. Stage 3 running
    while this audit is still going) never sees a partially written file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

# Online backends to switch off in --offline mode (keeps offline DBLP). These MUST be the exact
# `db` names `verifier` emits in each db_results entry -- a name that matches no backend is
# silently ignored, so a typo leaves that backend live in --offline mode (this is what let the
# old "DOI Resolver" entry never disable the real "DOI" backend). The names below are validated
# at run time against the db names actually seen (see main()); use --disable-dbs to add more.
DEFAULT_ONLINE_DBS = ["CrossRef", "DOI", "arXiv", "Semantic Scholar"]

# The only backend that makes no network call, so the only one expected to appear in an --offline
# run's db_results. Any other name there means an online backend survived the disable list -- the
# inverse drift direction of the DEFAULT_ONLINE_DBS tripwire in main().
KNOWN_LOCAL_DBS = ["DBLP"]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def find_pdfs(target: Path) -> list[Path]:
    if target.is_dir():
        # Case-insensitive (.pdf and .PDF); error on an empty directory rather than silently
        # running on zero papers.
        pdfs = sorted(p for p in target.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
        if not pdfs:
            sys.exit(f"error: no PDF files in {target} (looked for *.pdf, case-insensitive)")
        return pdfs
    if target.is_file() and target.suffix.lower() == ".pdf":
        return [target]
    sys.exit(f"error: no PDF(s) found at {target}")


def _doi_info(info) -> dict | None:
    return None if info is None else {"doi": info.doi, "valid": info.valid, "title": info.title}


def _arxiv_info(info) -> dict | None:
    return None if info is None else {"arxiv_id": info.arxiv_id, "valid": info.valid, "title": info.title}


def _retraction_info(info) -> dict | None:
    if info is None or not info.is_retracted:
        return None
    return {"is_retracted": True, "retraction_doi": info.retraction_doi,
            "retraction_source": info.retraction_source}


def _db_results(results) -> list[dict]:
    return [{"db": r.db_name, "status": r.status, "elapsed_ms": r.elapsed_ms,
             "found_authors": list(r.found_authors), "paper_url": r.paper_url}
            for r in results]


def verification_dict(result) -> dict:
    failed = list(result.failed_dbs)
    return {
        "status": result.status,
        # A "not_found" from a run where backends errored or rate-limited is not the same claim as
        # a "not_found" from a complete run: the reference may simply never have been asked about.
        # Kept as a separate flag rather than a new status value, so `status != "verified"` stays
        # the single definition of "needs triage" and no consumer has to learn a new string.
        "degraded": bool(failed) and result.status != "verified",
        "source": result.source,
        "found_authors": list(result.found_authors),
        "paper_url": result.paper_url,
        "doi_info": _doi_info(result.doi_info),
        "arxiv_info": _arxiv_info(result.arxiv_info),
        "retraction_info": _retraction_info(result.retraction_info),
        "failed_dbs": failed,
        "db_results": _db_results(result.db_results),
    }


def parsed_dict(reference) -> dict | None:
    if reference is None:
        return None
    return {"title": reference.title, "authors": list(reference.authors),
            "doi": reference.doi, "arxiv_id": reference.arxiv_id}


def dblp_build_info(dblp_path: Path) -> dict:
    """Best-effort metadata about the offline DBLP DB: file mtime, and the
    build_date from its metadata table if the ingest recorded one."""
    info: dict = {"path": str(dblp_path), "exists": dblp_path.exists()}
    if not dblp_path.exists():
        return info
    info["file_mtime"] = dt.datetime.fromtimestamp(
        dblp_path.stat().st_mtime, dt.timezone.utc).replace(microsecond=0).isoformat()
    try:
        con = sqlite3.connect(f"file:{dblp_path}?mode=ro", uri=True)
        try:
            meta = dict(con.execute("SELECT key, value FROM metadata").fetchall())
        finally:
            con.close()
    except sqlite3.Error:
        return info
    # The ingest stores the dump's HTTP Last-Modified date and a build epoch.
    if meta.get("last_modified"):
        info["dump_last_modified"] = meta["last_modified"]
    if str(meta.get("last_updated", "")).isdigit():
        info["built_at"] = dt.datetime.fromtimestamp(
            int(meta["last_updated"]), dt.timezone.utc).replace(microsecond=0).isoformat()
    if meta.get("publication_count"):
        info["publication_count"] = int(meta["publication_count"])
    return info


DBLP_STALE_DAYS = 30

# Below this an offline mirror is a failed build, not a bibliography: the real one holds
# millions of authors.
_DBLP_MIN_AUTHORS = 1000


def _dblp_drops_non_ascii_authors(dblp_path: Path) -> bool:
    """True when the offline DBLP database holds no author name with a non-ASCII character.

    DBLP itself is carefully curated and full of accented names, so a mirror containing none of
    them was built by an ingest that mangles them. On a 4.0M-author build every such author was
    simply absent -- Márcio Ribeiro, Martin Höst, Björn Regnell, Petr Tuma and Jácome Cunha were in
    no record, folded or otherwise -- which silently drops them from the author list of every
    publication they wrote. Any DBLP author comparison over that data is then unsound in one
    direction: it reports a mismatch for references that are cited correctly. Worth a loud warning
    because nothing else makes it visible -- the counts and the titles all look right."""
    try:
        con = sqlite3.connect(f"file:{dblp_path}?mode=ro", uri=True)
        try:
            # A database too small to be a real mirror says nothing about entity handling -- and an
            # empty one would otherwise report as "dropped every accented author", which sends the
            # reader after the wrong bug. _dblp_is_empty covers that case separately.
            n = con.execute("SELECT COUNT(*) FROM (SELECT 1 FROM authors LIMIT ?)",
                            (_DBLP_MIN_AUTHORS,)).fetchone()[0]
            if n < _DBLP_MIN_AUTHORS:
                return False
            # Indexless scan of a 4M-row table is slow, so cap it: a healthy build hits a non-ASCII
            # name almost immediately, and finding none in this many rows is already conclusive.
            row = con.execute(
                "SELECT 1 FROM (SELECT name FROM authors LIMIT 400000) "
                "WHERE name GLOB '*[^ -~]*' LIMIT 1").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return row is None


def _dblp_publication_count(dblp_path: Path) -> int | None:
    """Publications in the offline mirror, or None if it cannot be read.

    A download that brought back a bot-check HTML page instead of the dump still ingests, leaving a
    valid, empty, useless mirror in place of a good one.
    Nothing downstream distinguishes that from a paper whose references DBLP simply does not
    hold."""
    try:
        con = sqlite3.connect(f"file:{dblp_path}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _dblp_age_days(dblp_path: Path) -> float | None:
    """Days since the offline DBLP database was built (max of file mtime and the `last_updated`
    metadata epoch), or None if the file is absent."""
    if not dblp_path.exists():
        return None
    newest = dblp_path.stat().st_mtime
    try:
        con = sqlite3.connect(f"file:{dblp_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM metadata WHERE key = 'last_updated'").fetchone()
        finally:
            con.close()
        if row and str(row[0]).isdigit():
            newest = max(newest, int(row[0]))
    except sqlite3.Error:
        pass
    return (dt.datetime.now().timestamp() - newest) / 86400.0


def build_verifier(args) -> Verifier:
    disabled = list(DEFAULT_ONLINE_DBS) if args.offline else []
    dblp = Path(args.dblp)
    dblp_path: str | None = None
    if dblp.exists():
        dblp_path = str(dblp.resolve())
        age = _dblp_age_days(dblp)
        if age is not None and age > DBLP_STALE_DAYS:
            print(f"warning: offline DBLP database is {age:.0f} days old (> {DBLP_STALE_DAYS} days); "
                  f"recent papers may be missing. Rebuild with: mise run build-dblp", file=sys.stderr)
        n_pubs = _dblp_publication_count(dblp)
        if n_pubs is not None and n_pubs < _DBLP_MIN_AUTHORS:
            print(f"warning: the offline DBLP database at {dblp} holds only {n_pubs} publication(s), "
                  f"so it is a failed build, not a mirror -- a download that returns a bot-check "
                  f"page instead of the dump ingests as an empty database. "
                  f"Every DBLP lookup in this run will miss. Rebuild it to a scratch path first and "
                  f"keep the old file until the new one is verified.", file=sys.stderr)
        if _dblp_drops_non_ascii_authors(dblp):
            print(f"warning: the offline DBLP database at {dblp} holds no author name with a "
                  f"non-ASCII character, so its ingest dropped every author whose name carries a "
                  f"diacritic. DBLP is missing those authors from the papers they wrote, and its "
                  f"author checks will disagree with correctly cited references. The reference "
                  f"rule reads that off the mirror and stops holding an absence against a citation, "
                  f"but the confirmations those authors would have made are still lost -- rebuild "
                  f"with an ingest that handles the dump's character entities.", file=sys.stderr)
    else:
        # The mirror decides nine confirmations in ten, so a run without one is an incomplete run.
        # `Verifier` reports DBLP as a backend failure rather than a clean negative when the file is
        # missing, which is what keeps a whole corpus from looking cleanly not-found.
        print(f"warning: offline DBLP database not found at {args.dblp}; every reference in this "
              f"run will carry a DBLP failure. Build it with: mise run build-dblp",
              file=sys.stderr)
    # Semantic Scholar rate-limits an unauthenticated caller hard: over twelve audit runs it
    # answered on one, returning `rate_limited` in about 2.4s for three to five references each
    # time. Those references then carry a degraded verification -- not a clean negative -- and the
    # boundary between "verified" and "needs triage" moves by one reference from run to run, which
    # is the whole of the churn observed between otherwise identical audits. A free key removes it.
    s2_key = args.s2_api_key or os.environ.get("S2_API_KEY", "")
    if not s2_key and not args.offline:
        print("note: no Semantic Scholar API key (--s2-api-key or $S2_API_KEY). Unauthenticated "
              "callers are rate-limited, which leaves references degraded and makes the worklist "
              "vary between runs. Free key: https://www.semanticscholar.org/product/api",
              file=sys.stderr)
    if args.disable_dbs:
        disabled += [d.strip() for d in args.disable_dbs.split(",") if d.strip()]
    return Verifier(dblp_path=dblp_path, mailto=args.mailto, s2_api_key=s2_key,
                    rate_limit_retries=(2 if args.rate_limit_retries is None
                                        else args.rate_limit_retries),
                    disabled_dbs=tuple(disabled))


_YEAR_IN_CITATION = re.compile(r"\(((?:19|20)\d{2}[a-z]?)\)")
# Trailing initials on a Springer-style author ("de Dieu MJ" -> "de Dieu", "Bi T" -> "Bi").
_TRAILING_INITIALS = re.compile(r"\s+[A-ZÀ-ÖØ-Þ]{1,4}$")


def _surname(author: str) -> str:
    a = author.strip()
    if "," in a:                       # "Surname, I." (APA)
        return a.split(",", 1)[0].strip()
    return _TRAILING_INITIALS.sub("", a).strip() or a


def reference_label(ref_number: int, raw: str, parsed: dict | None, style: str) -> dict:
    """How to name this reference to someone reading the paper.

    A numeric bibliography prints "[12]" next to the entry, so the number is a real handle. An
    author-year bibliography prints no numbers at all -- there, the entry's handle is the citation
    key the body text uses ("de Dieu et al. (2025c)"), and the sequential index the extractor
    assigns is a tool-internal artifact that appears nowhere in the paper. Reporting that index as
    though it were a reference number sends the reader looking for something that does not exist,
    so it is only ever a fallback, and one that has to say what it is."""
    if style in ("numeric", "bracket-numeric"):
        return {"label": f"[{ref_number}]", "label_kind": "printed"}
    authors = [a for a in ((parsed or {}).get("authors") or []) if a]
    year = _YEAR_IN_CITATION.search(raw or "")
    if authors and year:
        names = [_surname(a) for a in authors]
        who = (names[0] if len(names) == 1
               else f"{names[0]} and {names[1]}" if len(names) == 2
               else f"{names[0]} et al.")
        return {"label": f"{who} ({year.group(1)})", "label_kind": "citation"}
    return {"label": f"#{ref_number}", "label_kind": "internal"}


CROSSREF_WORKS = "https://api.crossref.org/works"


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", (t or "").lower().replace("-", ""))).strip()


def crossref_candidates(title: str, authors: list, mailto: str = "",
                        rows: int = 5, timeout: float = 10.0, keep: int = 3) -> list[dict]:
    """Real publications whose metadata resembles this reference, from CrossRef's bibliographic
    search. Candidates only -- never a verdict.

    The exact-title lookups the validator does will miss a citation that abbreviates or expands a
    term ("LLMs" for "Large Language Models"), and a plain web search for such a title surfaces the
    authors' *other* papers, which reads exactly like the fabrication signature. A fuzzy
    bibliographic query finds the real record and hands triage something concrete to confirm or
    reject, instead of a blank page."""
    if not (title or "").strip():
        return []
    query = " ".join([title] + [str(a) for a in (authors or [])[:3]])
    params = {"query.bibliographic": query, "rows": str(rows),
              "select": "title,author,container-title,issued,DOI"}
    if mailto:
        params["mailto"] = mailto
    url = f"{CROSSREF_WORKS}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as fh:
            items = json.load(fh).get("message", {}).get("items", []) or []
    except Exception:
        return []                       # a best-effort hint must never fail an audit

    want = _norm_title(title)
    out = []
    for it in items:
        got = (it.get("title") or [""])[0]
        names = [" ".join(filter(None, (a.get("given"), a.get("family"))))
                 for a in (it.get("author") or [])]
        out.append({
            "title": got,
            "authors": names[:6],
            "venue": (it.get("container-title") or [""])[0],
            "year": ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0],
            "doi": it.get("DOI"),
            "title_similarity": round(SequenceMatcher(None, want, _norm_title(got)).ratio(), 3),
        })
    out.sort(key=lambda c: -c["title_similarity"])
    # Below ~0.6 a "candidate" is noise that would only invite a wrong match.
    return [c for c in out[:keep] if c["title_similarity"] >= 0.6]


def _retry_degraded(validator: Verifier, refs: list, verifications: list[dict | None],
                    rounds: int, delay: float) -> int:
    """Re-check references whose verification had a backend failure, and keep the better result.

    A backend only gets asked about the references an earlier one did not already match, so the
    hard residue -- exactly the references a human will be asked to judge -- is where rate limiting
    concentrates. Leaving those as a bare "not_found" overstates the evidence against them.
    Retried results replace the originals only when they improve (a match, or fewer failed
    backends), so a retry can never make a reference look worse than the first attempt."""
    fixed = 0
    for _ in range(rounds):
        pending = [i for i, v in enumerate(verifications)
                   if v is not None and v.get("degraded")]
        if not pending:
            break
        time.sleep(delay)
        try:
            results = validator.check([refs[i] for i in pending])
        except Exception as exc:                      # a failed retry must not lose the first pass
            print(f"    retry of {len(pending)} degraded reference(s) failed: {exc}",
                  file=sys.stderr)
            break
        for i, result in zip(pending, results):
            new = verification_dict(result)
            old = verifications[i]
            better = (new["status"] == "verified"
                      or len(new["failed_dbs"]) < len(old["failed_dbs"]))
            if better:
                verifications[i] = new
                fixed += 1
    return fixed




# Letters that carry no combining mark to strip, so NFKD leaves them alone: a stroke or bar
# through the glyph, a ligature, or a letter of its own. Without these, "Przybylek" and
# "Przybyłek" are different people -- the l-with-stroke survives folding, then falls to the
# non-ASCII filter and splits the surname into fragments that match nothing.









def _retry_dehyphenated(validator: Verifier, extractor,
                        entries: list, verifications: list[dict]) -> int:
    """Re-verify failed references using their dehyphenated variant, and keep a verifying result.

    The extractor keeps the hyphen when it joins a line-break ("Experimen-tation") because that is
    correct for a real compound broken at its own hyphen -- but for a soft-hyphenated word it is
    wrong, and an FTS backend then misses a title it actually holds, sending a real, indexed work
    into triage as `not_found`. Each entry carries the other variant (`alt_text`); trying it after
    a miss can only improve: a reference is switched only when the variant *verifies*."""
    pending = [i for i, (e, v) in enumerate(zip(entries, verifications))
               if v["status"] != "verified" and e.alt_text]
    alt_idx, alt_refs = [], []
    for i in pending:
        r = _parse(extractor, entries[i].alt_text, None)
        if r is not None:
            alt_idx.append(i)
            alt_refs.append(r)
    if not alt_refs:
        return 0
    try:
        results = validator.check(alt_refs)
    except Exception as exc:                          # a failed retry must not lose the first pass
        print(f"    dehyphenated retry of {len(alt_refs)} reference(s) failed: {exc}",
              file=sys.stderr)
        return 0
    fixed = 0
    for i, ref, result in zip(alt_idx, alt_refs, results):
        new = verification_dict(result)
        if new["status"] == "verified":
            verifications[i] = new
            entries[i].reference = ref                # the variant is the title that verified
            fixed += 1
    return fixed


def attach_mirror_evidence(dblp_path: str, entries: list, verifications: list[dict]) -> None:
    """What the offline mirror can tell whoever reviews the residue, attached to each unverified
    reference's verification. Not a check: nothing here changes a status.

    `dblp_record` is DBLP's own year, venue, volume/pages and DOI where exactly one record carries
    the cited title (`dblp_check.record_context`). `dblp_nearest` is the mirror's nearest title
    where no record carries it, offered only when every cited person is on that record
    (`dblp_check.nearest_title`). It is asked for only where the DBLP backend answered `no_match`
    -- the status string `verifier` emits for "asked, and found no record with this title" -- so
    a reference the mirror was never asked about (`skipped`) or found under its title with other
    authors (`author_mismatch`) gets no near miss it does not need."""
    for e, v in zip(entries, verifications):
        if v["status"] == "verified":
            continue
        ref = e.reference
        title = getattr(ref, "title", "") or ""
        found = record_context(dblp_path, title)
        if found:
            v["dblp_record"] = found
            continue
        if any(r.get("db") == DBLP and r.get("status") == NO_MATCH
               for r in v.get("db_results") or []):
            near = nearest_title(dblp_path, title, list(getattr(ref, "authors", None) or []))
            if near:
                v["dblp_nearest"] = near


def audit_pdf(pdf: Path, extractor, validator: Verifier | None,
              retry_rounds: int = 1, retry_delay: float = 5.0,
              candidates: bool = False, mailto: str = "",
              dblp_path: str | None = None) -> dict:
    info = extract_references(str(pdf.resolve()), extractor)

    parsed_entries = [e for e in info.refs if e.reference is not None]
    parsed_refs = [e.reference for e in parsed_entries]
    results = validator.check(parsed_refs) if (validator and parsed_refs) else []
    verifications = [verification_dict(r) for r in results]
    if validator is not None and verifications:
        n = _retry_dehyphenated(validator, extractor, parsed_entries, verifications)
        if n:
            print(f"    recovered {n} reference(s) by removing line-break hyphens")
        parsed_refs = [e.reference for e in parsed_entries]
    if validator is not None and retry_rounds > 0 and verifications:
        n = _retry_degraded(validator, parsed_refs, verifications, retry_rounds, retry_delay)
        if n:
            print(f"    recovered {n} degraded verification(s) on retry")
    # Evidence for whoever reviews the residue: DBLP's own year, venue, volume/pages and DOI beside
    # the citation, or its nearest title where it holds no record of the cited one. Not a check --
    # comparing these fields automatically was measured against the corpus and is far too noisy to
    # demote on (see dblp_check.record_context). This runs after every pass, so it covers the final
    # residue; attaching it earlier skipped exactly the references the last pass demotes, which
    # are the ones a reviewer most needs the evidence for.
    if dblp_path and verifications:
        attach_mirror_evidence(dblp_path, parsed_entries, verifications)
    result_iter = iter(verifications)

    references = []
    for e in info.refs:
        parsed = parsed_dict(e.reference)
        rec = {
            "original_number": e.number,
            "raw_citation": e.raw_text,
            "parsed": parsed,
            **reference_label(e.number, e.raw_text, parsed, info.style),
        }
        if e.reference is None:
            rec["db_verification"] = {
                "status": "unparsed",
                "note": "could not be parsed into fields; triage from raw_citation",
            }
        elif validator is not None:
            rec["db_verification"] = next(result_iter)
        else:
            rec["db_verification"] = None  # --no-verify
        # For a reference no database confirmed, offer the closest real records CrossRef knows
        # of. These are leads for triage to confirm or reject, never a verdict.
        dv = rec.get("db_verification") or {}
        if candidates and dv.get("status") not in (None, "verified") and parsed:
            found = crossref_candidates(parsed.get("title") or "",
                                        parsed.get("authors") or [], mailto)
            if found:
                rec["candidates"] = found
        references.append(rec)

    return {
        "schema_version": SCHEMA_VERSION,
        "paper_id": pdf.stem,
        "pdf_path": os.path.relpath(pdf, Path.cwd()),
        "audited_at": now_iso(),
        "num_references": len(info.refs),
        "extraction": {
            "style": info.style,
            "lineno_on": info.lineno_on,
            "section_found": info.section_found,
            "parsed": len(parsed_refs),
            "unparsed": len(info.refs) - len(parsed_refs),
            "suspect_merged": info.suspect_merged,
            "missing_numbers": info.missing_numbers,
        },
        "references": references,
    }


def paper_status_counts(record: dict) -> dict:
    counts = {"verified": 0, "not_found": 0, "mismatch": 0, "unparsed": 0,
              "retracted": 0, "pending": 0}
    checked = 0
    for ref in record["references"]:
        dv = ref["db_verification"]
        if dv is None:
            counts["pending"] += 1
            continue
        checked += 1
        counts[dv["status"]] = counts.get(dv["status"], 0) + 1
        if dv.get("retraction_info"):
            counts["retracted"] += 1
    # Everything the validator checked but did not confirm ("verified") needs triage. Derive this
    # by negation rather than summing a hard-coded list of failure statuses, so an unrecognised
    # status -- e.g. "mismatch", which an earlier list silently dropped from both
    # the count and the worklist -- is always surfaced.
    counts["unverified"] = checked - counts["verified"]
    counts["degraded"] = sum(1 for ref in record["references"]
                             if (ref["db_verification"] or {}).get("degraded"))
    return counts


def backend_failures(record: dict) -> dict:
    """How often each backend failed to answer, across a paper's references."""
    failures: dict = {}
    for ref in record["references"]:
        for db in (ref["db_verification"] or {}).get("failed_dbs") or []:
            failures[db] = failures.get(db, 0) + 1
    return failures


def main() -> int:
    p = argparse.ArgumentParser(description="Extract + verify paper references (no LLM).")
    p.add_argument("target", help="A PDF file or a directory of PDF files (e.g. ..)")
    p.add_argument("--dblp", default=DEFAULT_DBLP,
                   help="Offline DBLP SQLite DB ($HALLUCITE_DBLP, else ~/hallucite/dblp.db)")
    p.add_argument("--out", default="out", help="Output directory")
    p.add_argument("--mailto", default="", help="CrossRef polite-pool contact (recommended)")
    p.add_argument("--s2-api-key", default="",
                   help="Semantic Scholar API key ($S2_API_KEY). Without one S2 rate-limits and "
                        "its references stay degraded")
    p.add_argument("--rate-limit-retries", type=int, default=None,
                   help="How often a rate-limited backend is retried")
    p.add_argument("--offline", action="store_true",
                   help="no network (disable online DBs; offline DBLP + the local Standards "
                        "matcher stay live)")
    p.add_argument("--disable-dbs", default="", help="Comma-separated DB names to disable")
    p.add_argument("--no-verify", action="store_true", help="Extract only; skip DB verification")
    p.add_argument("--no-candidates", action="store_true",
                   help="Skip the CrossRef bibliographic lookup that attaches candidate real "
                        "records to unverified references (implied by --offline)")
    p.add_argument("--retry-degraded", type=int, default=1, metavar="N",
                   help="Re-check references whose verification had a backend failure, N times "
                        "(default 1; 0 disables). Rate limiting concentrates on exactly the "
                        "references that reach triage.")
    p.add_argument("--retry-delay", type=float, default=5.0, metavar="SECONDS",
                   help="Pause before each degraded-reference retry (default 5)")
    args = p.parse_args()

    pdfs = find_pdfs(Path(args.target))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dblp_file = Path(args.dblp)

    extractor = reference_parser
    validator = None if args.no_verify else build_verifier(args)

    summary_papers = []
    seen_dbs: set[str] = set()
    all_failures: dict = {}
    for i, pdf in enumerate(pdfs, start=1):
        print(f"[{i}/{len(pdfs)}] {pdf.name} ...", flush=True)
        try:
            record = audit_pdf(pdf, extractor, validator,
                               retry_rounds=args.retry_degraded, retry_delay=args.retry_delay,
                               candidates=not (args.offline or args.no_candidates),
                               mailto=args.mailto,
                               dblp_path=str(dblp_file) if dblp_file.exists() else None)
        except Exception as exc:  # one bad PDF must not abort the batch
            print(f"    ERROR: {exc}", file=sys.stderr)
            traceback.print_exc()
            summary_papers.append({"paper_id": pdf.stem, "error": str(exc)})
            continue

        _atomic_write(out_dir / f"{pdf.stem}.json",
                      json.dumps(record, indent=2, ensure_ascii=False))
        counts = paper_status_counts(record)
        summary_papers.append({"paper_id": record["paper_id"],
                               "num_references": record["num_references"], **counts})
        for ref in record["references"]:
            for r in (ref.get("db_verification") or {}).get("db_results", []) or []:
                seen_dbs.add(r["db"])
        for db, n in backend_failures(record).items():
            all_failures[db] = all_failures.get(db, 0) + n
        ext = record["extraction"]
        if record["num_references"] == 0 or not ext["section_found"]:
            print(f"    warning: extracted {record['num_references']} reference(s)"
                  f"{'; no References section was found' if not ext['section_found'] else ''}"
                  f" -- this paper contributes nothing to triage; check the PDF/extraction.",
                  file=sys.stderr)
        if ext.get("missing_numbers"):
            labels = ", ".join(f"[{n}]" for n in ext["missing_numbers"])
            print(f"    warning: the bibliography prints entry {labels} but extraction produced "
                  f"no reference for it. A numbered bibliography numbers itself consecutively, so "
                  f"each of those is a reference that never reached verification and cannot be "
                  f"reported as unverified. Check the PDF around it.", file=sys.stderr)
        if ext.get("suspect_merged"):
            labels = ", ".join(f"#{n}" for n in ext["suspect_merged"])
            print(f"    warning: reference(s) {labels} carry two author-year blocks in one entry "
                  f"-- possibly two entries merged by a wrapped year line; if so, the second was "
                  f"never verified on its own. Check them in the PDF.", file=sys.stderr)
        if args.no_verify:
            print(f"    {record['num_references']} refs extracted "
                  f"({record['extraction']['unparsed']} unparsed)", flush=True)
        else:
            print(f"    {record['num_references']} refs | {counts['verified']} verified, "
                  f"{counts['unverified']} unverified"
                  f"{', ' + str(counts['degraded']) + ' degraded' if counts['degraded'] else ''}"
                  f"{', ' + str(counts['retracted']) + ' RETRACTED' if counts['retracted'] else ''}",
                  flush=True)

    totals: dict[str, int] = {}
    for pp in summary_papers:
        for k, v in pp.items():
            if isinstance(v, int):
                totals[k] = totals.get(k, 0) + v

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "verified": not args.no_verify,
        "dblp_db": dblp_build_info(Path(args.dblp)),
        "num_papers": len(pdfs),
        "totals": totals,
        "backend_failures": all_failures,
        "papers": summary_papers,
    }
    _atomic_write(out_dir / "summary.json",
                  json.dumps(summary, indent=2, ensure_ascii=False))

    if all_failures:
        # Say it out loud: a backend that answered nothing is invisible in the per-paper counts,
        # yet it silently weakens every "not_found" it should have had a say in.
        worst = ", ".join(f"{db} ({n})" for db, n in
                          sorted(all_failures.items(), key=lambda kv: -kv[1]))
        print(f"\nwarning: backends failed to answer on some references -- {worst}. "
              f"{totals.get('degraded', 0)} reference(s) carry a degraded verification: their "
              f"status is not a clean negative, and triage must not treat it as evidence of "
              f"fabrication.", file=sys.stderr)
    print(f"\nDone. Per-paper JSON + summary.json written to {out_dir}/")
    if not args.no_verify:
        print(f"Unverified references to triage: {totals.get('unverified', 0)} "
              f"across {len(pdfs)} papers.")
        # Drift tripwire: a configured online-backend name that never appeared as a real `db`
        # is almost certainly misspelled or renamed upstream -- the failure mode that let the
        # old "DOI Resolver" entry silently never disable the live "DOI" backend in --offline.
        if not args.offline and seen_dbs:
            stale = [db for db in DEFAULT_ONLINE_DBS if db not in seen_dbs]
            if stale:
                print(f"warning: configured online-backend name(s) {stale} never appeared in any "
                      f"db_results; `verifier` may have renamed or removed them, so --offline would "
                      f"not actually disable them. Update DEFAULT_ONLINE_DBS.", file=sys.stderr)
        # The inverse direction: a backend that ran in --offline mode but is not known-local is an
        # online backend the disable list missed (new or renamed upstream), i.e. --offline silently
        # stopped meaning "no network" for it.
        if args.offline and seen_dbs:
            unexpected = sorted(seen_dbs - set(KNOWN_LOCAL_DBS))
            if unexpected:
                print(f"warning: backend(s) {unexpected} ran despite --offline and are not in "
                      f"KNOWN_LOCAL_DBS; if they query the network, add them to "
                      f"DEFAULT_ONLINE_DBS so --offline disables them.", file=sys.stderr)
    zero = [p for p in summary_papers if "error" not in p and p.get("num_references") == 0]
    if zero:
        # Aggregate the per-paper warnings, so one unsupported layout in a long batch cannot
        # scroll out of sight: a paper with zero extracted references was never checked at all.
        ids = ", ".join(p["paper_id"] for p in zero)
        print(f"\nwarning: {len(zero)} of {len(pdfs)} paper(s) yielded 0 references (unsupported "
              f"bibliography layout, or no References section) and were NOT checked: {ids}. "
              f"This is an extraction failure, not a finding: report it as such and fix the "
              f"extraction. Reading the bibliography by eye is not a substitute -- it yields no "
              f"verdict.", file=sys.stderr)
    errored = [p for p in summary_papers if "error" in p]
    if errored:
        ids = ", ".join(p["paper_id"] for p in errored)
        print(f"\nERROR: {len(errored)} of {len(pdfs)} paper(s) failed and produced NO output, so "
              f"they are silently absent from Stage 3 triage: {ids}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
