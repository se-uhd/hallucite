"""Record what the current implementation does, so a replacement can be held to it.

hallucite reaches into `hallucinator` at exactly two points -- `parse_reference` (one citation
string to fields) and `Validator.check` (fields to a per-backend verdict). Replacing that dependency
needs an oracle, and the honest way to build one is to observe the current implementation from the
outside rather than to read its source: what goes in, what comes out, on real references. The
recording is a specification by example, and it is also the differential test -- a replacement is
correct when it reproduces these outputs, and every disagreement is either a bug in the replacement
or a behaviour worth deciding about deliberately.

Deriving the spec black-box also keeps the licences apart. hallucinator is AGPL-3.0-or-later and
hallucite is MIT; observing behaviour through the public API and writing an independent
implementation is the boundary that keeps the two separate, and copying code across is what would
not.

    characterize.py record <pdf-or-dir> --out cases.json      # capture current behaviour
    characterize.py compare cases.json --impl <module>        # hold a replacement to it

`--impl` names an importable module exposing `parse_reference(text, prev_authors)` and
`check(refs)` with the same shapes; `compare` reports every field that differs.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

try:
    from hallucinator import PdfExtractor, Validator, ValidatorConfig
except ImportError:
    sys.exit("error: the 'hallucinator' package is not installed (mise run install)")

from audit_references import DEFAULT_DBLP, verification_dict
from pdf_references import extract_references

SCHEMA = "characterization/1"

# Only the fields hallucite actually consumes. Recording more would pin behaviour nobody depends
# on and make a replacement look wrong for differences that do not matter.
PARSE_FIELDS = ("title", "authors", "doi", "arxiv_id")
CHECK_FIELDS = ("status", "source", "found_authors", "paper_url", "failed_dbs")


def _parsed(ref) -> dict | None:
    if ref is None:
        return None
    return {"title": ref.title, "authors": list(ref.authors),
            "doi": ref.doi, "arxiv_id": ref.arxiv_id}


def record(target: Path, out: Path, dblp: str, mailto: str, offline: bool) -> int:
    extractor = PdfExtractor()
    extractor.min_title_words = 1

    pdfs = sorted(target.glob("*.pdf")) if target.is_dir() else [target]
    cases: list[dict] = []
    for pdf in pdfs:
        info = extract_references(str(pdf.resolve()), extractor)
        entries = [e for e in info.refs if e.reference is not None]
        print(f"  {pdf.name}: {len(entries)} parsed references", flush=True)
        for e in entries:
            cases.append({"paper": pdf.name, "number": e.number,
                          "raw_citation": e.raw_text, "parse": _parsed(e.reference)})

    if not offline and cases:
        cfg = ValidatorConfig()
        cfg.dblp_offline_path = dblp
        if mailto:
            cfg.crossref_mailto = mailto
        validator = Validator(cfg)
        # One batch, so the recording reflects how the audit actually calls it.
        refs = []
        idx = []
        extractor2 = PdfExtractor()
        extractor2.min_title_words = 1
        for i, c in enumerate(cases):
            r = extractor2.parse_reference(c["raw_citation"], None)
            if r is not None:
                refs.append(r)
                idx.append(i)
        print(f"  verifying {len(refs)} references ...", flush=True)
        for i, result in zip(idx, validator.check(refs)):
            v = verification_dict(result)
            cases[i]["check"] = {k: v.get(k) for k in CHECK_FIELDS}
            cases[i]["check"]["db_results"] = [
                {"db": d.get("db"), "status": d.get("status")} for d in v.get("db_results") or []]

    out.write_text(json.dumps({"schema": SCHEMA, "cases": cases}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"recorded {len(cases)} cases -> {out}")
    return 0


def compare(cases_path: Path, impl_name: str) -> int:
    impl = importlib.import_module(impl_name)
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        sys.exit(f"error: {cases_path} is schema {data.get('schema')!r}, expected {SCHEMA!r}")

    cases = data["cases"]
    diffs: list[str] = []
    checked = 0
    for c in cases:
        want = c.get("parse")
        try:
            got = impl.parse_reference(c["raw_citation"], None)
        except Exception as exc:                       # a crash is a difference, not a stop
            diffs.append(f"{c['paper']} [{c['number']}] parse raised {exc!r}")
            continue
        checked += 1
        for f in PARSE_FIELDS:
            a = (want or {}).get(f)
            b = (got or {}).get(f) if isinstance(got, dict) else getattr(got, f, None)
            if a != b:
                diffs.append(f"{c['paper']} [{c['number']}] parse.{f}: {a!r} != {b!r}")

    print(f"compared {checked}/{len(cases)} cases; {len(diffs)} difference(s)")
    for d in diffs[:60]:
        print("  " + d)
    if len(diffs) > 60:
        print(f"  ... and {len(diffs) - 60} more")
    return 1 if diffs else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="capture the current implementation's behaviour")
    r.add_argument("target", type=Path, help="a PDF file or a directory of them")
    r.add_argument("--out", type=Path, default=Path("cases.json"))
    r.add_argument("--dblp", default=DEFAULT_DBLP)
    r.add_argument("--mailto", default="")
    r.add_argument("--offline", action="store_true", help="record parsing only, no verification")

    c = sub.add_parser("compare", help="hold a replacement to a recording")
    c.add_argument("cases", type=Path)
    c.add_argument("--impl", required=True, help="importable module with parse_reference/check")

    a = p.parse_args()
    if a.cmd == "record":
        return record(a.target, a.out, a.dblp, a.mailto, a.offline)
    return compare(a.cases, a.impl)


if __name__ == "__main__":
    raise SystemExit(main())
