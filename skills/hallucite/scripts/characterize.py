"""Record what hallucite does on real references, so a change can be held to it.

Two recordings, and they answer different questions.

`~/hallucite/cases.json` is the original anchor: what the external `hallucinator` package returned
for 2065 references, captured through its public API rather than by reading its source. That is
the specification `reference_parser` and `verifier` were written against, and the boundary that
keeps an AGPL package and an MIT repo apart. It is frozen, and `compare` still replays it.

The second is made by the modules that now ship, of their own behaviour. Once the thing being
characterised is the thing that runs, the recording stops being a specification and becomes a
regression test: a difference is a change *this repo* made, and the question is whether it was
meant.

    characterize.py record <pdf-or-dir> --out cases.json [--offline]
    characterize.py compare cases.json --impl <module>

`--impl` names an importable module exposing `parse_reference(text, prev_authors)` and
`check(refs)`. `compare` reports every parse field that differs, and for the verdicts a movement
report: the recorded status against the implementation's, and every reference that crosses the
verified line in either direction. Field-by-field equality is not the question there -- a
different set of backends makes `source`, `failed_dbs` and `db_results` differ by construction --
and where a reference lands is what the audit and every report are built on.

Record with `--offline` unless the online verdicts are what is being characterised. An offline
recording takes half a minute instead of an hour, covers the 91.5% of confirmations the mirror
decides, and is reproducible -- where one made across the network bakes in whoever's rate limit
was in force that afternoon, which is not a property of this code at all.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import reference_parser
from audit_references import DEFAULT_DBLP, verification_dict
from pdf_references import extract_references
from verifier import Verifier

# A recording made by the external package the modules were written against. Kept readable
# forever: it is the specification they were held to, and replaying it is how a change is shown
# not to have moved away from it.
SCHEMA_V1 = "characterization/1"
# A recording made by hallucite's own modules, of hallucite's own behaviour. What a regression is
# measured against once the thing being characterised is the thing that ships.
SCHEMA = "characterization/2"
READABLE = (SCHEMA_V1, SCHEMA)

# Only the fields hallucite actually consumes. Recording more would pin behaviour nobody depends
# on and make a replacement look wrong for differences that do not matter.
PARSE_FIELDS = ("title", "authors", "doi", "arxiv_id")
CHECK_FIELDS = ("status", "source", "found_authors", "paper_url", "failed_dbs")


def _parsed(ref) -> dict | None:
    if ref is None:
        return None
    return {"title": ref.title, "authors": list(ref.authors),
            "doi": ref.doi, "arxiv_id": ref.arxiv_id}


def record(target: Path, out: Path, dblp: str, mailto: str, offline: bool, check: bool,
           s2_key: str) -> int:
    extractor = reference_parser

    pdfs = sorted(target.glob("*.pdf")) if target.is_dir() else [target]
    cases: list[dict] = []
    for pdf in pdfs:
        info = extract_references(str(pdf.resolve()), extractor)
        entries = [e for e in info.refs if e.reference is not None]
        print(f"  {pdf.name}: {len(entries)} parsed references", flush=True)
        for e in entries:
            cases.append({"paper": pdf.name, "number": e.number,
                          "raw_citation": e.raw_text, "parse": _parsed(e.reference)})

    if check and cases:
        disabled = ("CrossRef", "DOI", "arXiv", "Semantic Scholar") if offline else ()
        # Without a key Semantic Scholar rate-limits the residue hard, and the residue is most of
        # the wall clock: a 41-paper recording runs for hours and the references it is slowest
        # about are exactly the ones a replacement most needs a verdict for. An offline recording
        # has neither problem, and being reproducible is most of what an anchor is for.
        if not offline and not s2_key:
            print("note: no Semantic Scholar API key (--s2-api-key or $S2_API_KEY). "
                  "Unauthenticated callers are rate-limited, and this recording will take hours "
                  "longer than it needs to.", file=sys.stderr)
        verifier = Verifier(dblp_path=dblp, mailto=mailto, s2_api_key=s2_key,
                            disabled_dbs=disabled)
        # One batch, so the recording reflects how the audit actually calls it, and re-parsed from
        # the raw text so the recorded parse is the input the recorded verdict was reached from.
        refs, idx = [], []
        for i, c in enumerate(cases):
            r = reference_parser.parse_reference(c["raw_citation"], None)
            if r is not None:
                refs.append(r)
                idx.append(i)
                c["parse"] = _parsed(r)
        print(f"  verifying {len(refs)} references "
              f"({'offline' if offline else 'all backends'}) ...", flush=True)
        for i, result in zip(idx, verifier.check(refs)):
            v = verification_dict(result)
            cases[i]["check"] = {k: v.get(k) for k in CHECK_FIELDS}
            cases[i]["check"]["db_results"] = [
                {"db": d.get("db"), "status": d.get("status")} for d in v.get("db_results") or []]

    out.write_text(json.dumps({
        "schema": SCHEMA,
        # What made this recording, so two of them can never be mistaken for each other: the
        # hallucinator anchor says what the modules were written against, and this one says what
        # they currently do.
        "recorded_by": "hallucite (reference_parser + verifier)",
        "mode": "parse-only" if not check else ("offline" if offline else "all backends"),
        "cases": cases}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"recorded {len(cases)} cases -> {out}")
    return 0


class _Ref:
    """A parsed reference as the recording holds it, for feeding a candidate `check`.

    Deliberately not the implementation's own class: `check` is contracted to read `title`,
    `authors`, `doi` and `arxiv_id` off whatever it is given, and holding it to that keeps the two
    halves of the comparison independent -- a `check` divergence is then a `check` divergence, not
    a parse difference arriving one stage later."""

    def __init__(self, parsed: dict) -> None:
        self.title = parsed.get("title") or ""
        self.authors = list(parsed.get("authors") or [])
        self.doi = parsed.get("doi")
        self.arxiv_id = parsed.get("arxiv_id")


def _parse_diffs(cases: list[dict], impl) -> tuple[list[str], int]:
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
    return diffs, checked


# The backends an offline recording did not ask. Replaying one against a run that *does* ask them
# compares two different questions and reports the difference as a regression.
_ONLINE = ("CrossRef", "DOI", "arXiv", "Semantic Scholar")


def _check_report(cases: list[dict], impl, limit: int | None,
                  offline: bool) -> tuple[list[str], list[dict]]:
    """Compare the recorded verdicts with a candidate `check`, as a movement report.

    Field-by-field equality is the wrong question here. A replacement consults a different set of
    backends, so `source`, `failed_dbs` and `db_results` differ by construction and say nothing;
    what carries is where each reference *lands* -- `verified` or not -- because that is the line
    the audit, the worklist and every report are drawn on. So the per-reference status is compared
    as a matrix, and each reference that crosses the line is listed."""
    recorded = [c for c in cases if c.get("check")][:limit]
    if not recorded:
        return ["no recorded verifications in this file (recorded with --offline?)"], []
    refs = [_Ref(c["parse"] or {}) for c in recorded]
    if offline:
        try:
            results = impl.check(refs, disabled_dbs=_ONLINE)
        except TypeError:
            return (["error: this recording is offline and this implementation's `check` takes no "
                     "`disabled_dbs`; replaying it online would compare two different questions"],
                    [])
    else:
        results = impl.check(refs)
    matrix: dict[tuple[str, str], int] = {}
    sources: dict[str, int] = {}
    moved: list[dict] = []
    degraded = [0, 0]
    for c, got in zip(recorded, results):
        want = c["check"]
        a = want.get("status")
        b = got.get("status") if isinstance(got, dict) else getattr(got, "status", None)
        matrix[(a, b)] = matrix.get((a, b), 0) + 1
        source = got.get("source") if isinstance(got, dict) else getattr(got, "source", None)
        sources[source or "-"] = sources.get(source or "-", 0) + 1
        for side, failed in ((0, want.get("failed_dbs")), (1, _attr(got, "failed_dbs"))):
            if failed and (a if side == 0 else b) != "verified":
                degraded[side] += 1
        if (a == "verified") != (b == "verified"):
            moved.append({"paper": c["paper"], "number": c["number"],
                          "raw_citation": c["raw_citation"], "parse": c["parse"],
                          "recorded": want, "impl": {
                              "status": b, "source": source,
                              "found_authors": _attr(got, "found_authors"),
                              "paper_url": _attr(got, "paper_url"),
                              "failed_dbs": _attr(got, "failed_dbs"),
                              "db_results": [{"db": _attr(d, "db_name") or _attr(d, "db"),
                                              "status": _attr(d, "status")}
                                             for d in _attr(got, "db_results") or []]}})
    lines = [f"check: {len(recorded)} recorded verification(s)"]
    lines.append("  recorded -> implementation")
    for (a, b), n in sorted(matrix.items(), key=lambda kv: -kv[1]):
        mark = "  " if (a == "verified") == (b == "verified") else " *"
        lines.append(f"   {mark} {a or '-':<14} -> {b or '-':<14} {n:5d}")
    lines.append("  implementation's deciding backend: " + ", ".join(
        f"{k} {v}" for k, v in sorted(sources.items(), key=lambda kv: -kv[1])))
    lines.append(f"  unverified references carrying a backend failure: "
                 f"recorded {degraded[0]}, implementation {degraded[1]}")
    return lines, moved


def _attr(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def compare(cases_path: Path, impl_name: str, out: Path | None, samples: int,
            check: bool, limit: int | None) -> int:
    impl = importlib.import_module(impl_name)
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    if data.get("schema") not in READABLE:
        sys.exit(f"error: {cases_path} is schema {data.get('schema')!r}, expected one of "
                 f"{', '.join(map(repr, READABLE))}")
    made_by = data.get("recorded_by", "hallucinator (the package these modules replaced)")
    mode = data.get("mode", "all backends")
    print(f"replaying {cases_path.name}: recorded by {made_by}, {mode}\n")
    if mode == "offline":
        print("  (replaying offline, to match how it was recorded)\n")

    cases = data["cases"]
    diffs, checked = _parse_diffs(cases, impl)
    print(f"parse: compared {checked}/{len(cases)} cases; {len(diffs)} difference(s)")
    for d in diffs[:samples]:
        print("  " + d)
    if len(diffs) > samples:
        print(f"  ... and {len(diffs) - samples} more")

    moved: list[dict] = []
    if check and hasattr(impl, "check"):
        print()
        lines, moved = _check_report(cases, impl, limit, mode == "offline")
        for line in lines:
            print(line)
    if out is not None:
        out.write_text(json.dumps({"parse_differences": diffs, "status_moves": moved},
                                  indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nfull divergence list -> {out}")
    return 1 if diffs or moved else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="capture the current implementation's behaviour")
    r.add_argument("target", type=Path, help="a PDF file or a directory of them")
    r.add_argument("--out", type=Path, default=Path("cases.json"))
    r.add_argument("--dblp", default=DEFAULT_DBLP)
    r.add_argument("--mailto", default="")
    r.add_argument("--s2-api-key", default="",
                   help="Semantic Scholar API key ($S2_API_KEY). Without one the recording is "
                        "rate-limited into taking hours")
    r.add_argument("--offline", action="store_true",
                   help="verify against the offline mirror only -- reproducible, and the 91.5% of "
                        "confirmations it decides do not depend on anyone's rate limit")
    r.add_argument("--no-check", action="store_true", help="record the parse only")

    c = sub.add_parser("compare", help="hold a replacement to a recording")
    c.add_argument("cases", type=Path)
    c.add_argument("--impl", required=True, help="importable module with parse_reference/check")
    c.add_argument("--out", type=Path, default=None,
                   help="write every difference, and every reference whose status moved, as JSON")
    c.add_argument("--samples", type=int, default=60,
                   help="how many parse differences to print (default 60)")
    c.add_argument("--limit", type=int, default=None, metavar="N",
                   help="compare only the first N recorded verifications. `check` queries the "
                        "network, so a whole recording is a long, rate-limited run")
    c.add_argument("--no-check", action="store_true",
                   help="compare the parse only, and make no network request")

    a = p.parse_args()
    if a.cmd == "record":
        return record(a.target, a.out, a.dblp, a.mailto, a.offline, not a.no_check,
                      a.s2_api_key or os.environ.get("S2_API_KEY", ""))
    return compare(a.cases, a.impl, a.out, a.samples, not a.no_check, a.limit)


if __name__ == "__main__":
    raise SystemExit(main())
