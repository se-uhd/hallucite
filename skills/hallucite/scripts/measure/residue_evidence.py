"""What the audit knows about the residue and did not show, measured over an offline audit's output.

Three things a `not_found` used to hide: which backends were never asked, the mirror's nearest title
where no record carries the cited one, and what a cited identifier resolves to. Each subcommand
prints every hit, because the count is not the finding -- the reading is.

    residue_evidence.py skipped OUTDIR               # backends at `skipped`, per residue reference
    residue_evidence.py nearest OUTDIR               # the mirror's nearest title, ungated and gated
    residue_evidence.py resolve OUTDIR --out FILE    # network: DOI and arXiv for the residue only
    residue_evidence.py resolved FILE                # what those identifiers resolved to

`OUTDIR` is what `audit_references.py --offline` wrote. `resolve` asks only the DOI and arXiv
backends, only about residue references that carry an identifier, and removes the Semantic Scholar
key from its own environment: a few hundred requests, not a corpus replay.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SCRIPTS = HERE.parent
DEFAULT_DBLP = os.environ.get("HALLUCITE_DBLP", os.path.expanduser("~/hallucite/dblp.db"))


def _residue(out_dir: str) -> list[tuple[str, dict]]:
    rows = []
    for f in sorted(glob.glob(os.path.join(out_dir, "*.json"))):
        rec = json.load(open(f, encoding="utf-8"))
        if not isinstance(rec, dict) or not isinstance(rec.get("references"), list):
            continue
        for ref in rec["references"]:
            dv = ref.get("db_verification") or {}
            if dv and dv.get("status") != "verified":
                rows.append((rec["paper_id"], ref))
    return rows


def _dblp_status(ref: dict) -> str | None:
    for r in (ref.get("db_verification") or {}).get("db_results") or []:
        if r.get("db") == "DBLP":
            return r.get("status")
    return None


def skipped(a) -> int:
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    import triage
    rows = _residue(a.out_dir)
    by_db: dict[str, int] = {}
    for pid, ref in rows:
        names = triage.skipped_dbs(ref)
        for name in names:
            by_db[name] = by_db.get(name, 0) + 1
        if "DBLP" in names:
            p = ref.get("parsed") or {}
            print(f"{pid} [{ref['original_number']}] {p.get('title')!r} "
                  f"authors={p.get('authors') or []}")
    print(f"\n{len(rows)} residue references; skipped per backend: {by_db}")
    return 0


def nearest(a) -> int:
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    import dblp_check as D
    rows = [(pid, ref) for pid, ref in _residue(a.out_dir) if _dblp_status(ref) == "no_match"]
    started = time.time()
    ungated = gated = 0
    for pid, ref in rows:
        p = ref.get("parsed") or {}
        title, authors = p.get("title") or "", p.get("authors") or []
        candidates = D._nearest_candidates(a.dblp, title)
        if not candidates:
            continue
        offered = D.nearest_title(a.dblp, title, authors)
        ungated += 1
        gated += offered is not None
        tag = "GATED  " if offered is not None else "ungated"
        best = offered or candidates[0]
        print(f"{tag} {pid} [{ref['original_number']}] edits={best['edits']}")
        print(f"    cited:  {title!r}  {authors}")
        print(f"    record: {best['title']!r}  {best['authors']}  {best['key']} "
              f"{best.get('year')} {best.get('venue')}")
        if len(candidates) > 1:
            print(f"    ({len(candidates)} candidates within {D._NEAREST_EDITS} edits)")
    print(f"\n{len(rows)} residue references the mirror answered no_match for; "
          f"a title within {D._NEAREST_EDITS} word edits: {ungated} ungated, {gated} gated on "
          f"every cited person being on it   ({time.time() - started:.0f}s)")
    return 0


class _Ref:
    def __init__(self, parsed: dict) -> None:
        self.title = parsed.get("title") or ""
        self.authors = list(parsed.get("authors") or [])
        self.doi = parsed.get("doi")
        self.arxiv_id = parsed.get("arxiv_id")


def resolve(a) -> int:
    os.environ.pop("S2_API_KEY", None)
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    from audit_references import verification_dict
    from verifier import Verifier
    rows = [(pid, ref) for pid, ref in _residue(a.out_dir)
            if (ref.get("parsed") or {}).get("doi") or (ref.get("parsed") or {}).get("arxiv_id")]
    print(f"{len(rows)} residue references carry a DOI or an arXiv id", file=sys.stderr)
    verifier = Verifier(dblp_path=None, mailto=a.mailto, s2_api_key="",
                        disabled_dbs=("DBLP", "CrossRef", "Semantic Scholar"))
    started = time.time()
    results = verifier.check([_Ref(ref["parsed"]) for _, ref in rows])
    out = []
    for (pid, ref), result in zip(rows, results):
        d = verification_dict(result)
        out.append({"paper": pid, "number": ref["original_number"], "parsed": ref["parsed"],
                    "raw": ref["raw_citation"], "offline_status": ref["db_verification"]["status"],
                    "doi_info": d["doi_info"], "arxiv_info": d["arxiv_info"],
                    "failed_dbs": d["failed_dbs"], "db_results": d["db_results"]})
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {len(out)} -> {a.out}  ({time.time() - started:.0f}s)", file=sys.stderr)
    return 0


def resolved(a) -> int:
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    import triage
    rows = json.load(open(a.file, encoding="utf-8"))
    tally: dict[str, int] = {}
    for row in rows:
        ref = {"parsed": row["parsed"], "db_verification": {
            "doi_info": row["doi_info"], "arxiv_info": row["arxiv_info"]}}
        for e in triage.identifier_evidence(ref):
            outcome = ("dead" if not e["resolves"] else "no title" if e["title"] is None
                       else "cited title" if e["cited_title"] else "different title")
            tally[f"{e['kind']}: {outcome}"] = tally.get(f"{e['kind']}: {outcome}", 0) + 1
            print(f"{row['paper']} [{row['number']}] {e['kind']} {e['id']} -> {outcome}")
            print(f"    cited:    {row['parsed'].get('title')!r}")
            if e["title"]:
                print(f"    resolved: {e['title']!r}")
        if row["failed_dbs"]:
            tally["did not answer"] = tally.get("did not answer", 0) + 1
            print(f"{row['paper']} [{row['number']}] did not answer: {row['failed_dbs']}")
    print(f"\n{len(rows)} references; {tally}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scripts", default=str(DEFAULT_SCRIPTS),
                   help="import hallucite's modules from this directory (a snapshot)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("skipped", help="backends at `skipped` for each residue reference")
    s.add_argument("out_dir")
    s.set_defaults(func=skipped)
    n = sub.add_parser("nearest", help="the mirror's nearest title, ungated and gated")
    n.add_argument("out_dir")
    n.add_argument("--dblp", default=DEFAULT_DBLP)
    n.set_defaults(func=nearest)
    r = sub.add_parser("resolve", help="network: resolve the residue's DOIs and arXiv ids")
    r.add_argument("out_dir")
    r.add_argument("--out", required=True)
    r.add_argument("--mailto", default="")
    r.set_defaults(func=resolve)
    d = sub.add_parser("resolved", help="tabulate a `resolve` output")
    d.add_argument("file")
    d.set_defaults(func=resolved)
    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
