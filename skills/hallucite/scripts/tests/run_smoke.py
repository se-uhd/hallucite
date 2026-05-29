#!/usr/bin/env python3
"""Smoke tests for hallucite: fast, dependency-light guards on the pipeline's data
contract and the plugin packaging. Run in CI (.github/workflows/smoke.yml) and locally:

    python skills/hallucite/scripts/tests/run_smoke.py

Tiers (any failing check exits non-zero):
  1  packaging/consistency -- version in sync across plugin.json / SKILL.md / CHANGELOG,
                              JSON validity, SKILL.md frontmatter, every script compiles,
                              referenced script paths exist.
  3  logic contract        -- needs_triage / paper_status_counts on synthetic records,
                              including the "mismatch" status a past bug silently dropped,
                              and category/severity consistency. No network or DB.
  4  end-to-end (offline)   -- build a tiny fixture DBLP DB, run the real audit --offline on a
                              synthetic fixture PDF, assert verified/not_found. Needs the
                              hallucinator package and pdftotext (poppler); skipped if absent.

Tier 2 (Markdown lint) runs as a separate CI step via lint_markdown.py.
The fixture PDF (tests/fixtures/synthetic_paper.pdf) was generated from the adjacent .txt
with `cupsfilter`; it contains only invented authors/titles (no real or shared paper data).
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
HALLUCITE = SCRIPTS.parent            # skills/hallucite
REPO = SCRIPTS.parents[2]             # scripts -> hallucite -> skills -> repo
FIXTURES = TESTS / "fixtures"
sys.path.insert(0, str(SCRIPTS))


class Checks:
    def __init__(self) -> None:
        self.failed = 0
        self.skipped = 0

    def ok(self, msg: str) -> None:
        print(f"  ok   {msg}")

    def fail(self, msg: str) -> None:
        self.failed += 1
        print(f"  FAIL {msg}")

    def skip(self, msg: str) -> None:
        self.skipped += 1
        print(f"  skip {msg}")

    def eq(self, got, want, msg: str) -> None:
        self.ok(msg) if got == want else self.fail(f"{msg} (got {got!r}, want {want!r})")

    def true(self, cond, msg: str) -> None:
        self.ok(msg) if cond else self.fail(msg)


C = Checks()


def tier1_packaging() -> None:
    print("Tier 1: packaging / consistency")
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    skill = (HALLUCITE / "SKILL.md").read_text()
    changelog = (REPO / "CHANGELOG.md").read_text()

    parts = skill.split("---", 2)
    fm = parts[1] if len(parts) >= 3 else ""
    pv = plugin.get("version")
    m = re.search(r'^\s*version:\s*"([^"]+)"', fm, re.M)
    sv = m.group(1) if m else None
    m = re.search(r'^##\s*\[([0-9]+\.[0-9]+\.[0-9]+)\]', changelog, re.M)
    cv = m.group(1) if m else None
    C.true(pv is not None and pv == sv == cv,
           f"version in sync: plugin.json={pv}, SKILL.md={sv}, CHANGELOG latest={cv}")

    try:
        tags = subprocess.run(["git", "-C", str(REPO), "tag", "-l", "hallucite--v*"],
                              capture_output=True, text=True).stdout.split()
    except Exception:
        tags = []
    if not tags:
        C.skip("git tags unavailable (shallow checkout); release-tag check skipped")
    elif f"hallucite--v{pv}" in tags:
        C.ok(f"release tag hallucite--v{pv} exists")
    else:
        C.skip(f"tag hallucite--v{pv} not present yet (tag the release commit before publishing)")

    C.eq(market.get("name"), "se-uhd", "marketplace name = se-uhd")
    C.true(any(p.get("source") in ("./", ".") for p in (market.get("plugins") or [])),
           "marketplace plugin source is the repo root")
    C.true(re.search(r'^\s*name:\s*hallucite\s*$', fm, re.M) is not None,
           "SKILL.md frontmatter name = hallucite")

    for p in sorted(SCRIPTS.glob("*.py")):
        r = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                           capture_output=True, text=True)
        C.true(r.returncode == 0, f"compiles: {p.name}"
               + ("" if r.returncode == 0 else f" :: {r.stderr.strip().splitlines()[-1:]}"))

    for name in ("audit_references.py", "triage.py", "pdf_references.py"):
        C.true((SCRIPTS / name).exists(), f"pipeline script present: {name}")


def tier3_logic() -> None:
    print("Tier 3: logic contract (no network/DB)")
    import triage

    C.true(set(triage.FLAG_CATEGORIES) <= set(triage.SEVERITY),
           "FLAG_CATEGORIES is a subset of SEVERITY")

    def ref(status):
        return {"db_verification": None if status is None else {"status": status}}

    # The contract: triage iff the validator checked it but did not confirm ("verified").
    expect = {"verified": False, "not_found": True, "mismatch": True,
              "unparsed": True, "author_mismatch": True, None: False}
    for status, want in expect.items():
        C.eq(triage.needs_triage(ref(status)), want, f"needs_triage(status={status!r})")
    C.true(triage.needs_triage(ref("mismatch")),
           "REGRESSION GUARD: a 'mismatch' reference reaches triage")

    try:
        import audit_references as audit
    except SystemExit:
        C.skip("paper_status_counts: hallucinator absent; audit_references import skipped")
        return
    record = {"references": [
        {"db_verification": {"status": "verified"}},
        {"db_verification": {"status": "not_found"}},
        {"db_verification": {"status": "mismatch"}},
        {"db_verification": {"status": "unparsed"}},
        {"db_verification": None},          # --no-verify / pending
    ]}
    counts = audit.paper_status_counts(record)
    C.eq(counts["verified"], 1, "counts.verified")
    C.eq(counts["pending"], 1, "counts.pending")
    C.eq(counts.get("mismatch"), 1, "counts.mismatch is tallied")
    C.eq(counts["unverified"], 3, "counts.unverified = not_found + mismatch + unparsed")
    checked = sum(1 for r in record["references"] if r["db_verification"] is not None)
    C.eq(counts["verified"] + counts["unverified"], checked,
         "INVARIANT: verified + unverified == checked references (none silently dropped)")


def _build_fixture_db(path: Path) -> None:
    """A few-KB DBLP DB matching hallucinator's offline schema (4 tables + an FTS5 index).
    Seeded so the synthetic fixture PDF yields verified (1, 4) and not_found (2, 3)."""
    con = sqlite3.connect(str(path))
    c = con.cursor()
    c.executescript("""
        CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE publication_authors (pub_id INTEGER NOT NULL, author_id INTEGER NOT NULL,
            PRIMARY KEY (pub_id, author_id));
        CREATE TABLE publications (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, title TEXT NOT NULL);
        CREATE VIRTUAL TABLE publications_fts USING fts5(title, content='publications', content_rowid='id');
    """)
    pubs = [
        (1, "conf/ic/AndersonB20", "A study of synthetic widgets in distributed systems",
         ["Alice Anderson", "Bob Brown"]),
        (2, "journals/mbr/XuY19", "Foundations of fictional algorithms",
         ["Xavier Xu", "Yara Young"]),     # title hit, different authors
        (4, "journals/ttf/FosterGH22", "Patterns of placeholder data in software testing",
         ["Frank Foster", "Grace Green", "Henry Hughes"]),
    ]
    aid: dict[str, int] = {}
    for pid, key, title, authors in pubs:
        c.execute("INSERT INTO publications(id,key,title) VALUES(?,?,?)", (pid, key, title))
        for a in authors:
            if a not in aid:
                c.execute("INSERT INTO authors(name) VALUES(?)", (a,))
                aid[a] = c.lastrowid
            c.execute("INSERT INTO publication_authors(pub_id,author_id) VALUES(?,?)", (pid, aid[a]))
    c.execute("INSERT INTO publications_fts(publications_fts) VALUES('rebuild')")
    meta = {"schema_version": "3", "last_updated": "1779901174",
            "last_modified": "Wed, 27 May 2026 03:14:57 GMT",
            "publication_count": str(len(pubs)), "author_count": str(len(aid))}
    c.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", meta.items())
    con.commit()
    con.close()


def tier4_end_to_end() -> None:
    print("Tier 4: end-to-end offline audit (fixture DBLP DB)")
    pdf = FIXTURES / "synthetic_paper.pdf"
    if not pdf.exists():
        C.fail(f"missing fixture PDF {pdf}")
        return
    try:
        import hallucinator  # noqa: F401
    except ImportError:
        C.skip("hallucinator not installed; end-to-end tier skipped")
        return
    if which("pdftotext") is None:
        C.skip("pdftotext (poppler) not installed; end-to-end tier skipped")
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _build_fixture_db(tmp / "dblp.db")
        out = tmp / "out"
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "audit_references.py"), str(pdf),
             "--offline", "--dblp", str(tmp / "dblp.db"), "--out", str(out)],
            capture_output=True, text=True)
        rec_path = out / f"{pdf.stem}.json"
        if not rec_path.exists():
            C.fail(f"audit produced no record (exit {r.returncode}): {r.stderr[-300:]}")
            return
        rec = json.loads(rec_path.read_text())
        C.eq(rec["num_references"], 4, "extracted 4 references")
        C.eq(rec["extraction"]["unparsed"], 0, "0 unparsed references")
        st = {x["original_number"]: (x.get("db_verification") or {}).get("status")
              for x in rec["references"]}
        C.eq(st.get(1), "verified", "ref [1] verified (exact DBLP match)")
        C.eq(st.get(4), "verified", "ref [4] verified (exact DBLP match)")
        C.eq(st.get(3), "not_found", "ref [3] not_found (absent from DBLP)")
        C.eq(sum(1 for s in st.values() if s == "verified"), 2, "exactly 2 verified")


def main() -> int:
    tier1_packaging()
    tier3_logic()
    tier4_end_to_end()
    print()
    if C.failed:
        print(f"SMOKE FAILED: {C.failed} check(s) failed, {C.skipped} skipped")
        return 1
    print(f"SMOKE OK: all checks passed ({C.skipped} skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
