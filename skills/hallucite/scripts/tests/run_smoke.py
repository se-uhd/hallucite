#!/usr/bin/env python3
"""Smoke tests for hallucite: fast, dependency-light guards on the pipeline's data
contract and the plugin packaging. Run in CI (.github/workflows/smoke.yml) and locally:

    python skills/hallucite/scripts/tests/run_smoke.py

Tiers (any failing check exits non-zero):
  1  packaging/consistency -- version in sync across plugin.json / SKILL.md / CHANGELOG,
                              JSON validity, SKILL.md frontmatter, every script compiles,
                              referenced script paths exist, SKILL.md drives the pipeline via
                              run.sh and states the stop conditions.
  1b run.sh bootstrap        -- the wrapper syntax-checks, rejects an unknown command, and fails
                              loud (sentinel + non-zero) when its Python lacks hallucinator.
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
import os
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
        tags = subprocess.run(["git", "-C", str(REPO), "tag", "-l", "v*"],
                              capture_output=True, text=True).stdout.split()
    except Exception:
        tags = []
    if not tags:
        C.skip("git tags unavailable (shallow checkout); release-tag check skipped")
    elif f"v{pv}" in tags:
        C.ok(f"release tag v{pv} exists")
    else:
        C.skip(f"tag v{pv} not present yet (tag the release commit before publishing)")

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

    run_sh = SCRIPTS / "run.sh"
    C.true(run_sh.exists(), "runner present: run.sh")
    C.true(run_sh.exists() and os.access(run_sh, os.X_OK), "run.sh is executable")
    # SKILL.md must drive the pipeline through run.sh, not a bare `python <script>` that the
    # plugin's shell may not have -- the failure that let a broken run masquerade as a clean one.
    C.true('run.sh' in skill, "SKILL.md invokes the run.sh wrapper")
    C.true('python "$SCRIPTS"' not in skill,
           "SKILL.md has no bare `python \"$SCRIPTS\"` calls (use run.sh)")
    C.true("Stop conditions" in skill and "No script output" in skill,
           "SKILL.md states the no-output-no-verdict stop conditions")


def tier1b_runner() -> None:
    """The run.sh bootstrap contract, without needing a network or a built venv: it must
    syntax-check, reject an unknown command, fail loud (sentinel + non-zero) on a Python that
    cannot import hallucinator, and -- when hallucinator is present -- print HALLUCITE_OK and
    forward a subcommand. The auto-provision path (build a venv + pip install) needs the network
    and is exercised manually, not here; tier4 runs a real audit *through* run.sh."""
    print("Tier 1b: run.sh bootstrap contract")
    run_sh = SCRIPTS / "run.sh"
    if which("bash") is None:
        C.skip("bash not available; run.sh contract skipped")
        return
    SENTINEL = "HALLUCITE_BOOTSTRAP_FAILED:"

    def run(args, **over):
        env = {**os.environ, **over.pop("env_add", {})}
        return subprocess.run(["bash", str(run_sh), *args], capture_output=True, text=True,
                              env=env, **over)

    r = subprocess.run(["bash", "-n", str(run_sh)], capture_output=True, text=True)
    C.true(r.returncode == 0, "run.sh passes `bash -n` syntax check"
           + ("" if r.returncode == 0 else f" :: {r.stderr.strip()}"))

    r = run(["frobnicate"])
    C.true(r.returncode != 0 and SENTINEL in r.stderr,
           "run.sh rejects an unknown command with the failure sentinel")

    r = run([])
    C.true(r.returncode != 0, "run.sh with no subcommand exits non-zero (usage)")

    # FAIL-LOUD, exercised deterministically regardless of the host's Pythons: a HALLUCITE_PYTHON
    # that is not even executable can never import hallucinator, so resolve_python must `die` with
    # the sentinel rather than fall through to a silent run. This is the guarantee that stops a
    # broken environment from masquerading as a clean audit.
    r = run(["doctor"], env_add={"HALLUCITE_PYTHON": str(TESTS / "no-such-python")})
    C.true(r.returncode != 0 and SENTINEL in r.stderr,
           "REGRESSION GUARD: run.sh fails loud (sentinel) when HALLUCITE_PYTHON is unusable")

    # HAPPY PATH + subcommand dispatch, when a hallucinator-capable Python exists. Point
    # HALLUCITE_PYTHON at it so no venv is provisioned, then check both `doctor` and that an unknown
    # *script* flag is forwarded (proving args reach the underlying script, not swallowed by run.sh).
    if subprocess.run([sys.executable, "-c", "import hallucinator"],
                      capture_output=True).returncode == 0:
        r = run(["doctor"], env_add={"HALLUCITE_PYTHON": sys.executable})
        C.true(r.returncode == 0 and "HALLUCITE_OK:" in r.stdout,
               "run.sh doctor prints HALLUCITE_OK for a hallucinator-capable Python")
        r = run(["audit", "--this-flag-does-not-exist"],
                env_add={"HALLUCITE_PYTHON": sys.executable})
        C.true(r.returncode != 0 and SENTINEL not in r.stderr
               and "audit_references.py" in (r.stderr + r.stdout),
               "run.sh forwards a subcommand+args to the underlying script (argparse error, "
               "not a bootstrap failure)")
    else:
        C.skip("hallucinator not importable from sys.executable; run.sh happy-path checks skipped")


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


def tier3b_triage_concurrency() -> None:
    print("Tier 3b: triage worklist slicing + verdicts locking (no network/DB)")
    import triage

    def paper(pid, nums):
        return {"paper_id": pid, "references": [
            {"original_number": n, "raw_citation": f"{pid} cite {n}",
             "db_verification": {"status": "not_found"}} for n in nums]}

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        # Two paper_ids where one is a prefix of the other -- the paper6 / paper66 trap.
        (out / "p6.json").write_text(json.dumps(paper("esem26-seip-paper6", [3, 4, 5])))
        (out / "p66.json").write_text(json.dumps(paper("esem26-seip-paper66", [1, 2, 7, 10])))

        # --paper emits exactly one paper's slice by EXACT id match: the prefix neither leaks in
        # nor steals the other's references.
        triage.cmd_worklist(out, paper_id="esem26-seip-paper6")
        slice6 = json.loads((out / "triage_worklist-esem26-seip-paper6.json").read_text())
        C.eq({e["paper_id"] for e in slice6}, {"esem26-seip-paper6"},
             "REGRESSION GUARD: --paper paper6 slice holds only paper6 (not paper66)")
        C.eq(sorted(e["number"] for e in slice6), [3, 4, 5], "--paper paper6 slice has paper6's refs")
        triage.cmd_worklist(out, paper_id="esem26-seip-paper66")
        slice66 = json.loads((out / "triage_worklist-esem26-seip-paper66.json").read_text())
        C.eq(sorted(e["number"] for e in slice66), [1, 2, 7, 10],
             "--paper paper66 slice has paper66's refs")

        # An unknown id fails loudly instead of silently writing an empty/wrong slice.
        try:
            triage.cmd_worklist(out, paper_id="esem26-seip-paper999")
            C.fail("--paper with an unknown id should raise SystemExit")
        except SystemExit:
            C.ok("--paper with an unknown id raises SystemExit")

    # The verdicts lock prevents lost updates: many concurrent `record` processes each writing a
    # distinct key must all survive (the pre-lock load/modify/write would drop most of them).
    triage_py = SCRIPTS / "triage.py"
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "p.json").write_text(json.dumps(paper("p", list(range(1, 21)))))
        procs = [subprocess.Popen(
            [sys.executable, str(triage_py), "record", "p", str(i),
             "real-published", f"finding {i}", "--out", str(out)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for i in range(1, 21)]
        for p in procs:
            p.wait()
        saved = json.loads((out / "triage_verdicts.json").read_text())
        C.eq(len(saved), 20,
             "REGRESSION GUARD: 20 concurrent record writes all persist (verdicts lock, no lost update)")


def tier3c_title_first_gate() -> None:
    print("Tier 3c: title-first record gate + fabrication signals (no network/DB)")
    import triage
    triage_py = SCRIPTS / "triage.py"

    def rec(out, num, category, signals=None):
        cmd = [sys.executable, str(triage_py), "record", "p", str(num), category, "finding",
               "--out", str(out)]
        if signals is not None:
            cmd += ["--signals", json.dumps(signals)]
        return subprocess.run(cmd, capture_output=True, text=True).returncode

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        refs = [{"original_number": n, "raw_citation": f"cite {n}",
                 "db_verification": {"status": "not_found"},
                 "parsed": {"title": f"Title {n}"}} for n in range(1, 8)]
        (out / "p.json").write_text(json.dumps(
            {"paper_id": "p", "pdf_path": "p.pdf", "num_references": 7, "references": refs}))

        # The gate: a partial-match must name a matched real title; likely-hallucinated must assert
        # the title was not found. These are the misclassifications that caused the long correction.
        C.true(rec(out, 1, "partial-match") != 0,
               "REGRESSION GUARD: partial-match without --signals is rejected")
        C.true(rec(out, 1, "partial-match", {"title_match": "no"}) != 0,
               "REGRESSION GUARD: partial-match with title_match=no is rejected")
        C.true(rec(out, 1, "partial-match", {"title_match": "yes"}) != 0,
               "partial-match with title_match=yes but no matched_title is rejected")
        C.eq(rec(out, 1, "partial-match", {"title_match": "yes", "matched_title": "Real"}), 0,
             "partial-match with title_match=yes + matched_title is accepted")
        C.true(rec(out, 2, "likely-hallucinated", {"title_match": "yes", "matched_title": "x"}) != 0,
               "likely-hallucinated with title_match=yes is rejected")
        C.eq(rec(out, 2, "likely-hallucinated", {"title_match": "no"}), 0,
             "likely-hallucinated with title_match=no is accepted")
        C.true(rec(out, 3, "unclear", {"title_match": "maybe"}) != 0,
               "an out-of-vocabulary signal value is rejected")
        C.eq(rec(out, 4, "real-published"), 0, "real-* without signals is accepted (optional)")
        # Grey literature (a web page, not a publication) uses title_match=na and needs no
        # matched_title -- the gate must not block it (the paper82 "Copy for AI" case).
        C.eq(rec(out, 5, "partial-match", {"title_match": "na", "venue_match": "yes"}), 0,
             "partial-match with title_match=na (non-publication resource) is accepted")

    # is_fabrication: a non-existent title (T) is itself the desk-reject trigger -- even with real
    # authors and a real venue otherwise intact (the paper33 case: invented title, real six-author
    # group, real ICSE 2020 association). Requiring a compounding signal would miss exactly this.
    C.true(triage.is_fabrication({"signals": {"title_match": "no"}}),
           "REGRESSION GUARD: title_match=no alone is a desk-reject candidate (real authors/venue, invented title)")
    C.true(triage.is_fabrication({"signals": {"title_match": "no", "authors_match": "yes", "venue_match": "no"}}),
           "is_fabrication: title_match=no with compounding signals")
    C.true(not triage.is_fabrication({"signals": {"title_match": "yes", "venue_match": "no"}}),
           "is_fabrication: a real title with a wrong venue is a citation error, not fabrication")
    # A dead/misresolving DOI on a real title is an honest citation error (the off-by-one-digit
    # case), NOT fabrication -- the title, not the DOI, is the decisive signal.
    C.true(not triage.is_fabrication({"signals": {"title_match": "yes", "doi_status": "404"}}),
           "is_fabrication: a real title with a dead DOI is a citation error, not fabrication")
    C.true(not triage.is_fabrication({"signals": {"title_match": "na", "venue_match": "no"}}),
           "is_fabrication: a non-publication resource (na) is never a fabricated title")

    # report surfaces the discriminating facts and the desk-reject section.
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        refs = [{"original_number": 1, "raw_citation": "Real Authors. Invented Title. ICSE, 2020.",
                 "db_verification": {"status": "not_found"}, "parsed": {"title": "Invented Title"}}]
        (out / "p.json").write_text(json.dumps(
            {"paper_id": "p", "pdf_path": "p.pdf", "num_references": 1, "references": refs}))
        rec(out, 1, "likely-hallucinated",
            {"title_match": "no", "authors_match": "yes", "venue_match": "no", "doi_status": "none"})
        triage.cmd_report(out)
        rollup = (out / "reports" / "potential-hallucinations.md").read_text()
        C.true("Desk-reject candidates" in rollup,
               "report rollup has a Desk-reject candidates section for a fabricated-title ref")
        C.true("no publication bears the cited title" in rollup,
               "report shows the cited title matched no publication")
        C.true("title=no" in rollup, "report prints the structured signal summary")


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
        # Drive the audit through run.sh (HALLUCITE_PYTHON pins this interpreter, so no venv is
        # provisioned), so the wrapper's dispatch and argument forwarding are on the end-to-end
        # tested path rather than bypassed. Falls back to a direct call only if bash is absent.
        if which("bash") is not None:
            cmd = ["bash", str(SCRIPTS / "run.sh"), "audit", str(pdf),
                   "--offline", "--dblp", str(tmp / "dblp.db"), "--out", str(out)]
            env = {**os.environ, "HALLUCITE_PYTHON": sys.executable}
        else:
            cmd = [sys.executable, str(SCRIPTS / "audit_references.py"), str(pdf),
                   "--offline", "--dblp", str(tmp / "dblp.db"), "--out", str(out)]
            env = None
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
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
    tier1b_runner()
    tier3_logic()
    tier3b_triage_concurrency()
    tier3c_title_first_gate()
    tier4_end_to_end()
    print()
    if C.failed:
        print(f"SMOKE FAILED: {C.failed} check(s) failed, {C.skipped} skipped")
        return 1
    print(f"SMOKE OK: all checks passed ({C.skipped} skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
