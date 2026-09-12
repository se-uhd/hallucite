"""Hold hallucite's DBLP path to the verifier it replaced, DBLP only and offline.

Four combinations of parser and check are scored over the same citations, so a difference can be
attributed to one half: the recorded `hallucinator` parse against `reference_parser`, and
`hallucinator`'s DBLP backend against `verifier`. Everything else is disabled on both sides. The
old verifier accepts any string in `disabled_dbs` without complaint and disables nothing for a
name it does not know -- its names are the display names, "Semantic Scholar" and "Europe PMC" --
so this script also removes the Semantic Scholar key from its own environment and points every
proxy variable at a closed port before the old verifier is imported. A backend that is still
asked then fails in milliseconds and shows as `error` in its `db_results`; the summary lists the
backends the old verifier asked, and the list has to read `['DBLP']`.

    head_to_head.py run --source cases  out.json          # the 2065 recorded citations
    head_to_head.py run --source corpus out.json          # every reference the corpus extracts
    head_to_head.py moved out.json [lost|gained]          # the references that cross the line
    head_to_head.py diff before.json after.json           # what one change moved

`--scripts DIR` imports hallucite's modules from a snapshot instead of the working tree, which is
how a before-and-after is scored without stashing. `--refs CACHE` keeps the corpus extraction and
the old parse of it between runs, so each setting is scored on the identical references.
`pip install hallucinator` is needed for `run` and for nothing else in this repo.
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
DEFAULT_CASES = os.path.expanduser("~/hallucite/cases.json")
DEFAULT_CORPUS = os.path.expanduser("~/hallucite/corpus")
ONLINE = ("CrossRef", "DOI", "arXiv", "Semantic Scholar")
# The old verifier's backends by the names it knows them under. Anything not on this list that it
# still asks fails through the closed proxy and is reported.
OLD_DISABLED = ["Semantic Scholar", "Europe PMC", "ACL Anthology", "Open Library", "CrossRef",
                "DOI", "arXiv", "PubMed", "Standards", "OpenAlex", "IACR ePrint", "URL", "SearXNG"]
DEAD_PROXY = "http://127.0.0.1:9"
COMBOS = ("old_old", "new_new", "old_new", "new_old")


def _offline_environment() -> None:
    os.environ.pop("S2_API_KEY", None)
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ[var] = DEAD_PROXY


class _Ref:
    """What `check` is contracted to read off a reference."""

    def __init__(self, parsed: dict) -> None:
        self.title = parsed.get("title") or ""
        self.authors = list(parsed.get("authors") or [])
        self.doi = parsed.get("doi")
        self.arxiv_id = parsed.get("arxiv_id")


def _parsed(ref) -> dict | None:
    if ref is None:
        return None
    return {"title": ref.title, "authors": list(ref.authors), "doi": ref.doi,
            "arxiv_id": ref.arxiv_id}


def _new_check(parses: list, dblp: str) -> list:
    from audit_references import verification_dict
    from verifier import Verifier
    verifier = Verifier(dblp_path=dblp, disabled_dbs=ONLINE)
    idx = [i for i, p in enumerate(parses) if p]
    out: list = [None] * len(parses)
    started = time.time()
    for i, result in zip(idx, verifier.check([_Ref(parses[i]) for i in idx])):
        d = verification_dict(result)
        out[i] = {"status": d.get("status"), "source": d.get("source"),
                  "found_authors": d.get("found_authors"), "paper_url": d.get("paper_url"),
                  "dblp": next((x.get("status") for x in d.get("db_results") or []
                                if x.get("db") == "DBLP"), None)}
    print(f"  new check: {time.time() - started:.0f}s", file=sys.stderr, flush=True)
    return out


def _old_check(parses: list, dblp: str) -> list:
    from hallucinator import Reference, Validator, ValidatorConfig
    config = ValidatorConfig()
    config.dblp_offline_path = dblp
    config.disabled_dbs = OLD_DISABLED
    config.num_workers = 4
    validator = Validator(config)
    idx = [i for i, p in enumerate(parses) if p]
    out: list = [None] * len(parses)
    started = time.time()
    refs = [Reference(title=parses[i]["title"] or "", authors=list(parses[i]["authors"] or []),
                      doi=parses[i].get("doi"), arxiv_id=parses[i].get("arxiv_id")) for i in idx]
    for i, result in zip(idx, validator.check(refs)):
        dbs = {d.db_name: d.status for d in result.db_results}
        out[i] = {"status": result.status, "source": result.source,
                  "found_authors": list(result.found_authors or []),
                  "paper_url": result.paper_url, "dblp": dbs.get("DBLP"),
                  "asked": sorted(k for k, s in dbs.items() if s != "skipped")}
    print(f"  old check: {time.time() - started:.0f}s", file=sys.stderr, flush=True)
    return out


def _load_refs(source: str, cases: str, corpus: str, cache: str | None) -> list[dict]:
    if source == "cases":
        data = json.load(open(cases, encoding="utf-8"))["cases"]
        return [{"paper": c["paper"], "number": c["number"], "raw": c["raw_citation"],
                 "parse_old": c.get("parse")} for c in data]
    if cache and os.path.exists(cache):
        return json.load(open(cache, encoding="utf-8"))
    import pdf_references
    import reference_parser
    from hallucinator import NativePdfExtractor
    extractor = NativePdfExtractor()
    rows = []
    for pdf in sorted(glob.glob(os.path.join(corpus, "*.pdf"))):
        info = pdf_references.extract_references(pdf, reference_parser)
        for e in info.refs:
            rows.append({"paper": os.path.basename(pdf), "number": e.number, "raw": e.raw_text,
                         "style": info.style,
                         "parse_old": _parsed(extractor.parse_reference(e.raw_text, None))})
    if cache:
        json.dump(rows, open(cache, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return rows


def _verified(row: dict, combo: str) -> bool:
    return ((row.get(combo) or {}).get("status")) == "verified"


def run(a) -> int:
    _offline_environment()
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    import reference_parser
    print(f"scripts: {Path(reference_parser.__file__).parent}", file=sys.stderr)
    rows = _load_refs(a.source, a.cases, a.corpus, a.refs)
    old_p = [r["parse_old"] for r in rows]
    new_p = [_parsed(reference_parser.parse_reference(r["raw"], None)) for r in rows]
    for r, p in zip(rows, new_p):
        r["parse_new"] = p
    print(f"{len(rows)} refs; old parse {sum(1 for p in old_p if p)}, "
          f"new parse {sum(1 for p in new_p if p)}", file=sys.stderr, flush=True)
    combos = {"old_old": _old_check(old_p, a.dblp), "new_new": _new_check(new_p, a.dblp),
              "old_new": _new_check(old_p, a.dblp), "new_old": _old_check(new_p, a.dblp)}
    for i, r in enumerate(rows):
        for k, v in combos.items():
            r[k] = v[i]
    json.dump(rows, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("verified:", {k: sum(1 for r in rows if _verified(r, k)) for k in combos})
    print("old_old vs new_new: gained",
          sum(1 for r in rows if _verified(r, "new_new") and not _verified(r, "old_old")),
          "lost", sum(1 for r in rows if _verified(r, "old_old") and not _verified(r, "new_new")))
    asked: set[str] = set()
    for r in rows:
        asked.update((r.get("old_old") or {}).get("asked") or [])
    print("old verifier asked backends:", sorted(asked))
    return 0


def _print_row(r: dict, combo: str, tag: str) -> None:
    v = r.get(combo) or {}
    if v.get("found_authors"):
        print(f"   {tag} found: {v['found_authors'][:6]} {v.get('paper_url')}")


def moved(a) -> int:
    rows = json.load(open(a.out, encoding="utf-8"))
    if a.which == "lost":
        sel = [r for r in rows if _verified(r, "old_old") and not _verified(r, "new_new")]
    else:
        sel = [r for r in rows if _verified(r, "new_new") and not _verified(r, "old_old")]
    print(f"{a.which}: {len(sel)}")
    for i, r in enumerate(sel, 1):
        po, pn = r.get("parse_old") or {}, r.get("parse_new") or {}
        statuses = "  ".join(f"{k}={(r.get(k) or {}).get('status')}" for k in COMBOS)
        print(f"\n#{i} {r['paper']} [{r['number']}]  {statuses}")
        print(f"   RAW: {r['raw'][:230]}")
        print(f"   OLD: T={po.get('title')!r} A={po.get('authors')}")
        if po != pn:
            print(f"   NEW: T={pn.get('title')!r} A={pn.get('authors')}")
        _print_row(r, "old_old", "old")
        _print_row(r, "new_new", "new")
    return 0


def diff(a) -> int:
    before = {(r["paper"], r["number"]): r for r in json.load(open(a.before, encoding="utf-8"))}
    after = json.load(open(a.after, encoding="utf-8"))

    def state(r):
        v = r.get(a.combo) or {}
        return v.get("status"), v.get("dblp")

    pairs = [(before[k], r) for r in after
             if (k := (r["paper"], r["number"])) in before and state(before[k]) != state(r)]
    print(f"{a.combo}: before {sum(1 for r in before.values() if _verified(r, a.combo))} "
          f"verified, after {sum(1 for r in after if _verified(r, a.combo))}; {len(pairs)} moved")
    for b, r in pairs:
        print(f"\n{r['paper']} [{r['number']}] {state(b)} -> {state(r)}")
        print(f"   RAW: {r['raw'][:200]}")
        pb, pr = b.get("parse_new") or {}, r.get("parse_new") or {}
        if pb != pr:
            print(f"   before: T={pb.get('title')!r} A={pb.get('authors')}")
            print(f"   after:  T={pr.get('title')!r} A={pr.get('authors')}")
        else:
            print(f"   parse: T={pr.get('title')!r} A={(pr.get('authors') or [])[:4]}")
        _print_row(b, a.combo, "before")
        _print_row(r, a.combo, "after")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="score the four combinations and write them as JSON")
    r.add_argument("out")
    r.add_argument("--source", choices=("cases", "corpus"), default="cases")
    r.add_argument("--cases", default=DEFAULT_CASES)
    r.add_argument("--corpus", default=DEFAULT_CORPUS)
    r.add_argument("--refs", default=None, help="cache the corpus extraction and old parse here")
    r.add_argument("--scripts", default=str(DEFAULT_SCRIPTS),
                   help="import hallucite's modules from this directory (a snapshot)")
    r.add_argument("--dblp", default=DEFAULT_DBLP)
    r.set_defaults(func=run)
    m = sub.add_parser("moved", help="list the references old_old and new_new disagree on")
    m.add_argument("out")
    m.add_argument("which", nargs="?", choices=("lost", "gained"), default="lost")
    m.set_defaults(func=moved)
    d = sub.add_parser("diff", help="list the references whose verdict differs between two runs")
    d.add_argument("before")
    d.add_argument("after")
    d.add_argument("--combo", choices=COMBOS, default="new_new")
    d.set_defaults(func=diff)
    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
