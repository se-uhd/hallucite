#!/usr/bin/env python3
"""Stages 1+2 of the hallucinated-reference audit: extract references from paper
PDF files and verify them against academic databases (offline DBLP + CrossRef/
arXiv/Semantic Scholar/...), with no LLM involvement.

Reference extraction is `lineno`-aware (see pdf_references.py); each extracted
reference is parsed and verified with the `hallucinator` package.

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
    --offline           No network: disable the online database backends.
                        Offline DBLP and hallucinator's built-in Standards
                        matcher stay live; a missing DBLP file disables DBLP
                        rather than falling back to dblp.org.
    --disable-dbs LIST  Comma-separated DB names to disable (passed to hallucinator)
    --no-verify         Extract only; skip database verification (fast, offline)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import traceback
from pathlib import Path

try:
    from hallucinator import PdfExtractor, Validator, ValidatorConfig
except ImportError:
    sys.exit(
        "error: the 'hallucinator' package is not installed.\n"
        "Run setup first:  mise run install   (see README.md / PLAN.md)"
    )

from pdf_references import extract_references

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
# `db` names hallucinator emits in each db_results entry -- a name that matches no backend is
# silently ignored, so a typo leaves that backend live in --offline mode (this is what let the
# old "DOI Resolver" entry never disable the real "DOI" backend). The names below are validated
# at run time against the db names actually seen (see main()); use --disable-dbs to add more.
DEFAULT_ONLINE_DBS = [
    "CrossRef", "arXiv", "Semantic Scholar", "ACL Anthology",
    "Europe PMC", "PubMed", "DOI", "Open Library",
]

# Backends expected to stay live in --offline mode because they make no network calls: the offline
# DBLP database (build_config() disables DBLP entirely when its file is missing, since hallucinator
# would otherwise fall back to dblp.org) and the built-in Standards pattern matcher. Any other name
# appearing in --offline db_results means an online backend survived the disable list (the inverse
# drift direction of the DEFAULT_ONLINE_DBS tripwire in main()), e.g. a backend hallucinator added
# or renamed upstream.
KNOWN_LOCAL_DBS = ["DBLP", "Standards"]


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
    return {
        "status": result.status,
        "source": result.source,
        "found_authors": list(result.found_authors),
        "paper_url": result.paper_url,
        "doi_info": _doi_info(result.doi_info),
        "arxiv_info": _arxiv_info(result.arxiv_info),
        "retraction_info": _retraction_info(result.retraction_info),
        "failed_dbs": list(result.failed_dbs),
        "db_results": _db_results(result.db_results),
    }


def parsed_dict(reference) -> dict | None:
    if reference is None:
        return None
    return {"title": reference.title, "authors": list(reference.authors),
            "doi": reference.doi, "arxiv_id": reference.arxiv_id}


def dblp_build_info(dblp_path: Path) -> dict:
    """Best-effort metadata about the offline DBLP DB: file mtime, and the
    build_date from its metadata table if hallucinator recorded one."""
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
    # hallucinator stores the dump's HTTP Last-Modified date and a build epoch.
    if meta.get("last_modified"):
        info["dump_last_modified"] = meta["last_modified"]
    if str(meta.get("last_updated", "")).isdigit():
        info["built_at"] = dt.datetime.fromtimestamp(
            int(meta["last_updated"]), dt.timezone.utc).replace(microsecond=0).isoformat()
    if meta.get("publication_count"):
        info["publication_count"] = int(meta["publication_count"])
    return info


DBLP_STALE_DAYS = 30


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


def build_config(args) -> ValidatorConfig:
    cfg = ValidatorConfig()
    disabled = list(DEFAULT_ONLINE_DBS) if args.offline else []
    dblp = Path(args.dblp)
    if dblp.exists():
        cfg.dblp_offline_path = str(dblp.resolve())
        age = _dblp_age_days(dblp)
        if age is not None and age > DBLP_STALE_DAYS:
            print(f"warning: offline DBLP database is {age:.0f} days old (> {DBLP_STALE_DAYS} days); "
                  f"recent papers may be missing. Rebuild with: mise run build-dblp", file=sys.stderr)
    elif args.offline:
        # Without an offline DB hallucinator's DBLP backend falls back to querying dblp.org, which
        # would break --offline's no-network promise; disable the backend outright instead.
        disabled.append("DBLP")
        print(f"warning: offline DBLP database not found at {args.dblp}; DBLP is disabled for "
              f"this --offline run (it would otherwise query dblp.org). Build it with: "
              f"mise run build-dblp", file=sys.stderr)
    else:
        print(f"warning: offline DBLP database not found at {args.dblp}; DBLP will be queried "
              f"online if available. Build it with: mise run build-dblp", file=sys.stderr)
    if args.mailto:
        cfg.crossref_mailto = args.mailto
    if args.disable_dbs:
        disabled += [d.strip() for d in args.disable_dbs.split(",") if d.strip()]
    if disabled:
        cfg.disabled_dbs = disabled
    return cfg


def audit_pdf(pdf: Path, extractor: PdfExtractor, validator: Validator | None) -> dict:
    info = extract_references(str(pdf.resolve()), extractor)

    parsed_refs = [e.reference for e in info.refs if e.reference is not None]
    results = validator.check(parsed_refs) if (validator and parsed_refs) else []
    result_iter = iter(results)

    references = []
    for e in info.refs:
        rec = {
            "original_number": e.number,
            "raw_citation": e.raw_text,
            "parsed": parsed_dict(e.reference),
        }
        if e.reference is None:
            rec["db_verification"] = {
                "status": "unparsed",
                "note": "could not be parsed into fields; triage from raw_citation",
            }
        elif validator is not None:
            rec["db_verification"] = verification_dict(next(result_iter))
        else:
            rec["db_verification"] = None  # --no-verify
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
    # status -- e.g. hallucinator's "mismatch", which an earlier list silently dropped from both
    # the count and the worklist -- is always surfaced.
    counts["unverified"] = checked - counts["verified"]
    return counts


def main() -> int:
    p = argparse.ArgumentParser(description="Extract + verify paper references (no LLM).")
    p.add_argument("target", help="A PDF file or a directory of PDF files (e.g. ..)")
    p.add_argument("--dblp", default=DEFAULT_DBLP,
                   help="Offline DBLP SQLite DB ($HALLUCITE_DBLP, else ~/hallucite/dblp.db)")
    p.add_argument("--out", default="out", help="Output directory")
    p.add_argument("--mailto", default="", help="CrossRef polite-pool contact (recommended)")
    p.add_argument("--offline", action="store_true",
                   help="no network (disable online DBs; offline DBLP + the local Standards "
                        "matcher stay live)")
    p.add_argument("--disable-dbs", default="", help="Comma-separated DB names to disable")
    p.add_argument("--no-verify", action="store_true", help="Extract only; skip DB verification")
    args = p.parse_args()

    pdfs = find_pdfs(Path(args.target))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    extractor = PdfExtractor()
    # We segment the bibliography ourselves, so every string handed to
    # parse_reference is already one real reference; accept short book titles too.
    extractor.min_title_words = 1
    validator = None if args.no_verify else Validator(build_config(args))

    summary_papers = []
    seen_dbs: set[str] = set()
    for i, pdf in enumerate(pdfs, start=1):
        print(f"[{i}/{len(pdfs)}] {pdf.name} ...", flush=True)
        try:
            record = audit_pdf(pdf, extractor, validator)
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
        ext = record["extraction"]
        if record["num_references"] == 0 or not ext["section_found"]:
            print(f"    warning: extracted {record['num_references']} reference(s)"
                  f"{'; no References section was found' if not ext['section_found'] else ''}"
                  f" -- this paper contributes nothing to triage; check the PDF/extraction.",
                  file=sys.stderr)
        if args.no_verify:
            print(f"    {record['num_references']} refs extracted "
                  f"({record['extraction']['unparsed']} unparsed)", flush=True)
        else:
            print(f"    {record['num_references']} refs | {counts['verified']} verified, "
                  f"{counts['unverified']} unverified"
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
        "papers": summary_papers,
    }
    _atomic_write(out_dir / "summary.json",
                  json.dumps(summary, indent=2, ensure_ascii=False))

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
                      f"db_results; hallucinator may have renamed/removed them, so --offline would "
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
    errored = [p for p in summary_papers if "error" in p]
    if errored:
        ids = ", ".join(p["paper_id"] for p in errored)
        print(f"\nERROR: {len(errored)} of {len(pdfs)} paper(s) failed and produced NO output, so "
              f"they are silently absent from Stage 3 triage: {ids}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
