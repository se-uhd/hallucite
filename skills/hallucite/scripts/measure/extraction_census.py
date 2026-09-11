"""What every paper in a corpus extracts: style, references, unparsed, missing numbers, suspected
merges, and with `--verify` how many the offline mirror confirms.

A bibliography that extracts nothing, or one entry, is invisible downstream -- nothing can report
a reference that never arrived -- so this is the first thing to run after touching extraction, and
`--baseline` says which papers a change moved. Five papers of the 55-paper corpus once extracted 0,
0, 1, 1 and 1 references with no other symptom than this table.

    extraction_census.py ~/hallucite/corpus --out census.json
    extraction_census.py ~/hallucite/corpus --baseline census.json     # what moved since
    extraction_census.py ~/hallucite/corpus --verify                    # offline DBLP per paper
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DBLP = os.environ.get("HALLUCITE_DBLP", os.path.expanduser("~/hallucite/dblp.db"))
ONLINE = ("CrossRef", "DOI", "arXiv", "Semantic Scholar")
FIELDS = ("style", "refs", "unparsed", "missing", "merged")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("corpus", help="a directory of PDF files")
    p.add_argument("--out", default=None, help="write the per-paper rows as JSON")
    p.add_argument("--baseline", default=None, help="a previous --out to report changes against")
    p.add_argument("--verify", action="store_true",
                   help="also verify each paper against the offline mirror (no network)")
    p.add_argument("--dblp", default=DEFAULT_DBLP)
    p.add_argument("--scripts", default=str(HERE.parent),
                   help="import hallucite's modules from this directory (a snapshot)")
    a = p.parse_args()
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    import pdf_references
    import reference_parser
    verifier = None
    if a.verify:
        from verifier import Verifier
        verifier = Verifier(dblp_path=a.dblp, disabled_dbs=ONLINE)
        from audit_references import verification_dict

    rows: dict[str, dict] = {}
    for pdf in sorted(glob.glob(os.path.join(a.corpus, "*.pdf"))):
        info = pdf_references.extract_references(pdf, reference_parser)
        row = {"style": info.style, "refs": len(info.refs),
               "unparsed": sum(1 for r in info.refs if r.reference is None),
               "missing": len(info.missing_numbers), "merged": len(info.suspect_merged)}
        line = (f"{os.path.basename(pdf):28s} {row['style']:16s} refs={row['refs']:4d} "
                f"unparsed={row['unparsed']:3d} missing={row['missing']:3d} "
                f"merged={row['merged']}")
        if verifier is not None:
            refs = [r.reference for r in info.refs if r.reference is not None]
            counts = Counter(verification_dict(x)["status"] for x in verifier.check(refs))
            row["verified"] = counts.get("verified", 0)
            row["statuses"] = dict(counts)
            line += f" verified={row['verified']:4d} {dict(counts)}"
        rows[os.path.basename(pdf)] = row
        print(line, flush=True)
    total = sum(r["refs"] for r in rows.values())
    print(f"TOTAL {len(rows)} papers, {total} references, "
          f"{sum(r['unparsed'] for r in rows.values())} unparsed"
          + (f", {sum(r.get('verified', 0) for r in rows.values())} verified offline"
             if verifier is not None else ""))
    if a.baseline:
        before = json.load(open(a.baseline, encoding="utf-8"))
        moved = [(k, before[k], rows[k]) for k in rows if k in before
                 and any(before[k].get(f) != rows[k].get(f) for f in FIELDS)]
        print(f"\nchanged since {a.baseline}: {len(moved)} paper(s)")
        for k, b, r in moved:
            print(f"  {k}: " + "  ".join(f"{f} {b.get(f)}->{r.get(f)}" for f in FIELDS
                                         if b.get(f) != r.get(f)))
        for k in rows:
            if k not in before:
                print(f"  {k}: not in baseline")
    if a.out:
        json.dump(rows, open(a.out, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
