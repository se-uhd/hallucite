"""The corruption harness: real DBLP records cited correctly, then corrupted, scored through
`Verifier.check` with the online backends disabled.

The truth is known by construction. A record cited under its own title and authors must confirm;
cited with an author appended, an author replaced, a title word changed, the title reversed or
invented, it must not. A confirmation that lands on a record other than the one sampled is counted
separately: for a correct citation it is usually the preprint twin of the sampled record, for a
corrupted one it is a false confirmation with a name attached.

Three sets, each built once and then handed to every setting under test. Drawing fresh invented
names per setting reports holes that are not there.

* `three_plus_tokens`: 250 records with a complete byline and a title of three or more FTS tokens.
  This is the set the strictness is stated over -- correct 250, `et al.` 250, first author only
  250, one, two or three invented names appended 0, one swapped 0 -- and it has to stay there.
* `two_tokens`: 250 records with a two-token title, the population `_MIN_TOKENS` decides about,
  which the first set cannot see.
* `truncated_records` (a separate file): records whose byline DBLP cut short with an `et al.` row,
  the population the lenient author tier decides about.

    corruptions.py build            [--out ~/hallucite/corruptions.json]
    corruptions.py build-truncated  [--out ~/hallucite/corruptions-truncated.json]
    corruptions.py score FILE [--scripts DIR] [--label NAME]

The record keys are those of the mirror the set was built from; a rebuild on a newer dump samples
different records, so keep the built file with the other anchors in `~/hallucite/` and score
against it rather than rebuilding.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SCRIPTS = HERE.parent
DEFAULT_DBLP = os.environ.get("HALLUCITE_DBLP", os.path.expanduser("~/hallucite/dblp.db"))
DEFAULT_OUT = os.path.expanduser("~/hallucite/corruptions.json")
DEFAULT_TRUNCATED_OUT = os.path.expanduser("~/hallucite/corruptions-truncated.json")
ONLINE = ("CrossRef", "DOI", "arXiv", "Semantic Scholar")
SEED = 20260911
TRUNCATED_SEED = 20260912
# Syllables for invented names; every name drawn is checked against the authors table.
SYLLABLES = ["bar", "den", "fol", "gar", "hal", "jen", "kol", "lim", "mor", "nes", "pol", "quen",
             "ril", "sot", "tur", "vel", "wik", "zan", "ash", "bri"]


def _tokens(title: str, fold) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(title))


class _Sampler:
    def __init__(self, dblp: str, seed: int) -> None:
        sys.path.insert(0, str(DEFAULT_SCRIPTS))
        import dblp_check
        self.D = dblp_check
        self.rng = random.Random(seed)
        self.con = sqlite3.connect(f"file:{dblp}?mode=ro", uri=True)
        self.max_id = self.con.execute("SELECT MAX(id) FROM publications").fetchone()[0]

    def authors_of(self, pid: int) -> list[str]:
        return [self.D._HOMONYM_SUFFIX.sub("", r[0]) for r in self.con.execute(
            "SELECT a.name FROM publication_authors pa JOIN authors a ON a.id = pa.author_id "
            "WHERE pa.pub_id = ? ORDER BY pa.rowid", (pid,))]

    def invent(self) -> str:
        while True:
            first = (self.rng.choice(SYLLABLES) + self.rng.choice(SYLLABLES)).capitalize()
            last = (self.rng.choice(SYLLABLES) + self.rng.choice(SYLLABLES)
                    + self.rng.choice(SYLLABLES)).capitalize()
            name = f"{first} {last}"
            if not self.con.execute("SELECT 1 FROM authors WHERE name = ? LIMIT 1",
                                    (name,)).fetchone():
                return name

    def sample(self, want: int, title_ok) -> list[dict]:
        out: list[dict] = []
        while len(out) < want:
            pid = self.rng.randint(1, self.max_id)
            row = self.con.execute("SELECT id, key, title FROM publications WHERE id = ?",
                                   (pid,)).fetchone()
            if not row:
                continue
            authors = self.authors_of(row[0])
            if (len(authors) < 2 or not self.D.record_authors_complete(authors)
                    or not title_ok(row[2]) or any(not self.D._is_person(a) for a in authors)):
                continue
            out.append({"key": row[1], "title": row[2], "authors": authors})
        return out

    def corrupt(self, rec: dict) -> dict:
        D, rng = self.D, self.rng
        title, authors = rec["title"], rec["authors"]
        invented = [self.invent() for _ in range(3)]
        swapped = list(authors)
        swapped[rng.randrange(len(authors))] = invented[0]
        words = title.split()
        content = [i for i, w in enumerate(words) if len(re.sub(r"[^a-z]", "", w.lower())) >= 4]
        changed = list(words)
        if content:
            changed[rng.choice(content)] = self.invent().split()[1]
        head = D._SUBTITLE.split(title, maxsplit=1)[0]
        respaced = (re.sub(r"-", " ", title) if "-" in title
                    else re.sub(r"(\w{4})(\w{3,})", r"\1-\2", title, count=1))
        return {
            "clean": {"title": title, "authors": authors},
            "et_al": {"title": title, "authors": [authors[0], "et al."]},
            "first_only": {"title": title, "authors": [authors[0]]},
            "plus1": {"title": title, "authors": authors + invented[:1]},
            "plus2": {"title": title, "authors": authors + invented[:2]},
            "plus3": {"title": title, "authors": authors + invented[:3]},
            "swapped": {"title": title, "authors": swapped},
            "word_changed": {"title": " ".join(changed), "authors": authors} if content else None,
            "reversed": ({"title": " ".join(reversed(words)), "authors": authors}
                         if len(words) >= 3 else None),
            "invented_title": {"title": " ".join(self.invent().split()[1]
                                                 for _ in range(max(3, len(words)))),
                               "authors": authors},
            "subtitle_dropped": ({"title": head, "authors": authors}
                                 if head != title and D._subtitle_head(title) else None),
            "respaced": {"title": respaced, "authors": authors},
        }


def build(a) -> int:
    s = _Sampler(a.dblp, SEED)
    fold = s.D._fold
    long = s.sample(250, lambda t: len(_tokens(t, fold)) >= 3)
    two = s.sample(250, lambda t: len(_tokens(t, fold)) == 2)
    data = {"seed": SEED, "sets": {
        "three_plus_tokens": [{"record": r, "variants": s.corrupt(r)} for r in long],
        "two_tokens": [{"record": r, "variants": s.corrupt(r)} for r in two]}}
    json.dump(data, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"built {len(long)} + {len(two)} records -> {a.out}")
    return 0


def build_truncated(a) -> int:
    s = _Sampler(a.dblp, TRUNCATED_SEED)
    D = s.D
    row = s.con.execute("SELECT id FROM authors WHERE name = 'et al.'").fetchone()
    if not row:
        sys.exit("error: this mirror holds no 'et al.' author row")
    pids = [r[0] for r in s.con.execute(
        "SELECT pub_id FROM publication_authors WHERE author_id = ?", (row[0],))]
    s.rng.shuffle(pids)
    out = []
    for pid in pids:
        key, title = s.con.execute("SELECT key, title FROM publications WHERE id = ?",
                                   (pid,)).fetchone()
        authors = s.authors_of(pid)
        people = [x for x in authors if not D._ET_AL_ROW.match(x)]
        if (len(people) < 3 or len(_tokens(title, D._fold)) < 3
                or any(not D._is_person(x) for x in people)):
            continue
        invented = [s.invent(), s.invent()]
        out.append({"record": {"key": key, "title": title, "authors": authors}, "variants": {
            "clean_first3_etal": {"title": title, "authors": people[:3] + ["et al."]},
            "first_only": {"title": title, "authors": people[:1]},
            "plus1": {"title": title, "authors": people[:3] + invented[:1]},
            "wholly_invented": {"title": title, "authors": invented},
            "first_swapped": {"title": title, "authors": [invented[0]] + people[1:3]}}})
        if len(out) >= a.count:
            break
    json.dump({"seed": TRUNCATED_SEED, "sets": {"truncated_records": out}},
              open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"built {len(out)} truncated records (of {len(pids)} in the mirror) -> {a.out}")
    return 0


class _Ref:
    def __init__(self, variant: dict) -> None:
        self.title = variant["title"]
        self.authors = list(variant["authors"])
        self.doi = None
        self.arxiv_id = None


def score(a) -> int:
    sys.path.insert(0, str(Path(a.scripts).resolve()))
    from audit_references import verification_dict
    from verifier import Verifier
    data = json.load(open(a.file, encoding="utf-8"))
    verifier = Verifier(dblp_path=a.dblp, disabled_dbs=ONLINE)
    started = time.time()
    for name, recs in data["sets"].items():
        cells = []
        for column in recs[0]["variants"]:
            items = [(r["record"], r["variants"][column]) for r in recs
                     if r["variants"].get(column)]
            hits = other = 0
            for (rec, variant), result in zip(items, verifier.check([_Ref(v) for _, v in items])):
                d = verification_dict(result)
                if d.get("status") == "verified":
                    hits += 1
                    if not (d.get("paper_url") or "").endswith("/" + rec["key"]):
                        other += 1
            cells.append(f"{column} {hits}/{len(items)}" + (f" (other record {other})"
                                                             if other else ""))
        print(f"[{a.label}] {name}: " + "   ".join(cells), flush=True)
    print(f"  {time.time() - started:.0f}s", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dblp", default=DEFAULT_DBLP)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="sample the two title sets and build every corruption once")
    b.add_argument("--out", default=DEFAULT_OUT)
    b.set_defaults(func=build)
    t = sub.add_parser("build-truncated", help="sample records DBLP truncated with an et al. row")
    t.add_argument("--out", default=DEFAULT_TRUNCATED_OUT)
    t.add_argument("--count", type=int, default=100)
    t.set_defaults(func=build_truncated)
    s = sub.add_parser("score", help="score an implementation against a built set")
    s.add_argument("file")
    s.add_argument("--scripts", default=str(DEFAULT_SCRIPTS),
                   help="import hallucite's modules from this directory (a snapshot)")
    s.add_argument("--label", default="working tree")
    s.set_defaults(func=score)
    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
