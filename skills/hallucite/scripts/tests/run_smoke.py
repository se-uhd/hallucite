#!/usr/bin/env python3
"""Smoke tests for hallucite: fast, dependency-light guards on the pipeline's data
contract and the plugin packaging. Run in CI (.github/workflows/smoke.yml) and locally:

    python skills/hallucite/scripts/tests/run_smoke.py

Tiers (any failing check exits non-zero):
  1  packaging/consistency -- version in sync across Claude/Codex manifests / SKILL.md /
                              CHANGELOG, JSON validity, SKILL.md frontmatter, every script
                              compiles, referenced script paths exist, Claude and Codex
                              marketplace shapes, repo-local symlink shims, AGENTS.md, and
                              SKILL.md runner resolver branches.
  1b run.sh bootstrap       -- the wrapper syntax-checks, rejects an unknown command, fails loud
                              (sentinel + non-zero) when its Python is unusable, and reads the
                              gitignored .env.local without letting it override the environment.
  1c Codex CLI marketplace  -- optional when `codex` is installed: register this repo in an
                              isolated CODEX_HOME and assert hallucite@hallucite is listed.
  3  logic contract        -- needs_triage / paper_status_counts on synthetic records,
                              including the "mismatch" status a past bug silently dropped,
                              and category/severity consistency. No network or DB.
  3b triage concurrency    -- worklist --paper slice isolation (the paper6/paper66 prefix case)
                              and the fcntl verdicts lock under concurrent writers.
  3c title-first gate      -- record --signals enforcement (including the contradictory
                              unclear+title_match=no and unknown paper:number rejections),
                              is_fabrication's category gate, and the desk-reject report section.
  3i dblp author encoding  -- an offline DBLP mirror holding no accented author name is
                              reported: its ingest dropped those authors, so DBLP disagrees
                              with correctly cited references. No network.
  3g stale verdicts        -- a verdict recorded against reference text a re-audit then changed
                              is quarantined: report shows it as stale/pending (never the old
                              category against the new reference) and --pending resurfaces it.
  3j residue evidence      -- what the audit knows about an unverified reference reaches the
                              worklist, the report and the verification sheet: the backends never
                              asked (`skipped`), what a cited DOI or arXiv id resolved to, and the
                              mirror's nearest title, offered only with every cited author on it.
                              Fixture DB; no network.
  3h author absence        -- a cited author that no author of the matched publication
                              accounts for demotes the reference to triage, while name-form
                              differences, parser artifacts and truncated database author
                              rows do not. No network/DB.
  3d repeated entries      -- entries sharing authors+title under different citation keys are
                              grouped and classified: identical in every field = duplicate (a
                              fact), differing venue/volume/pages = conflicting (an open question).
  3e reference labels      -- a numeric bibliography reports its printed "[N]"; an unnumbered
                              author-year one reports the citation key the paper itself uses, and
                              any tool-internal index is marked as not appearing in the paper.
  4  end-to-end (offline)   -- build a tiny fixture DBLP DB, run the real audit --offline on a
                              synthetic fixture PDF, assert verified/not_found. Needs pdftotext
                              (poppler); skipped if absent.
  4b extraction segmentation -- a bracket-numeric bibliography under LaTeX lineno margins, across a
                              page-break margin reset, segments as [1]..[N] (the margin numbers do
                              not hijack the sequence, drop the first entry, or collapse the tail).
                              Pure pdf_references logic; no network, DB, or poppler.
  4d DBLP title+author check -- the all-candidates check over the offline DBLP file: matches the
                              right one of several same-title records, reads an "et al." citation
                              as a truncation, and refuses wrong, invented, and phantom-author
                              citations -- a correct author list with one invented name spliced in
                              is the pattern the tool exists to catch. Pure dblp_check logic on a
                              fixture DB; no network.
  4e small-caps headings    -- an IEEE-style heading letter-spaced by pdftotext ("R EFERENCES")
                              still opens the bibliography, and the entries under it segment.
                              Pure pdf_references logic; no network, DB, or poppler.
  4h page furniture         -- the three ways a bibliography loses whole references: a running
                              head hiding the gutter on a short page, a gutter cut placed inside a
                              word, and an entry wearing a running head's disguises. No network/DB.
  4i hanging indent         -- the unnumbered author-first bibliography (Elsevier Harvard, plainnat,
                              ACM author-year): the right column aligned to the left, a bare or
                              venue-field year still voting author-year, continuations opening with
                              digits not voting numeric, and the trailing author biographies dropped.
                              No network/DB/poppler.
  5  reference parsing     -- one entry of each style the corpus prints (IEEE quoted, ACM
                              year-first, Springer inverted, the repeated-author dash), plus the
                              identifier forms, held to VERIFICATION-SPEC.md. No network/DB.
  5b verification contract  -- hallucite's own `check` on a fixture DBLP file with the online
                              backends disabled: 1:1 alignment, `verified`/`mismatch`/`not_found`,
                              a did-not-answer backend named in failed_dbs rather than folded into
                              no_match, and a disabled backend leaving no trace. No network.
  4c author-year extraction -- a Springer author-year bibliography under LaTeX lineno margins,
                              driven through the real PDF: margin numbers must be detected in both
                              renderings and blanked (not deleted) so the hanging indent still
                              delimits the entries. Needs poppler; no network or DB.

Tier 2 (Markdown lint) runs as a separate CI step via lint_markdown.py.
Both fixture PDFs contain only invented authors/titles -- no real or shared paper data.
tests/fixtures/synthetic_paper.pdf was generated from the adjacent .txt with `cupsfilter`;
tests/fixtures/lineno_authoryear.pdf is written directly by the adjacent
make_lineno_authoryear.py (cupsfilter re-wraps long lines, which would destroy the column
alignment that fixture exists to test).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
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
    claude_plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    codex_plugin = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text())
    claude_market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    codex_market = json.loads((REPO / ".agents" / "plugins" / "marketplace.json").read_text())
    skill = (HALLUCITE / "SKILL.md").read_text()
    agents_md = (REPO / "AGENTS.md").read_text()
    changelog = (REPO / "CHANGELOG.md").read_text()

    parts = skill.split("---", 2)
    fm = parts[1] if len(parts) >= 3 else ""
    pv = claude_plugin.get("version")
    cpv = codex_plugin.get("version")
    m = re.search(r'^\s*version:\s*"([^"]+)"', fm, re.M)
    sv = m.group(1) if m else None
    m = re.search(r'^##\s*\[([0-9]+\.[0-9]+\.[0-9]+)\]', changelog, re.M)
    cv = m.group(1) if m else None
    C.true(pv is not None and pv == cpv == sv == cv,
           "version in sync: "
           f"Claude plugin={pv}, Codex plugin={cpv}, SKILL.md={sv}, CHANGELOG latest={cv}")

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

    C.eq(claude_market.get("name"), "hallucite", "Claude marketplace name = hallucite")
    claude_entries = claude_market.get("plugins") or []
    C.true(any(isinstance(p.get("source"), str) and p.get("source") in ("./", ".")
               for p in claude_entries),
           "Claude marketplace plugin source is the repo root string")
    C.true(all(isinstance(p.get("source"), str) and "policy" not in p and "category" not in p
               for p in claude_entries),
           "Claude marketplace remains Claude-shaped (string source, no Codex policy/category)")

    C.eq(codex_plugin.get("name"), "hallucite", "Codex manifest name = hallucite")
    C.eq(codex_plugin.get("skills"), "./skills/", "Codex manifest skills = ./skills/")
    interface = codex_plugin.get("interface") or {}
    for field in ("displayName", "shortDescription", "longDescription",
                  "developerName", "category"):
        C.true(isinstance(interface.get(field), str) and interface[field].strip(),
               f"Codex manifest interface.{field} is present")
    C.true(isinstance(interface.get("capabilities"), list)
           and all(isinstance(v, str) and v.strip() for v in interface["capabilities"]),
           "Codex manifest interface.capabilities is an array of strings")
    prompt = interface.get("defaultPrompt") or interface.get("default_prompt")
    C.true(isinstance(prompt, list) and 1 <= len(prompt) <= 3
           and all(isinstance(v, str) and v.strip() for v in prompt),
           "Codex manifest interface.defaultPrompt has 1-3 prompts")

    C.eq(codex_market.get("name"), "hallucite", "Codex marketplace name = hallucite")
    codex_entries = codex_market.get("plugins") or []
    codex_entry = next((p for p in codex_entries if p.get("name") == "hallucite"), None)
    C.true(codex_entry is not None, "Codex marketplace has hallucite entry")
    if codex_entry is not None:
        C.eq(codex_entry.get("source"),
             {"source": "local", "path": "./plugins/hallucite"},
             "Codex marketplace source.path = ./plugins/hallucite")
        C.eq((codex_entry.get("policy") or {}).get("installation"), "AVAILABLE",
             "Codex marketplace policy.installation = AVAILABLE")
        C.eq((codex_entry.get("policy") or {}).get("authentication"), "ON_INSTALL",
             "Codex marketplace policy.authentication = ON_INSTALL")
        C.true(isinstance(codex_entry.get("category"), str) and codex_entry["category"].strip(),
               "Codex marketplace category is present")

    plugin_shim = REPO / "plugins" / "hallucite"
    C.true(plugin_shim.is_symlink(), "plugins/hallucite is a symlink")
    C.eq(plugin_shim.resolve(), REPO.resolve(), "plugins/hallucite resolves to repo root")
    skill_shim = REPO / ".agents" / "skills" / "hallucite"
    C.true(skill_shim.is_symlink(), ".agents/skills/hallucite is a symlink")
    C.eq(skill_shim.resolve(), HALLUCITE.resolve(),
         ".agents/skills/hallucite resolves to shared skill")
    C.true("CLAUDE.md" in agents_md and "[CLAUDE.md](CLAUDE.md)" in agents_md,
           "AGENTS.md points to CLAUDE.md")

    C.true(re.search(r'^\s*name:\s*hallucite\s*$', fm, re.M) is not None,
           "SKILL.md frontmatter name = hallucite")

    for p in sorted(SCRIPTS.glob("*.py")) + sorted((SCRIPTS / "measure").glob("*.py")):
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
    for label, needle in (
        ("Claude plugin install", "CLAUDE_PLUGIN_ROOT"),
        ("Codex repo-local skill shim", ".agents/skills/hallucite/scripts/run.sh"),
        ("direct repo clone", "skills/hallucite/scripts/run.sh"),
        ("Codex plugin cache root", "${CODEX_HOME:-$HOME/.codex}/plugins/cache"),
        ("preferred hallucite/hallucite cache", "*/hallucite/hallucite/*/skills/hallucite/scripts/run.sh"),
        ("fallback hallucite cache", "*/hallucite/*/skills/hallucite/scripts/run.sh"),
        ("locator failure sentinel",
         "HALLUCITE_BOOTSTRAP_FAILED: cannot locate hallucite scripts/run.sh"),
        # Version sort, not lexicographic: plain `sort` picks 1.9.0 over 1.10.0.
        ("version-sorted cache pick", "| sort -V | tail -n 1"),
    ):
        C.true(needle in skill, f"SKILL.md documents runner resolver branch: {label}")


def tier1c_codex_cli_marketplace() -> None:
    print("Tier 1c: Codex CLI marketplace discovery (optional)")
    codex = which("codex")
    if codex is None:
        C.skip("codex CLI not installed; Codex marketplace discovery skipped")
        return

    tmp_parent = Path("/private/tmp") if Path("/private/tmp").is_dir() else Path(tempfile.gettempdir())

    def run_codex(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run([codex, *args], capture_output=True, text=True,
                                  env=env, timeout=30)
        except subprocess.TimeoutExpired:
            C.fail(f"codex {' '.join(args)} timed out")
            return None

    with tempfile.TemporaryDirectory(prefix="hallucite-codex-home-", dir=str(tmp_parent)) as home:
        env = {**os.environ, "CODEX_HOME": home}
        r = run_codex(["plugin", "marketplace", "add", str(REPO)], env)
        if r is None:
            return
        C.true(r.returncode == 0, "codex plugin marketplace add <repo> succeeds"
               + ("" if r.returncode == 0 else f" :: {(r.stderr or r.stdout).strip()[-300:]}"))
        if r.returncode != 0:
            return
        r = run_codex(["plugin", "list", "--marketplace", "hallucite"], env)
        if r is None:
            return
        listing = r.stdout + r.stderr
        C.true(r.returncode == 0, "codex plugin list --marketplace hallucite succeeds"
               + ("" if r.returncode == 0 else f" :: {listing.strip()[-300:]}"))
        C.true("hallucite@hallucite" in listing,
               "codex plugin list shows hallucite@hallucite")


def tier1b_runner() -> None:
    """The run.sh bootstrap contract, without needing a network or a built venv: it must
    syntax-check, reject an unknown command, fail loud (sentinel + non-zero) on a Python that
    is not a usable Python, and otherwise print HALLUCITE_OK and
    forward a subcommand. It also has to read `.env.local` where one exists, tolerate one that does
    not, and let an explicit environment variable win. Tier 4 runs a real audit *through*
    run.sh."""
    print("Tier 1b: run.sh bootstrap contract")
    run_sh = SCRIPTS / "run.sh"
    if which("bash") is None:
        C.skip("bash not available; run.sh contract skipped")
        return
    SENTINEL = "HALLUCITE_BOOTSTRAP_FAILED:"

    def run(args, **over):
        # Keep the suite hermetic: check-env's staleness lookup would otherwise hit PyPI.
        env = {**os.environ, "HALLUCITE_NO_VERSION_CHECK": "1", **over.pop("env_add", {})}
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
    C.true("check-env" in r.stderr and "audit" in r.stderr,
           "usage lists the subcommands")

    # `.env.local` carries the API keys the online backends want. It is optional, and an explicit
    # environment variable has to win, or a one-off `S2_API_KEY=... run.sh audit` would be ignored.
    with tempfile.TemporaryDirectory() as td:
        tree = Path(td) / "skills" / "hallucite" / "scripts"
        tree.mkdir(parents=True)
        copied = tree / "run.sh"
        copied.write_text(run_sh.read_text())
        show = ["python", "-c", "import os; print(os.environ.get('SMOKE_FAKE_KEY', 'unset'))"]

        def run_copy(**over):
            env = {k: v for k, v in os.environ.items() if k != "SMOKE_FAKE_KEY"}
            env.update({"HALLUCITE_NO_VERSION_CHECK": "1", **over})
            return subprocess.run(["bash", str(copied), *show], capture_output=True, text=True,
                                  env=env)

        before = run_copy()
        C.true(before.returncode == 0 and before.stdout.strip() == "unset",
               "run.sh runs with no .env.local present")
        (Path(td) / ".env.local").write_text(
            "# a comment\n\nSMOKE_FAKE_KEY=from-the-file\n")
        C.eq(run_copy().stdout.strip(), "from-the-file",
             "run.sh reads .env.local, skipping comments and blank lines")
        C.eq(run_copy(SMOKE_FAKE_KEY="from-the-environment").stdout.strip(),
             "from-the-environment",
             "REGRESSION GUARD: a variable already set in the environment wins over the file")

    # The interpreter probe reads the *output*, not the exit status. Plenty of executables take
    # `-c` and exit 0 without running anything, and a wrapper that accepts one hands the audit an
    # interpreter that silently does nothing.
    for fake in ("/bin/echo", "/usr/bin/true"):
        if not Path(fake).exists():
            continue
        r = run(["check-env"], env_add={"HALLUCITE_PYTHON": fake})
        C.true(r.returncode != 0 and SENTINEL in r.stderr,
               f"REGRESSION GUARD: {fake} accepts `-c` and exits 0, and is still refused")

    # FAIL-LOUD, exercised deterministically regardless of the host's Pythons: a HALLUCITE_PYTHON
    # that is not even executable can never be a Python, so resolve_python must `die` with
    # the sentinel rather than fall through to a silent run. This is the guarantee that stops a
    # broken environment from masquerading as a clean audit.
    r = run(["check-env"], env_add={"HALLUCITE_PYTHON": str(TESTS / "no-such-python")})
    C.true(r.returncode != 0 and SENTINEL in r.stderr,
           "REGRESSION GUARD: run.sh fails loud (sentinel) when HALLUCITE_PYTHON is unusable")

    # HAPPY PATH + subcommand dispatch. Point
    # HALLUCITE_PYTHON at it so no venv is provisioned, then check both `check-env` and that an unknown
    # *script* flag is forwarded (proving args reach the underlying script, not swallowed by run.sh).
    if True:
        r = run(["check-env"], env_add={"HALLUCITE_PYTHON": sys.executable})
        C.true(r.returncode == 0 and "HALLUCITE_OK:" in r.stdout,
               "run.sh check-env prints HALLUCITE_OK for a usable Python")
        r = run(["audit", "--this-flag-does-not-exist"],
                env_add={"HALLUCITE_PYTHON": sys.executable})
        C.true(r.returncode != 0 and SENTINEL not in r.stderr
               and "audit_references.py" in (r.stderr + r.stdout),
               "run.sh forwards a subcommand+args to the underlying script (argparse error, "
               "not a bootstrap failure)")
        # The missing-pdftotext preflight warning must stay non-fatal and keep the HALLUCITE_OK
        # contract. pdftotext may exist in find_exe's absolute fallback dirs (Homebrew etc.), so
        # simulate its absence by probing a name that cannot exist anywhere.
        with tempfile.TemporaryDirectory() as td:
            patched = Path(td) / "run.sh"
            patched.write_text(run_sh.read_text().replace(
                "find_exe pdftotext >", "find_exe pdftotext-absent-for-smoke >"))
            r = subprocess.run(["bash", str(patched), "check-env"], capture_output=True,
                               text=True, env={**os.environ, "HALLUCITE_PYTHON": sys.executable})
            C.true(r.returncode == 0 and "HALLUCITE_OK:" in r.stdout
                   and "pdftotext" in r.stderr,
                   "check-env warns on stderr about a missing pdftotext but stays OK (exit 0)")
    else:
        C.skip("no usable Python for the run.sh happy-path checks")


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

    import audit_references as audit
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


def tier3d_duplicate_entries() -> None:
    """Bibliography entries repeated under different citation keys, and how firmly that can be
    called. Where every field matches -- authors, title, venue, volume, pages -- it is one work
    entered twice, because two distinct articles cannot share a venue, volume, and article number;
    the report says so outright. Where only the authors and title match, it is genuinely open
    (an extended version or a preprint can share a title), and the report says that instead.
    Collapsing the two into one hedged category loses the certain case; collapsing them into
    "duplicate" produces bad advice on the open one."""
    print("Tier 3d: repeated bibliography entries, duplicate vs conflicting (no network/DB)")
    import triage

    # The year must be shared and only its disambiguation letter differ -- that is the whole shape
    # under test: distinct citation keys pointing at the same bibliographic data.
    def ref(n, year, title, tail):
        return {"original_number": n, "label": f"Author et al. ({year})",
                "raw_citation": f"Author A, Other B ({year}) {title}. {tail}",
                "parsed": {"title": title}, "db_verification": {"status": "verified"}}

    T1 = "Mining architecture tactics and quality attributes knowledge in stack overflow"
    T2 = "How do users revise architectural related questions on stack overflow: an empirical study"
    JSS, EMSE_A, EMSE_B = ("Journal of Systems and Software 180:111005",
                           "Empirical Software Engineering 30(6):171",
                           "Empirical Software Engineering 30:1-42")
    paper = {"paper_id": "p1", "references": [
        ref(1, "2021a", T1, JSS),
        ref(2, "2021b", T1.replace("stack overflow", "Stack Overflow"), JSS),
        ref(3, "2025c", T2, EMSE_A),
        ref(4, "2025d", T2.replace("architectural", "architec-tural"), EMSE_B),
        ref(5, "2025e", T2, EMSE_B),
        ref(6, "2019", "A completely unrelated study of something else entirely", "Venue 1:1"),
    ]}
    groups = triage.duplicate_groups(paper)
    by = {(g["kind"], tuple(r["original_number"] for r in g["refs"])) for g in groups}

    C.true(("duplicate", (1, 2)) in by,
           "REGRESSION GUARD: entries identical but for capitalization are called duplicates")
    C.true(("duplicate", (4, 5)) in by,
           "REGRESSION GUARD: a line-break hyphen does not stop an all-fields match")
    C.true(("conflict", (3, 4)) in by,
           "REGRESSION GUARD: same title, different pages -> conflicting, not duplicate")
    C.true(not any(6 in nums for _, nums in by), "a unique reference is not grouped")
    C.eq(len(groups), 3, "each distinct finding is reported once")

    # An unparsed reference has no title to compare, and a stub title is not evidence.
    stubs = {"paper_id": "p2", "references": [
        ref(1, "2020a", "Short", "V"), ref(2, "2020b", "Short", "V"),
        {"original_number": 3, "raw_citation": "fragment", "parsed": None,
         "db_verification": {"status": "unparsed"}},
        {"original_number": 4, "raw_citation": "fragment", "parsed": None,
         "db_verification": {"status": "unparsed"}},
    ]}
    C.eq(triage.duplicate_groups(stubs), [],
         "short titles and unparsed references are never grouped")


def tier3e_reference_labels() -> None:
    """How a reference is named in the reports. A numeric bibliography prints "[12]" beside the
    entry, so that number is a real handle. An author-year bibliography prints no numbers at all --
    the handle there is the citation key the body text uses, and the extractor's sequential index
    is a tool-internal artifact. Reporting that index as a reference number sends a reviewer
    hunting the PDF for a "[22]" that was never printed, which is what happened on the paper that
    prompted this."""
    print("Tier 3e: reference labels follow the bibliography style (no network/DB)")
    from audit_references import reference_label
    import triage

    def lab(n, raw, authors, style):
        return reference_label(n, raw, {"authors": authors} if authors else None, style)

    # Numeric: the printed number is the handle.
    r = lab(12, "[12] Bai, Y., Kadavath, S.: A title. Venue (2022)", ["Bai, Y."], "numeric")
    C.eq((r["label"], r["label_kind"]), ("[12]", "printed"), "numeric style keeps the printed [N]")
    C.eq(triage.ref_key({**r, "original_number": 12}), "[12]",
         "a printed number is not repeated as a tool index")

    # Author-year: the citation key, by author count.
    cases = [
        (["de Dieu MJ", "Liang P", "Shahin M", "Khan AA"],
         "de Dieu MJ, Liang P, Shahin M, Khan AA (2025c) How do users revise...",
         "de Dieu et al. (2025c)", "three or more authors -> et al., keeping the year suffix"),
        (["Baldwin CY", "Clark KB"], "Baldwin CY, Clark KB (2000) Design Rules",
         "Baldwin and Clark (2000)", "two authors -> 'A and B'"),
        (["Israel GD"], "Israel GD (1992) Determining sample size",
         "Israel (1992)", "one author -> bare surname"),
        (["Bai, Y.", "Kadavath, S.", "Kundu, S."], "Bai, Y., Kadavath, S., Kundu, S. (2022) T",
         "Bai et al. (2022)", "an APA 'Surname, I.' author still yields the surname"),
    ]
    for authors, raw, want, why in cases:
        got = lab(22, raw, authors, "author-year")
        C.eq((got["label"], got["label_kind"]), (want, "citation"), why)

    # REGRESSION GUARD: the year suffix distinguishes the keys, so near-identical entries stay
    # separately addressable -- exactly the 2021a/2021b and 2025c/d/e case.
    a = lab(7, "Bi T, Liang P (2021a) Mining...", ["Bi T", "Liang P"], "author-year")["label"]
    b = lab(8, "Bi T, Liang P (2021b) Mining...", ["Bi T", "Liang P"], "author-year")["label"]
    C.true(a != b and a.endswith("(2021a)") and b.endswith("(2021b)"),
           "REGRESSION GUARD: the a/b year suffix keeps two similar entries distinguishable")

    # Fallback: nothing to build a key from -> the internal index, marked as such.
    r = lab(40, "garbled text with no parsable year", [], "author-year")
    C.eq((r["label"], r["label_kind"]), ("#40", "internal"),
         "with no author/year the tool-internal index is used")
    C.true("#40" in triage.ref_key({**r, "original_number": 40}),
           "the internal index is shown as #n, never as a bracketed [n]")

    # The reports must say when a number is hallucite's own and not in the paper.
    numeric_paper = {"references": [{"label": "[1]", "label_kind": "printed"}]}
    ay_paper = {"references": [{"label": "Bi et al. (2021a)", "label_kind": "citation"}]}
    C.eq(triage.label_note(numeric_paper), None, "a numbered bibliography needs no note")
    note = triage.label_note(ay_paper) or ""
    C.true("appears nowhere in the paper" in note,
           "REGRESSION GUARD: an unnumbered bibliography gets a note that #n is tool-internal")


def tier3f_degraded_verification() -> None:
    """A "not_found" produced while backends were erroring or rate-limited is not the same claim as
    one from a complete run. Verification short-circuits on the first match, so later backends are
    only ever asked about the residue -- precisely the references that reach triage -- and that is
    where rate limiting lands. On the run that prompted this, all 9 triaged references had at least
    one backend that never answered, and nothing said so."""
    print("Tier 3f: degraded verification is not a clean negative (no network/DB)")
    import triage
    import audit_references as audit

    def ref(status, failed=()):
        return {"original_number": 1, "raw_citation": "R", "parsed": {"title": "T"},
                "db_verification": {"status": status, "failed_dbs": list(failed),
                                    "degraded": bool(failed) and status != "verified"}}

    C.true(not triage.is_degraded(ref("not_found")), "a complete not_found is not degraded")
    C.true(triage.is_degraded(ref("not_found", ["Semantic Scholar"])),
           "REGRESSION GUARD: not_found with a failed backend is marked degraded")
    C.true(not triage.is_degraded(ref("verified", ["Semantic Scholar"])),
           "a verified reference is never degraded (a match settles it)")

    # `degraded` must not disturb the needs-triage contract, which is defined by negation.
    C.true(triage.needs_triage(ref("not_found", ["Semantic Scholar"])),
           "a degraded reference still needs triage")
    C.true(not triage.needs_triage(ref("verified", ["Semantic Scholar"])),
           "INVARIANT: degraded does not turn a verified reference into triage work")

    record = {"references": [ref("verified"), ref("not_found", ["Semantic Scholar"]),
                             ref("mismatch", ["Europe PMC", "Semantic Scholar"])]}
    counts = audit.paper_status_counts(record)
    C.eq(counts["degraded"], 2, "paper_status_counts tallies degraded references")
    C.eq(counts["unverified"], 2, "INVARIANT: the unverified count is unchanged by degradation")
    C.eq(audit.backend_failures(record), {"Semantic Scholar": 2, "Europe PMC": 1},
         "backend_failures counts each backend's silent references")

    # A mismatch's evidence must travel with it: which backend matched what, and with which
    # authors. On the run that prompted this, DBLP matched the right paper but held an incomplete
    # author list, while CrossRef matched an unrelated thesis -- indistinguishable from the
    # worklist until both candidates were visible side by side.
    dv = {"status": "mismatch", "db_results": [
        {"db": "DBLP", "status": "author_mismatch", "paper_url": "https://dblp.org/rec/x",
         "found_authors": ["A One", "B Two"]},
        {"db": "CrossRef", "status": "author_mismatch",
         "paper_url": "https://doi.org/10.0000/thesis", "found_authors": ["A One"]},
        {"db": "PubMed", "status": "no_match", "paper_url": None, "found_authors": []},
        {"db": "Semantic Scholar", "status": "rate_limited", "paper_url": None,
         "found_authors": []},
        {"db": "ACL Anthology", "status": "error", "paper_url": None, "found_authors": []},
    ]}
    matched = triage._matched_records(dv)
    C.eq([m["db"] for m in matched], ["DBLP", "CrossRef"],
         "REGRESSION GUARD: only backends that actually matched something are reported")
    C.eq(matched[0]["found_authors"], ["A One", "B Two"],
         "the matched record's own author list travels with it")
    C.true(all(m["paper_url"] for m in matched),
           "each matched record carries the URL needed to check it")
    C.eq(triage._matched_records({"status": "not_found", "db_results": []}), [],
         "a reference nothing matched reports no matched records")

    # The candidate scorer's normalizer must ignore the cosmetic differences, so a line-break
    # hyphen or casing cannot depress a real match below the keep threshold.
    C.eq(audit._norm_title("Experimen-tation in Software Engineering!"),
         audit._norm_title("Experimentation in software engineering"),
         "candidate title matching ignores hyphenation, case, and punctuation")


def tier3b_triage_concurrency() -> None:
    print("Tier 3b: triage worklist slicing + verdicts locking (no network/DB)")
    import triage

    def paper(pid, nums):
        # The full audit-written contract (see PLAN.md): load_papers treats a JSON without
        # pdf_path/num_references as a stray, not a paper record, and cmd_report reads each
        # reference's "parsed" field unguarded.
        return {"paper_id": pid, "pdf_path": f"{pid}.pdf", "num_references": len(nums),
                "references": [
            {"original_number": n, "raw_citation": f"{pid} cite {n}", "parsed": None,
             "db_verification": {"status": "not_found"}} for n in nums]}

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        # Two paper_ids where one is a prefix of the other -- the paper6 / paper66 trap.
        (out / "p6.json").write_text(json.dumps(paper("esem26-seip-paper6", [3, 4, 5])))
        (out / "p66.json").write_text(json.dumps(paper("esem26-seip-paper66", [1, 2, 7, 10])))

        # A stray JSON that has paper_id+references but not the other audit-written fields is
        # skipped -- previously it passed load_papers and crashed status/report with a KeyError.
        (out / "stray.json").write_text(json.dumps({"paper_id": "stray", "references": []}))
        C.eq({p["paper_id"] for p in triage.load_papers(out)},
             {"esem26-seip-paper6", "esem26-seip-paper66"},
             "REGRESSION GUARD: stray JSON without pdf_path/num_references is skipped")

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
        C.true(rec(out, 3, "unclear", {"title_match": "no"}) != 0,
               "REGRESSION GUARD: unclear with title_match=no is rejected (it asserts the "
               "likely-hallucinated finding while hedging the category)")
        C.eq(rec(out, 4, "real-published"), 0, "real-* without signals is accepted (optional)")
        C.true(rec(out, 99, "real-published") != 0,
               "REGRESSION GUARD: an unknown paper:number is an error, not a silently "
               "unreportable verdict")
        # Grey literature (a web page, not a publication) uses title_match=na and needs no
        # matched_title -- the gate must not block it (the paper82 "Copy for AI" case).
        C.eq(rec(out, 5, "partial-match", {"title_match": "na", "venue_match": "yes"}), 0,
             "partial-match with title_match=na (non-publication resource) is accepted")

    # is_fabrication: a non-existent title (T) is itself the desk-reject trigger -- even with real
    # authors and a real venue otherwise intact (the paper33 case: invented title, real six-author
    # group, real ICSE 2020 association). Requiring a compounding signal would miss exactly this.
    # But only when the CATEGORY asserts fabrication: a hedged verdict must never be escalated
    # past what it claims.
    LH = "likely-hallucinated"
    C.true(triage.is_fabrication({"category": LH, "signals": {"title_match": "no"}}),
           "REGRESSION GUARD: title_match=no alone is a desk-reject candidate (real authors/venue, invented title)")
    C.true(triage.is_fabrication({"category": LH, "signals": {"title_match": "no", "authors_match": "yes", "venue_match": "no"}}),
           "is_fabrication: title_match=no with compounding signals")
    C.true(not triage.is_fabrication({"category": "unclear", "signals": {"title_match": "no"}}),
           "REGRESSION GUARD: a hedged (unclear) verdict never reaches Desk-reject candidates")
    C.true(not triage.is_fabrication({"category": "partial-match",
                                      "signals": {"title_match": "yes", "venue_match": "no"}}),
           "is_fabrication: a real title with a wrong venue is a citation error, not fabrication")
    # A dead/misresolving DOI on a real title is an honest citation error (the off-by-one-digit
    # case), NOT fabrication -- the title, not the DOI, is the decisive signal.
    C.true(not triage.is_fabrication({"category": "partial-match",
                                      "signals": {"title_match": "yes", "doi_status": "404"}}),
           "is_fabrication: a real title with a dead DOI is a citation error, not fabrication")
    C.true(not triage.is_fabrication({"category": "partial-match",
                                      "signals": {"title_match": "na", "venue_match": "no"}}),
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


def tier3h_author_absence() -> None:
    """A reference naming an author the matched publication does not have must reach triage.

    A backend confirms on the title, so a real title with an invented author list was cleared as
    `verified`: a TSE proof cited "Refactoring Test Smells With JUnit 5" -- right venue, volume and
    pages -- under an author list carrying two people who are not on the paper, CrossRef matched
    the title, and it never reached the worklist, the report, or a human.

    The counter-cases matter as much as the catch, and every shape below is one that came out of a
    corpus run rather than out of somebody's head. The rule lives in `dblp_check.authors_match`
    now -- one implementation, shared by every backend -- rather than in a pass the audit ran
    afterwards over whatever a lenient backend had cleared."""
    print("Tier 3h: an absent cited author demotes a verified reference (no network/DB)")
    from dblp_check import authors_match, matched_authors, mirror_authors_complete

    # The catch: two cited names are on no author of the matched work.
    cited = ["Keila L. Lucas", "Elvys S. Soares", "Marcio Ribeiro", "Rohit Gheyi", "Ivan Machado"]
    record = ["Elvys Soares", "Márcio Ribeiro", "Rohit Gheyi", "Guilherme Amaral", "André Santos"]
    C.true(not authors_match(cited, record),
           "REGRESSION GUARD: a cited author absent from the matched work reaches triage")
    C.eq(matched_authors(cited, record), (3, 5),
         "REGRESSION GUARD: and the three that do match are counted, so the near miss a triager "
         "is shown is the record accounting for most of them")

    # Name forms that differ without naming a different person.
    for cited, found, why in (
            (["Dave Binkley"], ["Dave W. Binkley"], "a middle initial in the record"),
            (["Marcio Ribeiro"], ["Márcio Ribeiro"], "diacritics"),
            (["Shekoufeh Kolahdouz-Rahimi"], ["Shekoufeh Kolahdouz Rahimi"], "a hyphenated surname"),
            (["Samuel Binny"], ["Binny M. Samuel"], "swapped given/surname order"),
            (["Marcelo Amorim"], ["Marcelo d'Amorim"], "a compound surname"),
            (["Bart Van Rompaey"], ["Bart Van Rompaey"], "a surname particle"),
            (["Marcelo Amorim"], ["Marcelo d'Amorim"], "an elided particle the citation drops"),
            (["Marcio Ribeiro"], ["Márcio Ribeiro 0001"], "a DBLP homonym suffix"),
            (["A. Przybyłek"], ["Adam Przybylek"], "l with stroke"),
            (["Kåre Synnes"], ["Kare Synnes"], "a ring above"),
            (["Lars Bjørnvig"], ["Lars Bjornvig"], "o with stroke"),
            (["Hans Weiß"], ["Hans Weiss"], "sharp s")):
        C.true(authors_match(cited, found), f"{why} does not demote")

    # Parser artifacts must never be held against a citation: they are skipped, not compared.
    for cited, found, why in (
            (["Hammond Pearce", "Privacy (SP)"], ["Hammond Pearce", "Baleegh Ahmad"],
             "a venue fragment parsed as an author"),
            (["Alberto Bacchelli", "Christian Bird. Expectations, outcomes"],
             ["Alberto Bacchelli", "Christian Bird"], "the sentence after the author list")):
        C.true(authors_match(cited, found), f"{why} does not demote")

    # A citation naming fewer people than the record is what "et al." means.
    C.true(not authors_match(["Anna Amorim"], ["Marcelo d'Amorim"]),
           "REGRESSION GUARD: and dropping the particle widens the surname, not the person")
    C.true(authors_match(["Claes Wohlin"], ["Per Runeson", "Claes Wohlin", "Magnus C. Ohlsson"]),
           "a citation shorter than the record is not an absence")
    # And a record shorter than the citation is only absence where the record is complete.
    C.true(not authors_match(["Patrick Lewis", "Ethan Perez", "Heinrich Küttler"],
                             ["Patrick Lewis", "Ethan Perez"]),
           "REGRESSION GUARD: against a complete record the extra cited name is the signal")
    C.true(authors_match(["Patrick Lewis", "Ethan Perez", "Heinrich Küttler"],
                         ["Patrick Lewis", "Ethan Perez"], record_complete=False),
           "REGRESSION GUARD: and against a record that cannot be complete it is not")

    # Which tier the run is in is decided from the mirror in hand. Hard-coding DBLP out survived
    # the mirror being repaired, and a reference with two invented authors verified again.
    with tempfile.TemporaryDirectory() as td:
        good = f"{td}/good.db"
        con = sqlite3.connect(good)
        con.execute("CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL)")
        con.executemany("INSERT INTO authors (name) VALUES (?)",
                        [("Márcio Ribeiro",)] + [(f"Filler {i}",) for i in range(1200)])
        con.commit()
        con.close()
        C.true(mirror_authors_complete(good),
               "REGRESSION GUARD: a mirror that kept its accented authors gets the strict rule")
        C.true(not mirror_authors_complete(f"{td}/absent.db"),
               "a missing mirror cannot support an absence claim")


def tier3i_dblp_author_encoding() -> None:
    """An offline DBLP mirror that holds no accented author name has a broken ingest, and the audit
    has to say so.

    DBLP is carefully curated and full of accented names, so their total absence is a property of
    the local build, not of DBLP. On a 4.0M-author mirror every such author was missing outright --
    Márcio Ribeiro, Martin Höst, Björn Regnell, Petr Tuma and Jácome Cunha appeared in no record --
    which quietly strips them from the author list of every paper they wrote and makes DBLP
    disagree with correctly cited references. Nothing else surfaces it: counts and titles look
    right."""
    print("Tier 3i: offline DBLP mirror that dropped accented authors (no network)")
    import audit_references as audit

    def build(path, names, n_pubs=0):
        """A mirror holding `names` plus enough filler to pass for a real build."""
        con = sqlite3.connect(path)
        con.executescript(
            "CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);"
            "CREATE TABLE publications (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL,"
            " title TEXT NOT NULL);")
        filler = [(f"Filler Author {i}",) for i in range(audit._DBLP_MIN_AUTHORS)]
        con.executemany("INSERT INTO authors (name) VALUES (?)",
                        [(n,) for n in names] + filler)
        con.executemany("INSERT INTO publications (key, title) VALUES (?, ?)",
                        [(f"conf/x/P{i}", f"Paper {i}") for i in range(n_pubs)])
        con.commit()
        con.close()
        return Path(path)

    with tempfile.TemporaryDirectory() as td:
        broken = build(f"{td}/broken.db",
                       ["Claes Wohlin", "Per Runeson", "Magnus C. Ohlsson", "Elvys Soares"],
                       n_pubs=5)
        healthy = build(f"{td}/healthy.db",
                        ["Claes Wohlin", "Martin Höst", "Björn Regnell", "Márcio Ribeiro"],
                        n_pubs=5)
        C.true(audit._dblp_drops_non_ascii_authors(broken),
               "REGRESSION GUARD: a mirror with no accented author name is reported as broken")
        C.true(not audit._dblp_drops_non_ascii_authors(healthy),
               "a mirror that kept accented names is not reported")
        C.true(not audit._dblp_drops_non_ascii_authors(Path(f"{td}/missing.db")),
               "a missing database is not reported as broken")

        # A failed download leaves a valid, empty database behind, and the ingest exits 0. That
        # is a different fault from a mangled ingest and must not be reported as one -- sending
        # the reader after character entities when the dump never arrived.
        empty = build(f"{td}/empty.db", [], n_pubs=0)
        con = sqlite3.connect(f"{td}/empty.db")
        con.execute("DELETE FROM authors")
        con.commit()
        con.close()
        C.eq(audit._dblp_publication_count(empty), 0, "an empty mirror reports 0 publications")
        C.true(not audit._dblp_drops_non_ascii_authors(empty),
               "REGRESSION GUARD: an empty mirror is not misreported as having dropped authors")
        C.eq(audit._dblp_publication_count(Path(f"{td}/missing.db")), None,
             "a missing database has no publication count")


def tier3j_residue_evidence() -> None:
    """Three things the audit knew about an unverified reference and threw away before they reached
    a human: which backends were never asked (123 of the 788 corpus residue references had never
    been put to the mirror, and read as a clean `not_found`), what a cited identifier resolved to
    (5 dead DOIs and 57 identifiers naming another title in the same residue), and the mirror's
    nearest title where it holds no record of the cited one (32 leads over the corpus, every one
    the cited work, once the record had to carry every cited author)."""
    print("Tier 3j: the evidence the audit already has reaches the triager (no network)")
    import types
    import triage
    import audit_references as audit
    from verifier import Reference

    def ref(n, status, rows, parsed=None, extra=None):
        dv = {"status": status, "failed_dbs": [],
              "db_results": [{"db": db, "status": st} for db, st in rows]}
        dv.update(extra or {})
        return {"original_number": n, "raw_citation": f"Author A. Title {n}. Venue, 2020.",
                "db_verification": dv,
                "parsed": parsed or {"title": f"Title {n}", "authors": ["Author A"]}}

    # Not asked. `skipped` is the verifier's word for it, and the one string that means it.
    short = ref(1, "not_found", [("DBLP", "skipped"), ("CrossRef", "no_match"), ("DOI", "skipped"),
                                 ("arXiv", "skipped"), ("Semantic Scholar", "skipped")],
                parsed={"title": "Random Forests", "authors": ["Leo Breiman"]})
    asked = ref(2, "not_found", [("DBLP", "no_match"), ("CrossRef", "no_match"), ("DOI", "error")])
    C.eq(triage.skipped_dbs(short), ["DBLP", "DOI", "arXiv", "Semantic Scholar"],
         "REGRESSION GUARD: every backend that was never asked is named, the mirror first")
    C.eq(triage.skipped_dbs(asked), [],
         "a backend that answered, or failed to answer, was asked")
    for status in ("timeout", "error", "rate_limited", "no_match", "author_mismatch", "match",
                   "not_applicable"):
        C.eq(triage.skipped_dbs({"db_verification": {"db_results": [{"db": "X", "status": status}]}}),
             [], f"a backend row of {status!r} is not 'never asked'")

    # What the identifier resolved to: dead, another title, the cited title, nothing known.
    dead = ref(3, "not_found", [("DOI", "no_match")],
               parsed={"title": "A paper with a dead DOI", "authors": ["Ada Byte"],
                       "doi": "10.1000/dead"},
               extra={"doi_info": {"doi": "10.1000/dead", "valid": False, "title": None}})
    other = ref(4, "not_found", [("DOI", "no_match")],
                parsed={"title": "The title the citation gives", "authors": ["Ada Byte"],
                        "doi": "10.1000/other"},
                extra={"doi_info": {"doi": "10.1000/other", "valid": True,
                                    "title": "An unrelated work the DOI really names"}})
    same = ref(5, "mismatch", [("arXiv", "author_mismatch")],
               parsed={"title": "Modeling library popu-larity within a software ecosystem",
                       "authors": ["Ada Byte"], "arxiv_id": "2407.08138"},
               extra={"arxiv_info": {"arxiv_id": "2407.08138", "valid": True,
                                     "title": "Modeling Library Popularity Within a Software "
                                              "Ecosystem"}})
    none = ref(6, "not_found", [("DOI", "skipped")])
    C.eq(triage.identifier_evidence(dead),
         [{"kind": "doi", "id": "10.1000/dead", "resolves": False, "title": None,
           "cited_title": None}],
         "REGRESSION GUARD: a dead identifier is reported as one -- fabrication signal (D)")
    C.eq([(e["resolves"], e["cited_title"]) for e in triage.identifier_evidence(other)],
         [(True, False)],
         "REGRESSION GUARD: an identifier naming another work is reported as resolving to a "
         "different title -- the opposite verdict from a dead one")
    C.eq([(e["kind"], e["cited_title"]) for e in triage.identifier_evidence(same)],
         [("arxiv", True)],
         "a resolved title that differs only in case and a line-break hyphen is the cited title")
    C.eq(triage.identifier_evidence(none), [], "no identifier, nothing claimed")

    # Through the worklist, the report and the verification sheet, which is where a triager reads.
    near = {"key": "conf/x/Near20", "title": "A Near Title With One Extra Word",
            "authors": ["Author A"], "edits": 1, "year": 2020, "venue": "X"}
    lead = ref(7, "not_found", [("DBLP", "no_match")], extra={"dblp_nearest": near})
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        refs = [short, asked, dead, other, same, none, lead]
        (out / "p.json").write_text(json.dumps(
            {"paper_id": "p", "pdf_path": "p.pdf", "num_references": len(refs),
             "references": refs}))
        triage.cmd_worklist(out)
        wl = {e["number"]: e for e in json.loads((out / "triage_worklist.json").read_text())}
        C.eq(wl[1]["skipped_dbs"], ["DBLP", "DOI", "arXiv", "Semantic Scholar"],
             "REGRESSION GUARD: the worklist entry says which backends never asked")
        C.eq(wl[2]["skipped_dbs"], [], "and says nothing where every backend was asked")
        C.eq([e["resolves"] for e in wl[3]["identifiers"]], [False],
             "the worklist entry carries the dead identifier")
        C.eq((wl[4]["identifiers"][0]["cited_title"], wl[5]["identifiers"][0]["cited_title"]),
             (False, True), "and whether each resolved title is the cited one")
        C.eq(wl[7]["dblp_nearest"], near,
             "REGRESSION GUARD: the mirror's nearest title travels with the entry")
        triage.cmd_record(out, "p", "1", "unclear", "the mirror was never asked")
        triage.cmd_record(out, "p", "4", "unclear", "the DOI names another work")
        triage.cmd_report(out)
        check = (out / "reports" / "reference-check-p.md").read_text()
        sheet = (out / "reports" / "verify-p.md").read_text()
        C.true("- Not asked: DBLP, DOI, arXiv, Semantic Scholar" in check,
               "REGRESSION GUARD: the per-paper report says the mirror was never asked")
        C.true("- DOI 10.1000/dead does not resolve" in check,
               "the report names a dead identifier")
        C.true("- DOI 10.1000/other resolves to a different title: An unrelated work the DOI "
               "really names" in check,
               "REGRESSION GUARD: the report shows the title an identifier really names")
        C.true("- arXiv 2407.08138 resolves to the cited title" in check,
               "the report says when an identifier confirms the cited title")
        C.true("- Nearest DBLP title, 1 word edit away, with every cited author on it "
               "(`conf/x/Near20`): A Near Title With One Extra Word -- year=2020, venue=X"
               in check,
               "REGRESSION GUARD: the report offers the mirror's nearest title as a lead")
        C.true("- Not asked: DBLP" in sheet and "resolves to a different title" in sheet,
               "the verification sheet carries the same evidence")

    # The nearest title, through the function the audit calls, on a fixture mirror.
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "dblp.db"
        _build_fixture_db(db)

        def entry(title, authors):
            return types.SimpleNamespace(reference=Reference(title=title, authors=authors))

        def dv(status="not_found", dblp="no_match"):
            return {"status": status, "db_results": [{"db": "DBLP", "status": dblp}]}

        near_title = "A study of synthetic widgets in distributed environments"
        entries = [entry(near_title, ["Alice Anderson", "Bob Brown"]),
                   entry(near_title, ["Alice Anderson", "Mallory Fake"]),
                   entry(near_title, ["Alice Anderson"]),
                   entry("Patterns of imaginary data in testing frameworks", ["Frank Foster"]),
                   entry(near_title, ["Alice Anderson", "Bob Brown"]),
                   entry("A study of synthetic widgets in distributed systems",
                         ["Alice Anderson", "Mallory Fake"]),
                   entry(near_title, ["Alice Anderson", "Bob Brown"])]
        vs = [dv(), dv(), dv(), dv(), dv(dblp="skipped"), dv("mismatch", "author_mismatch"),
              dv("verified", "match")]
        audit.attach_mirror_evidence(str(db), entries, vs)
        C.eq((vs[0].get("dblp_nearest") or {}).get("key"), "conf/ic/AndersonB20",
             "REGRESSION GUARD: a title one word off, under every cited author, is offered")
        C.eq((vs[0].get("dblp_nearest") or {}).get("edits"), 1,
             "with how far off it is")
        C.eq(vs[0]["dblp_nearest"]["authors"], ["Alice Anderson", "Bob Brown"],
             "and the record's own author list")
        C.true("dblp_nearest" not in vs[1],
               "REGRESSION GUARD: a cited person the near record does not carry withholds it -- "
               "ungated, half the corpus hits were different works")
        C.eq((vs[2].get("dblp_nearest") or {}).get("key"), "conf/ic/AndersonB20",
             "a citation naming fewer authors than the record still has every cited person on it")
        C.true("dblp_nearest" not in vs[3],
               "REGRESSION GUARD: three word edits is a different title, and is not offered")
        C.true("dblp_nearest" not in vs[4],
               "REGRESSION GUARD: a title the mirror was never asked about gets no near miss")
        C.true("dblp_nearest" not in vs[5],
               "a title the mirror found under other authors gets no near miss -- the record it "
               "found travels as `matched`")
        C.true("dblp_nearest" not in vs[6] and "dblp_record" not in vs[6],
               "a verified reference gets no evidence attached")


def tier3k_authors_absent() -> None:
    """`authors_absent` was read by triage and written by nothing since the cutover: the audit pass
    that filled it is gone, and a `mismatch` carries the matched record's authors instead. The
    field is now derived from that record -- the cited names no author of it accounts for, under
    the same pairing that refused the citation -- and travels with the worklist entry, the
    per-paper report and the verification sheet."""
    print("Tier 3k: the cited authors the matched record does not account for (no network)")
    import triage
    from dblp_check import absent_authors

    cited = ["Keila L. Lucas", "Elvys S. Soares", "Marcio Ribeiro", "Rohit Gheyi", "Ivan Machado"]
    record = ["Elvys Soares", "Márcio Ribeiro", "Rohit Gheyi", "Guilherme Amaral", "André Santos"]
    C.eq(absent_authors(cited, record), ["Keila L. Lucas", "Ivan Machado"],
         "REGRESSION GUARD: the two cited people on no author of the matched work are named, in "
         "the citation's order")
    C.eq(absent_authors(["Dave Binkley", "A. Przybyłek", "Marcelo Amorim", "Emiliano De Cristofaro"],
                        ["Dave W. Binkley", "Adam Przybylek", "Marcelo d'Amorim", "Cristofaro, E."]),
         [], "a middle initial, a stroke, an elided particle and a particle on one side are not "
             "absences")
    C.eq(absent_authors(["J. Smith"], ["Alice Smith"]), ["J. Smith"],
         "REGRESSION GUARD: a contradicted given initial is an absence")
    C.eq(absent_authors(["Hammond Pearce", "Privacy (SP)", "et al."], ["Hammond Pearce", "Baleegh Ahmad"]),
         [], "venue text and an et al. are not people, so they are never reported absent")

    def ref(n, status, authors, found=None, source=None):
        dv = {"status": status, "failed_dbs": [], "source": source,
              "found_authors": list(found or []),
              "db_results": [{"db": "DBLP", "status": {"verified": "match", "mismatch":
                              "author_mismatch"}.get(status, "no_match"),
                              "found_authors": list(found or []),
                              "paper_url": "https://dblp.org/rec/x/y" if found else None}]}
        return {"original_number": n, "raw_citation": f"Someone. Title {n}. Venue, 2020.",
                "db_verification": dv, "parsed": {"title": f"Title {n}", "authors": authors}}

    mismatch = ref(1, "mismatch", cited, record, "DBLP")
    verified = ref(2, "verified", ["Claes Wohlin", "Per Runeson"], ["Claes Wohlin", "Per Runeson"],
                   "DBLP")
    missing = ref(3, "not_found", ["Ada Byte"])
    C.eq(triage.authors_absent(mismatch), ["Keila L. Lucas", "Ivan Machado"],
         "REGRESSION GUARD: derived from the record the verdict rests on")
    C.eq(triage.authors_absent(verified), [], "a verified reference has no absent author to report")
    C.eq(triage.authors_absent(missing), [], "and neither has one no backend found a record for")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        refs = [mismatch, verified, missing]
        (out / "p.json").write_text(json.dumps(
            {"paper_id": "p", "pdf_path": "p.pdf", "num_references": len(refs),
             "references": refs}))
        triage.cmd_worklist(out)
        wl = {e["number"]: e for e in json.loads((out / "triage_worklist.json").read_text())}
        C.eq(wl[1]["authors_absent"], ["Keila L. Lucas", "Ivan Machado"],
             "REGRESSION GUARD: the worklist entry names the absent authors")
        C.eq(wl[3]["authors_absent"], [], "and names none where no record was matched")
        triage.cmd_record(out, "p", "1", "unclear", "two cited authors are not on the paper")
        triage.cmd_report(out)
        line = "- Cited author(s) no author of the matched record accounts for: Keila L. Lucas, Ivan Machado"
        check = (out / "reports" / "reference-check-p.md").read_text()
        sheet = (out / "reports" / "verify-p.md").read_text()
        C.true(line in check, "REGRESSION GUARD: the per-paper report names the absent authors")
        C.true(line in sheet, "and so does the verification sheet")


def tier3g_stale_verdicts() -> None:
    """A verdict is keyed by paper_id:number, but author-year numbers are extraction-order: a
    re-audit can renumber the bibliography and leave a verdict pointing at a different reference.
    Every consumer must then treat that reference as un-triaged. The alternative -- reattaching
    the old category -- printed a likely-hallucinated banner (with the desk-reject fabrication
    line) against an innocent reference in every written report, while the actually-fabricated
    one silently reverted to pending."""
    print("Tier 3g: stale verdicts are quarantined, not reattached (no network/DB)")
    import triage
    triage_py = SCRIPTS / "triage.py"

    def paper(refs):
        return {"paper_id": "p", "pdf_path": "p.pdf", "num_references": len(refs),
                "references": refs}

    def ref(n, title):
        return {"original_number": n, "raw_citation": f"Author A. {title}. Venue, 2020.",
                "db_verification": {"status": "not_found"}, "parsed": {"title": title}}

    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "p.json").write_text(json.dumps(paper([ref(1, "Innocent paper one"),
                                                      ref(2, "Fabricated title")])))
        r = subprocess.run([sys.executable, str(triage_py), "record", "p", "2",
                            "likely-hallucinated", "no publication bears this title",
                            "--signals", '{"title_match":"no"}', "--out", str(out)],
                           capture_output=True, text=True)
        C.eq(r.returncode, 0, "verdict records against the original reference")

        # Re-audit: numbering shifts, so #2 is now a different, real reference.
        (out / "p.json").write_text(json.dumps(paper([ref(1, "A new first entry"),
                                                      ref(2, "Innocent paper one"),
                                                      ref(3, "Fabricated title")])))
        triage.cmd_report(out)
        rollup = (out / "reports" / "potential-hallucinations.md").read_text()
        check = (out / "reports" / "reference-check-p.md").read_text()
        C.true("Innocent paper one" not in rollup,
               "REGRESSION GUARD: a stale verdict does not flag the reference now holding its number")
        C.true(not (out / "reports" / "verify-p.md").exists(),
               "no verify sheet is generated from a stale verdict alone")
        C.true("Stale verdict" in check and "(pending)" in check,
               "the per-paper report marks the verdict stale and the reference pending")

        triage.cmd_worklist(out, pending=True)
        wl = json.loads((out / "triage_worklist.json").read_text())
        C.eq(sorted(e["number"] for e in wl), [1, 2, 3],
             "REGRESSION GUARD: --pending resurfaces a reference whose verdict went stale")


def _build_fixture_db(path: Path) -> None:
    """A few-KB DBLP DB matching the mirror's schema (4 tables + an FTS5 index).
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
        # Couple the two stages' schemas: the audit's real output must pass Stage 3's paper-record
        # test, so a field rename in audit_references.py cannot silently empty load_papers.
        import triage
        C.eq([p["paper_id"] for p in triage.load_papers(out)], [pdf.stem],
             "load_papers accepts the audit's real output (Stage 1+2 -> Stage 3 contract)")
        st = {x["original_number"]: (x.get("db_verification") or {}).get("status")
              for x in rec["references"]}
        C.eq(st.get(1), "verified", "ref [1] verified (exact DBLP match)")
        C.eq(st.get(4), "verified", "ref [4] verified (exact DBLP match)")
        C.eq(st.get(3), "not_found", "ref [3] not_found (absent from DBLP)")
        C.eq(sum(1 for s in st.values() if s == "verified"), 2, "exactly 2 verified")


def tier4d_dblp_second_opinion() -> None:
    """The offline DBLP check, which decides most of hallucite's confirmations and is the first
    backend its verifier asks.

    A cited title that several publications share -- "Experimentation in Software Engineering" is a
    book, a 1986 TSE article and four other works -- has to be judged against all of them, not
    against whichever an FTS query ranks first. The decision then has to stay strict in one
    direction and lenient in the other: a citation may name fewer authors than the record, which is
    what "et al." means, and may not name more, which is the fabrication this tool exists to
    catch."""
    print("Tier 4d: offline DBLP title+author check over all same-title records (no network)")
    import dblp_check as D

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "dblp.db"
        con = sqlite3.connect(str(db))
        c = con.cursor()
        c.executescript("""
            CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
            CREATE TABLE publication_authors (pub_id INTEGER NOT NULL, author_id INTEGER NOT NULL,
                PRIMARY KEY (pub_id, author_id));
            CREATE TABLE publications (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, title TEXT NOT NULL);
            CREATE VIRTUAL TABLE publications_fts USING fts5(title, content='publications', content_rowid='id');
        """)
        pubs = [
            (1, "journals/x/First86", "A shared placeholder title about fictional pipelines",
             ["Alpha Aaron", "Beta Brown"]),
            # Same title, different punctuation/case; author rows truncated (as the real DB's are).
            (2, "books/x/Second12", "A Shared Placeholder Title: About Fictional Pipelines",
             ["Carla Chen", "Magnus D. Delta"]),
            (3, "conf/x/Solo92", "Determining fictional sample sizes properly", ["Golf D. Hotel"]),
            # A word the record's own title carries split, an edition suffix in each shape DBLP
            # writes, and an alias in parentheses.
            (4, "conf/x/Split24", "Improving Fictional Clone Detection U sing Equivalent Methods",
             ["India Juliet", "Kilo Lima"]),
            (5, "books/x/Book75", "The fictional man-month - essays on placeholder engineering (2. ed.)",
             ["Mike November"]),
            (6, "books/x/Book11", "Fictional mining: practical placeholder tools and techniques, 3rd Edition",
             ["Oscar Papa", "Quebec Romeo"]),
            (7, "journals/x/Alias23", "Study the placeholder correlation of fictional readme files",
             ["Tango (Tom) Uniform", "Victor Whiskey"]),
            (8, "conf/x/Glued20", "A C/C++ fictional vulnerability dataset with placeholder changes",
             ["Xray Yankee", "Zulu Alpha"]),
            # A record DBLP truncated, and one credited to a group rather than to people.
            (9, "journals/x/Trunc24", "A placeholder model for fictional code at very large scale",
             ["Bravo Charlie", "Delta Echo", "et al."]),
            (10, "journals/x/Group23", "A fictional technical report on placeholder models",
             ["PlaceholderAI"]),
        ]
        aid: dict[str, int] = {}
        for pid, key, title, authors in pubs:
            c.execute("INSERT INTO publications(id,key,title) VALUES(?,?,?)", (pid, key, title))
            for a in authors:
                if a not in aid:
                    c.execute("INSERT INTO authors(name) VALUES(?)", (a,))
                    aid[a] = c.lastrowid
                c.execute("INSERT INTO publication_authors(pub_id,author_id) VALUES(?,?)",
                          (pid, aid[a]))
        c.execute("INSERT INTO publications_fts(publications_fts) VALUES('rebuild')")
        con.commit()
        con.close()
        db = str(db)

        # The collision: the cited authors belong to the SECOND same-title record; the cited
        # title carries a line-break hyphen and different casing on top.
        m = D.second_opinion(db, "A shared placeholder ti-tle about fictional pipelines",
                             ["Chen C", "Delta MD"])
        C.true(m is not None and m.key == "books/x/Second12",
               "REGRESSION GUARD: the right same-title candidate matches, not the first FTS hit")
        C.true(D.second_opinion(db, "A shared placeholder title about fictional pipelines",
                                ["Fake F", "Invented I"]) is None,
               "wrong authors on a real title stay unverified")
        C.true(D.second_opinion(db, "A wholly invented title never stored anywhere",
                                ["Alpha Aaron"]) is None,
               "an invented title stays unverified")
        C.true(D.second_opinion(db, "A shared placeholder title about fictional pipelines",
                                ["Alpha Aaron", "Fake F", "Made M", "Up U"]) is None,
               "REGRESSION GUARD: a padded author list is refuted, not rescued by one real name")
        # The phantom-author pattern: the record's own authors, correct and complete, with one
        # invented name spliced in. Every other field of such a citation is right, so this rule is
        # the only thing standing between it and a clean verification.
        C.true(D.second_opinion(db, "A shared placeholder title about fictional pipelines",
                                ["Carla Chen", "Magnus D. Delta", "Quentin Fabrikant"]) is None,
               "REGRESSION GUARD: one invented name appended to a correct author list refutes")
        C.true(D.second_opinion(db, "A shared placeholder title about fictional pipelines",
                                ["Carla Chen"]) is not None,
               "a citation naming one of the record's authors is a truncation, not a disagreement")
        s = D.second_opinion(db, "Determining fictional sample sizes properly", ["Hotel GD"])
        C.true(s is not None and s.key == "conf/x/Solo92",
               "a single-author work matches on its one comparable author")
        C.true(D.second_opinion(db, "A shared placeholder title about fictional pipelines",
                                []) is None,
               "no cited authors, no clearance -- the check never verifies on title alone")
        C.true(D.second_opinion(db, "A shared placeholder title about fictional pipelines",
                                ["Proceedings of the Workshop (WS)"]) is None,
               "venue text parsed as an author is not a person, so it clears nothing")
        C.true(D.second_opinion(db, "A shared placeholder title about: fictional pipelines",
                                ["Carla Chen", "Magnus D. Delta"]) is not None,
               "punctuation and spacing do not make two spellings of a title different")

        # Retrieval catching up with the decision: `titles_match` never saw these differences,
        # and the record was there to be found the whole time.
        for cited, key, why in (
                ("Improving fictional clone detection using equivalent methods", "conf/x/Split24",
                 "a word split inside the record's own title"),
                ("A C/C++ fictional vulnera bility dataset with placeholder changes", "conf/x/Glued20",
                 "a word split in the citation with both halves longer than a fragment"),
                ("Ac/c++ fictional vulnerability dataset with placeholder changes", "conf/x/Glued20",
                 "an article the layout glued to its neighbour"),
                ("The fictional man-month: essays on placeholder engineering", "books/x/Book75",
                 "an edition suffix the record writes as \"(2. ed.)\""),
                ("Fictional mining: practical placeholder tools and techniques", "books/x/Book11",
                 "an edition suffix the record writes as \", 3rd Edition\""),
                ("Study the placeholder correlation of fictional readme files", "journals/x/Alias23",
                 "an alias the record writes in parentheses")):
            authors = {"conf/x/Split24": ["India Juliet", "Kilo Lima"],
                       "conf/x/Glued20": ["Xray Yankee", "Zulu Alpha"],
                       "books/x/Book75": ["Mike November"],
                       "books/x/Book11": ["Oscar Papa", "Quebec Romeo"],
                       "journals/x/Alias23": ["Tango Tom Uniform", "Victor Whiskey"]}[key]
            got = D.second_opinion(db, cited, authors)
            C.true(got is not None and got.key == key, f"REGRESSION GUARD: {why} is retrieved")
        C.true(D.second_opinion(db, "The fictional man-month: essays on placeholder engineering",
                                ["Mike November", "Papa Invented"]) is None,
               "the wider retrieval does not loosen the decision: a padded list still refutes")
        C.true(D.second_opinion(db, "Improving fictional clone detection using equivalent techniques",
                                ["India Juliet", "Kilo Lima"]) is None,
               "and a title differing in a content word is still not the record")
        C.eq(D._MAX_DROPPED, 12, "the leave-a-pair-out fallback is bounded")

        # The lenient tier is for a record that cannot refute, and it is not a wildcard: the
        # people a truncated record does list still have to account for at least one cited name.
        trunc = "A placeholder model for fictional code at very large scale"
        C.true(D.second_opinion(db, trunc, ["Bravo Charlie", "Foxtrot Golf", "et al."]) is not None,
               "a truncated record clears a citation whose unmatched name it may simply not carry")
        C.true(D.second_opinion(db, trunc, ["Mallory Fake", "Trent Nobody"]) is None,
               "REGRESSION GUARD: a truncated record does not clear a citation that pairs with "
               "none of the people it lists")
        C.true(D.second_opinion(db, "A fictional technical report on placeholder models",
                                ["Hotel India", "Juliet Kilo"]) is not None,
               "a group byline has no person to pair against and still clears on the title")

    # Name comparison, on the cases VERIFICATION-SPEC.md names. A middle initial or a particle the
    # other side does not carry is tolerated; a contradicted given name is not.
    for cited, stored, want, why in (
            ("Mohammed F Kharma", "Mohammed Kharma", True, "a middle initial the record lacks"),
            ("C. E. Jimenez", "Carlos Jimenez", True, "a middle initial beside an initialled given name"),
            ("Emiliano De Cristofaro", "Cristofaro, E.", True, "a particle on one side only"),
            ("Frederick P. Brooks Jr.", "Frederick P. Brooks", True, "a generational suffix"),
            ("Kolahdouz-Rahimi", "Shekoufeh Kolahdouz Rahimi", True, "a hyphen written as a space"),
            ("J. Smith", "Alice Smith", False, "a contradicted given initial"),
            ("A. E. Jimenez", "Carlos Jimenez", False, "a wrong given initial beside a middle one"),
            ("Wei Wang", "Wei Zhang", False, "a shared given name and a different surname"),
            ("Eric O\u2019Donoghue", "Eric O'Donoghue", True, "a curly apostrophe against a straight one"),
            ("Eric O'Brien", "Eric O'Donoghue", False, "two different surnames that share a particle"),
            ("O. LeBenich", "Olaf Le\u00dfenich", True, "an eszett the PDF rendered as a capital B"),
            ("JetBrains Team", "Jane Brains", False, "a name that really carries a capital B")):
        C.eq(D._author_matches(cited, stored), want, f"{cited!r} vs {stored!r}: {why}")
    C.eq(D.matched_authors(["Xin Xia", "Xin Xiao"], ["Xin Xiao", "Xin Xia 0001"]), (2, 2),
         "REGRESSION GUARD: author lists are paired to a maximum, not first-fit")


def tier4b_extraction_lineno() -> None:
    """Regression for a real paper (a bracket-numeric bibliography under LaTeX `lineno` margin
    numbers, spanning a page break that resets the margin count) that extraction once mangled:
    plain numeric segmentation locked onto the margin numbers instead of the "[N]" labels, dropped
    the first entry, and collapsed every reference after the page reset into one segment. These
    lines reproduce that layout with invented authors/titles -- the `pdftotext -layout` shape after
    the section header, margin numbers and all. No network, DB, or poppler.

    Failure shape this guards against: 10 references, numbered [1]..[10], must each segment; the
    margin numbers (single- and multi-digit, some standalone, and a per-page reset between [5] and
    [6]) must not become entry numbers, drop [1], or merge the tail into one blob."""
    print("Tier 4b: bracket-numeric extraction under lineno margins (no network/DB)")
    import pdf_references as R

    # As `_references_section` returns it: margin numbers retained (their inconsistent rendering
    # defeats line-number stripping), entries are "[N]", margins reset to 1 between [5] and [6].
    section = [
        " 1",
        " 2",
        "     [1]    Anna Apple and Ben Berry. Toward effective adoption of placeholder practices.",
        " 3",
        "            A trailing title fragment with no margin number.",
        " 4   [2]    Carla Cherry and Dan Date. 2014. Foundations of fictional static analysis tools.",
        " 5          J. Imaginary Tooling 10, 2 (2014), 93–98. DOI:https://doi.org/10.0000/fake.2014.1",
        " 6   [3]    Erin Elder. 2021. A study of nonexistent program repair effectiveness.",
        " 7          Imaginary Softw. Eng. 26, 5 (2021). DOI:https://doi.org/10.0000/fake.2021.2",
        " 8   [4]    Fred Fig and Gail Gold. 2018. Security in the fictional development lifecycle. (2018).",
        " 9   [5]    Hugo Hill, Iris Ash, and Jo Kemp. 2023. Placeholder DevSecOps tools and monitoring.",
        "10          Proc. Imaginary Conf. (2023), 201–205. DOI:https://doi.org/10.0000/fake.2023.3",
        "11",
        "     [6]    Karl Knot, Lena Lime, and Mona Moss. Invented coding for web apps and the role of models.",
        " 1          A continuation line that opens with a reset margin number.",
        " 2   [7]    Nora Nest, Otto Oak, Paul Pine, and Quinn Reed. 2009. Imaginary literature reviews.",
        " 3          Inf. Softw. Tech. 51, 1 (2009), 7–15. DOI:https://doi.org/10.0000/fake.2009.4",
        " 4   [8]    Rita Rose. 2025. A placeholder report on insecure code. Retrieved from https://e.invalid/x",
        " 5   [9]    Sam Stone, Tia Vale, and Uma Wood. 2020. Can this fault be found: a study on detection.",
        " 6          J. Imaginary Softw. 170 (2020), 110769. DOI:https://doi.org/10.0000/fake.2020.5",
        " 7   [10]   Vic Wren. 2023. The last fictional reference, with no trailing content.",
        " 8",
    ]

    style = R._dominant_style(section)
    C.eq(style, "bracket-numeric", "lineno bracket-numeric bibliography detected as bracket-numeric")

    segs = R._segment(section, style)
    nums = [n for n, _, _ in segs]
    text = {n: t for n, t, _ in segs}
    C.eq(nums, list(range(1, 11)),
         "REGRESSION GUARD: entries segment as [1]..[10] (no margin hijack, no dropped [1], no collapse)")
    C.true(1 in text and text[1].startswith("Anna Apple"),
           "ref [1] is recovered (was dropped when margin numbers anchored the sequence)")
    C.true(6 in text and "Invented coding for web apps" in text[6]
           and "Imaginary literature reviews" not in text[6],
           "REGRESSION GUARD: the post-reset entry [6] does not swallow [7]..[10]")
    # Margin numbers must not bleed into the joined text: [7]'s venue continuation had a "3" gutter
    # number, [6]'s had a reset "1"; neither should survive, and no standalone margin line either.
    C.true(7 in text and "Inf. Softw. Tech. 51" in text[7] and "3 Inf. Softw." not in text[7],
           "a continuation's gutter margin number is stripped before joining")
    C.true(6 in text and "1 A continuation line" not in text[6]
           and "A continuation line" in text[6],
           "a reset margin number on a continuation line is stripped, the content kept")

    # A plain-numeric bibliography (no bracket labels) must stay numeric, not be pulled into the
    # new style by a stray bracket.
    plain = [
        "1. Xavier Xu. 2019. A numeric-style entry without brackets. Venue (2019).",
        "2. Yara Young. 2020. Another numeric entry [see 1]. Venue (2020).",
        "3. Zack Zeal. 2021. A third numeric entry. Venue (2021).",
    ]
    C.eq(R._dominant_style(plain), "numeric",
         "a plain numeric bibliography is not misclassified as bracket-numeric")

    # Soft line-break hyphens: the raw text keeps the hyphen (right for a compound broken at its
    # own hyphen), and the alt variant drops it (right for a soft-hyphenated word) -- FTS phrase
    # lookups miss the wrong form, which sent real, DBLP-indexed works into triage as not_found.
    soft = [
        "1. Alice Author. 2019. Benchmarking experimen-",
        "   tation in fictional software tools. Venue (2019).",
        "2. Bob Builder. 2020. A second fictional entry. Venue (2020).",
        "3. Carol Coder. 2021. A third fictional entry. Venue (2021).",
    ]
    ssegs = R._segment(soft, "numeric")
    C.true(bool(ssegs) and "experimen-tation" in ssegs[0][1],
           "a line-break hyphen join keeps the hyphen in the raw text")
    C.true(ssegs[0][2] is not None and "experimentation in fictional" in ssegs[0][2],
           "REGRESSION GUARD: the dehyphenated alt variant is offered for verification retry")
    C.true(ssegs[1][2] is None, "an entry with no soft join carries no alt variant")

    # A running head that appears only ONCE inside the section (any two-page bibliography) must
    # still be dropped when the document shows it repeating on other pages -- section-only
    # counting glued the citing paper's own running head into a reference's title.
    head = "     Placeholder Study of Imaginary Systems                                   31"
    sec2 = [
        "1. Dana Dev. 2018. First fictional entry. Venue (2018).",
        head,
        "2. Ed Eng. 2019. Second fictional entry. Venue (2019).",
        "3. Fay Fix. 2020. Third fictional entry. Venue (2020).",
    ]
    doc = ["intro text"] + [head.replace("31", str(pg)) for pg in (27, 29)] + sec2
    joined = " ".join(t for _, t, _ in R._segment(sec2, "numeric", doc))
    C.true("Placeholder Study" not in joined,
           "REGRESSION GUARD: a head seen once in the section is dropped via the document-wide count")

    # A short number alone on a line at a continuation indent is content (a wrapped page number),
    # not a lineno margin number -- blanking it silently truncated the citation it belonged to.
    lineno_doc = []
    for i in range(1, 40):
        lineno_doc += [f"{i:>2}", "     Some body text line that carries the actual content."]
    lineno_doc += ["40", "       654"]
    stripped, on = R._strip_line_numbers(lineno_doc)
    C.true(on, "margin numbers are detected in the synthetic lineno document")
    C.true(any(l.strip() == "654" for l in stripped),
           "REGRESSION GUARD: a wrapped page number at a continuation indent survives blanking")
    C.true(not any(l.strip() == "40" for l in stripped),
           "a true margin number at the margin column is still blanked")

    # Two "(year)" author-blocks in one author-year segment is the shape of a silent merge (an
    # entry whose year wrapped onto the next line, glued into its predecessor); it must surface
    # as a suspect so the audit can warn that the second entry was never verified on its own.
    merged = [R.ExtractedRef(1, "Anderson K (2019) First entry. Venue. "
                                "Carter M (2020) Second entry. Venue.", None),
              R.ExtractedRef(2, "Lewis V (2021) Third entry. Venue.", None)]
    C.eq(R._suspect_merges(merged, "author-year"), [1],
         "REGRESSION GUARD: a two-year author-year segment is flagged as a suspected merge")
    C.eq(R._suspect_merges(merged, "numeric"), [],
         "numeric styles are never merge-suspects (their labels delimit entries)")


def tier4e_smallcaps_heading() -> None:
    """Regression for an IEEE-style journal proof whose section headings are set in small caps with
    a full-size initial: `pdftotext` renders the size change as a space, so "REFERENCES" arrives as
    "R EFERENCES". Matching the heading text exactly missed it, `_references_section` returned
    nothing, and the audit reported 0 references for a paper with a 32-entry bibliography -- exit 0,
    one warning line, and nothing to triage. Pure pdf_references logic; no network, DB, or poppler.

    Failure shape this guards against: a letter-spaced heading must open the section, and the
    entries after it must still segment."""
    print("Tier 4e: letter-spaced small-caps section headings (no network/DB)")
    import pdf_references as R

    entries = [
        "[1]  Anna Apple. A first invented entry. Imaginary Press, 2011.",
        "[2]  Ben Berry and Carla Cherry. A second invented entry. J. Imaginary 4, 2 (2015), 1-9.",
        "[3]  Dan Date. A third invented entry. Proc. Imaginary Conf. (2020), 44-51.",
    ]
    # Every spelling `pdftotext` produces for the same heading, plus a section number in front.
    for head in ("R EFERENCES", "R E F E R E N C E S", "B IBLIOGRAPHY", "VII. R EFERENCES",
                 "REFERENCES", "References"):
        section = R._references_section(["Body text before the bibliography.", head, *entries])
        C.eq(section, entries, f"section opens at a {head!r} heading")

    C.eq(R._references_section(["Body text.", "A CKNOWLEDGMENT", *entries]), [],
         "a non-bibliography heading does not open the section")
    C.eq(R._references_section(
        ["R eferences to the standard are collected in Table 3 of this paper.", *entries]), [],
        "space-stripping does not let a sentence starting with 'References' open the section")

    section = R._references_section(["Body text.", "R EFERENCES", *entries])
    style = R._dominant_style(section)
    C.eq(style, "bracket-numeric", "entries under a letter-spaced heading classify normally")
    C.eq([n for n, _, _ in R._segment(section, style)], [1, 2, 3],
         "REGRESSION GUARD: entries after a letter-spaced heading segment as [1]..[3]")

    # The tail heading carries the same artifact, and must still end the section -- otherwise the
    # author biographies an IEEE proof prints after the bibliography land inside it.
    tail = R._segment(R._references_section(
        ["Body text.", "R EFERENCES", *entries, "A CKNOWLEDGMENT",
         "Sam Stone received the Ph.D. degree in imaginary computing."]), "bracket-numeric")
    C.eq([n for n, _, _ in tail], [1, 2, 3],
         "a letter-spaced Acknowledgment heading still ends the section")


def tier4f_dblp_record_metadata() -> None:
    """The dump carries year, venue and the electronic edition on every record, and the ingest
    stored none of them -- `<ee>` was parsed and thrown away. Without them a wrong year or venue,
    or a DOI belonging to another work, cannot be seen offline at all, leaving two of the four
    fabrication signals uncheckable in `--offline` runs. The second opinion now carries them when
    the mirror has them, and must keep working against one that does not."""
    print("Tier 4f: DBLP record metadata reaches the second opinion (no network)")
    import dblp_check as D

    def build(path, with_meta):
        con = sqlite3.connect(str(path))
        c = con.cursor()
        extra = ", year INTEGER, venue TEXT, ee TEXT, kind TEXT" if with_meta else ""
        c.executescript(
            "CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);"
            "CREATE TABLE publication_authors (pub_id INTEGER NOT NULL, author_id INTEGER NOT NULL,"
            " PRIMARY KEY (pub_id, author_id));"
            "CREATE TABLE publications (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL,"
            f" title TEXT NOT NULL{extra});"
            "CREATE VIRTUAL TABLE publications_fts USING fts5(title, content='publications',"
            " content_rowid='id');")
        title = "A placeholder study of imaginary refactoring"
        if with_meta:
            c.execute("INSERT INTO publications(id,key,title,year,venue,ee,kind) "
                      "VALUES(1,?,?,?,?,?,?)",
                      ("journals/x/Ex23", title, 2023, "IEEE Trans. Imaginary Eng.",
                       "https://doi.org/10.0000/fake.2023.1", "article"))
        else:
            c.execute("INSERT INTO publications(id,key,title) VALUES(1,?,?)",
                      ("journals/x/Ex23", title))
        # An accented author and one carrying a stroke, which NFKD alone does not fold.
        for name in ("Marcio Ribeiro", "Adam Przybylek"):
            c.execute("INSERT INTO authors(name) VALUES(?)", (name,))
            c.execute("INSERT INTO publication_authors(pub_id,author_id) VALUES(1,?)",
                      (c.lastrowid,))
        c.execute("INSERT INTO publications_fts(publications_fts) VALUES('rebuild')")
        con.commit()
        con.close()
        return title

    with tempfile.TemporaryDirectory() as td:
        rich, plain = Path(td) / "rich.db", Path(td) / "plain.db"
        title = build(rich, True)
        build(plain, False)
        cited = ["Marcio Ribeiro", "Adam Przybylek"]

        m = D.second_opinion(str(rich), title, cited)
        C.true(m is not None, "the reference is confirmed against a mirror carrying metadata")
        if m is not None:
            C.eq(m.year, 2023, "year travels with the confirmation")
            C.eq(m.venue, "IEEE Trans. Imaginary Eng.", "venue travels with the confirmation")
            C.eq(m.ee, "https://doi.org/10.0000/fake.2023.1", "the electronic edition travels too")
            C.eq(m.kind, "article", "the record type travels too")

        m2 = D.second_opinion(str(plain), title, cited)
        C.true(m2 is not None,
               "REGRESSION GUARD: a mirror without the metadata columns still confirms")
        if m2 is not None:
            C.eq((m2.year, m2.venue, m2.ee, m2.kind), (None, None, None, None),
                 "a mirror without the columns reports metadata as absent, not as an error")


def tier4g_two_column_gutter() -> None:
    """An ACM two-column bibliography sets its columns three characters apart, and requiring four
    blank columns found no gutter on exactly those pages. The page was then read as one column, the
    right column's text was appended to the left column's lines, and about half of each
    bibliography silently vanished -- 8 of 16 references, 21 of 52, 24 of 62. Measured over 37
    arXiv papers (ICSE, FSE, ASE, ESEM old and new, TSE, TOSEM): 94.0% recall at four, 99.1% at
    three, nothing further at two."""
    print("Tier 4g: a three-column gutter is a gutter (no network/DB)")
    import pdf_references as R

    LEFT = [f"[{i}] Author {i} Surname. An invented entry number {i}. Imaginary Press, 20{10 + i}."
            for i in range(1, 7)]
    RIGHT = [f"[{i}] Author {i} Surname. An invented entry number {i}. J. Imaginary {i}, 1-9."
             for i in range(7, 13)]

    def page(gap):
        w = max(len(l) for l in LEFT)
        return [l.ljust(w) + " " * gap + r for l, r in zip(LEFT, RIGHT)]

    C.eq(R._MIN_GUTTER, 3, "a three-character gutter counts")
    g3 = R._gutter(page(3))
    C.true(g3 is not None, "REGRESSION GUARD: a three-character gutter is detected")
    C.true(R._gutter(page(8)) is not None, "a wider gutter is still detected")

    if g3 is not None:
        lines = [x[:g3].rstrip() for x in page(3)] + [x[g3:].rstrip() for x in page(3)]
        section = R._references_section(["Body text.", "References", *lines])
        nums = [n for n, _, _ in R._segment(section, R._dominant_style(section))]
        C.eq(nums, list(range(1, 13)),
             "REGRESSION GUARD: both columns segment, in reading order")

    # Justified single-column text must not be split by a coincidental run of spaces.
    single = ["Anna Apple and Ben Berry. 2019. A single column entry that simply runs on",
              "and continues here with ordinary spacing throughout the paragraph body,",
              "no column break existing anywhere within this block of justified text.",
              "A fourth line of the same paragraph, still without any column break at",
              "all, and a fifth to clear the minimum line count the detector requires.",
              "A sixth line, so the sample is not unusually short for the threshold."]
    C.true(R._gutter(single) is None, "single-column text is not split")


def tier4c_extraction_authoryear_lineno() -> None:
    """Regression for a Springer-style journal submission whose bibliography extraction collapsed:
    32 "references" came out of a 15-entry bibliography, 17 of them unparsable fragments, because
    three faults compounded.

      1. `lineno` detection missed the margin numbers (it required 2+ digits followed by text, so
         single-digit numbers and numbers rendered alone on a line did not count). Every margin
         number then survived into the text as data.
      2. With margin numbers intact the bibliography read as *numeric*, so each physical line
         became its own "reference" -- splitting entries mid-sentence and truncating titles.
      3. The author-year entry pattern only matched "Surname, I."; the Springer "Surname AB,"
         convention never matched it, so the correct style was unreachable in the first place.

    Unlike tier 4b this drives the real PDF, because the fix turns on preserving column positions
    through `pdftotext -layout` -- margin numbers are overwritten with spaces rather than deleted,
    so the hanging indent survives to delimit the entries. A hand-built line list would not
    exercise that. The fixture is generated by fixtures/make_lineno_authoryear.py and contains only
    invented references."""
    print("Tier 4c: author-year extraction under lineno margins (needs poppler; no network/DB)")
    pdf = FIXTURES / "lineno_authoryear.pdf"
    if not pdf.exists():
        C.fail(f"missing fixture PDF {pdf}")
        return
    if which("pdftotext") is None:
        C.skip("pdftotext (poppler) not installed; author-year extraction tier skipped")
        return
    import pdf_references as R

    lines, lineno_on = R._strip_line_numbers(R._linearize(str(pdf)))
    section = R._references_section(lines)
    style = R._dominant_style(section)
    C.true(lineno_on, "REGRESSION GUARD: lineno margins detected (both renderings counted)")
    C.eq(style, "author-year", "REGRESSION GUARD: Springer author-year bibliography, not numeric")
    C.eq(R._entry_indent(section), 5, "the hanging indent's entry column is found")

    segs = R._segment(section, style)
    text = {n: t for n, t, _ in segs}
    C.eq(len(segs), 15, "REGRESSION GUARD: 15 entries segment (was 6, split at every margin number)")
    C.true(all(re.search(r"\((?:19|20)\d{2}[a-z]?\)", t) for t in text.values()),
           "every segment carries a (year) -- none is a stray fragment")

    # The wrapped author list: its "(2022)" sits on the continuation line, and that line opens with
    # "Ivarsson P, Jorgensen M" -- indistinguishable from a new entry without the hanging indent.
    wrapped = next((t for t in text.values() if t.startswith("Corvino")), "")
    C.true("Jorgensen M, et al. (2022)" in wrapped and "arXiv:220100000" in wrapped,
           "REGRESSION GUARD: a wrapped author list stays one entry (year on the next line)")
    C.true(not any(t.startswith("Ivarsson") for t in text.values()),
           "REGRESSION GUARD: a continuation opening with a name does not start a phantom entry")

    # Author forms that the old "Surname, I." pattern could not match.
    for who, why in (("D’Amico AR, Enderby S", "an apostrophe in the surname"),
                     ("de Vries MJ, Fontaine H", "a lowercase particle before the surname"),
                     ("Ibsen GD (1992)", "a lone author with no comma at all")):
        C.true(any(t.startswith(who) for t in text.values()),
               f"an entry starting with {why} is segmented")

    # Page furniture must not become, or contaminate, a reference.
    joined = " ".join(text.values())
    C.true("Placeholder Architecture Recovery" not in joined,
           "REGRESSION GUARD: the repeated running head is not a reference")
    C.true("Ahlgren et al." not in joined, "the number-left running head is dropped too")
    C.true("Click here to download" not in joined,
           "REGRESSION GUARD: the editorial attachment slip stays out of the last reference")
    C.true("pp 38-48" in joined and "pp 72-82" in joined,
           "page ranges survive (the running-head filter does not eat short continuations)")


def tier4h_extraction_furniture() -> None:
    """The three ways a bibliography loses whole references to page furniture, none of which the
    audit can see afterwards: the entries simply are not there.

    A running head spans both columns, so the column gap is not blank on its line, and `_gutter`
    weighs such lines as a *proportion* -- which means the same head passes on a full page and
    fails on a short one. A band found at 97% tolerance still contains lines that run into it, so
    its midpoint cuts through a word. And a reference can wear a head's two disguises at once, a
    wide justification gap and digits that `_head_norm` strips."""
    print("Tier 4h: page furniture, gutter placement and entry recovery (no network/DB)")
    import pdf_references as P

    head = "Where Does Balance Break? Boundary Discovery under a Budget          ASE '26, Munich"

    def body(first: int) -> list[str]:
        return ["[%d] A. Author, \"A title of a work,\" in Proc. X, 2020.        [%d] B. Other, "
                "\"Another title,\" in Proc. Y, 2021." % (i, i + 40) for i in range(first, first + 6)]

    pages = ["\n".join([head] + body(1)), "\n".join([head] + body(7))]
    C.eq(P._page_furniture(pages), {P._furniture_norm(head)},
         "a line repeated at the edge of two pages is page furniture, and the references are not")
    C.eq(P._page_furniture(["\n".join(["pp. 12-19."] + body(1)),
                            "\n".join(["pp. 20-27."] + body(7))]), set(),
         "REGRESSION GUARD: a short edge line is not furniture -- `_head_norm` strips its digits, "
         "and it would collapse onto the tail of every reference")

    short = [head] + body(1)
    C.true(P._gutter(short) is None,
           "the running head hides the gutter on a short page, which is the bug")
    C.true(P._gutter(short[1:]) is not None,
           "and the gutter is there once the head is gone")

    # A band whose columns are not all blank: the midpoint falls inside a word.
    ragged = ["left text here" + " " * 10 + "right text here",
              "left text here" + " " * 10 + "right text here",
              "left text longer x" + " " * 6 + "right text here",
              "left text here" + " " * 10 + "right text here",
              "left text here" + " " * 10 + "right text here"]
    g = P._gutter(ragged)
    C.true(g is not None and all(len(l) <= g or l[g] == " " for l in ragged),
           "REGRESSION GUARD: the cut lands where every line is blank, never inside a word")

    # An entry that looks like a running head still opens its entry.
    section = ['[1] A. Author, "A title," in Proc. X, 2020, pp. 1-10.',
               '[2] "CVE-2017-12652,"        https://nvd.nist.gov/vuln/detail/CVE-2017-12652,',
               '[3] "CVE-2022-1975,"         https://nvd.nist.gov/vuln/detail/CVE-2022-1975,',
               '[4] B. Other, "Another title," in Proc. Y, 2021, pp. 11-20.']
    # The invariant a numbered bibliography gives for free, and the only way a swallowed entry is
    # visible at all: nothing downstream can report a reference that never arrived.
    made = lambda ns, text="": [P.ExtractedRef(n, text or f"[{n}] A. Author, \"T,\" 2020.", None)
                                for n in ns]
    C.eq(P._missing_numbers(made([1, 2, 4, 5]), "bracket-numeric"), [3],
         "an entry the bibliography numbers but extraction never produced is reported")
    C.eq(P._missing_numbers(made([1, 2, 3]), "bracket-numeric"), [],
         "a complete run reports nothing")
    tail = made([1, 2]) + [P.ExtractedRef(3, '[3] A. Author, "T," 2020.   [4] B. Other, "U," 2021.',
                                          None)]
    C.eq(P._missing_numbers(tail, "bracket-numeric"), [4],
         "REGRESSION GUARD: an entry swallowed past the end of the run is reported too -- the "
         "last page is where a two-column layout fails")
    C.eq(P._missing_numbers(made([1, 2, 4]), "author-year"), [],
         "an unnumbered bibliography has no such invariant and is not held to one")

    got = [n for n, _, _ in P._segment(section, "bracket-numeric", section)]
    C.eq(got, [1, 2, 3, 4],
         "REGRESSION GUARD: entries whose justification gap and stripped digits make them look "
         "like a repeated running head still open their own entry")


def tier4i_hanging_indent_author_first() -> None:
    """The unnumbered hanging-indent author-first bibliography: Elsevier's Harvard style, Springer's
    plainnat, ACM author-year. Five corpus papers lost their whole bibliography to it -- two read as
    no style at all and three as numeric on a handful of continuation lines that open with digits
    -- and three more were quietly losing every entry the author-year gate could not match. The
    hanging indent is the structural signal: an entry starts at the left edge, its continuations
    are indented. Driven through `extract_references` with `_pages` standing in for pdftotext, so
    the guard covers the column alignment, the style vote, the entry gate and the biography stop
    together; any one of them can be reverted without the others noticing."""
    print("Tier 4i: hanging-indent author-first bibliographies (no network/DB/poppler)")
    import pdf_references as P
    import reference_parser

    page1 = "\n".join([
        "Some body text of the paper, which ends on this line.",
        "References",
        "Apple, A., Berry, B., 2024. A fictional study of invented widgets, in: Proceedings of the",
        "  1st Imaginary Conference on Widgets, pp. 1–10. URL: https://doi.org/10.0000/fake.",
        "  1142. doi:10.0000/fake.1142.",
        "Cherry, C., Date, D., Elder, E., 2021. Deep learning for placeholder detection: Are we",
        "  there yet? Journal of Imaginary Software 48, 3280–3296.",
        "                                     35",
        "Fred Fig, Gail Gold, and Hugo Hill. Semistructured invention: Rethinking widgets. In",
        "  Proceedings of the 19th Imaginary Symposium, pages 190–200, Szeged, Hungary, September",
        "  2011. Association for Fictional Machinery.",
        "Ivy Ash and Jo Kemp. 2011. Practical change impact analysis for invented programs. In",
        "  Proceedings of the 4th Imaginary Workshop, pages 1–10.",
        "Karl Knot. A state-of-the-art survey on fictional merging. Imaginary Transactions on",
        "  Software, 28(5):449–462, 2002.",
        "OpenAI (2024) Gpt-4 technical report. URL https://arxiv.org/abs/2303.08774",
        "popular-3k python (2023) Dataset — Software Heritage documentation. URL https://",
        "  docs.example.org/popular-3k-python",
    ])
    # A two-column page: the right column's text starts a few columns past the gutter cut, and
    # the centred page number lands inside it, left of its text.
    left = ["Lime, L., Moss, M., 2020. Placeholder testing of",
            "  invented mobile systems. Imaginary Software",
            "  Engineering 21, 1107–1142.",
            "Nest, N., 2019. Modeling with invented UML.",
            "  Imaginary Press. doi:10.0000/fake.2019.",
            "Oak, O., Pine, P., 2018. Faster all-pairs shortest",
            "  paths via fictional circuits. SIAM J. Imag. 47,",
            "  1965–1985. doi:10.0000/fake.2018.",
            "", "", "", ""]
    right = ["Quinn, Q., Reed, R., 2017. On path cover problems",
             "  in invented digraphs. IEEE Trans. Imag. 5, 520–529.",
             "Rose, R., Stone, S., 2016. Random testing of invented",
             "  systems: Theoretical results. IEEE Trans. Imag. 38,",
             "  258–277. doi:10.0000/fake.2016.",
             "Vale, V., 2015. Integer priority queues with decrease",
             "  key in constant time. SIAM J. Imag. 33, 1–10.",
             "", "", "", "", ""]
    rows = [l.ljust(52) + " " * 6 + r for l, r in zip(left, right)]
    rows[-1] = " " * 56 + "36"
    page2 = "\n".join(rows)
    page3 = "\n".join([
        "Lisa Lime is an assistant professor at Imaginary Technical",
        "University. She received B.Sc., M.Sc., and Ph.D. degrees from",
        "Placeholder University, in 2014, 2016, and 2023, respec-",
        "tively, and continued her research at Fictional University.",
        "Her interests include invented testing and fictional widgets.",
    ])
    real_pages = P._pages
    try:
        P._pages = lambda _path: [page1, page2, page3]
        lines = P._linearize("ignored.pdf")
        info = P.extract_references("ignored.pdf", reference_parser)
    finally:
        P._pages = real_pages

    # Column alignment, asserted through `_linearize`.
    oak = next((l for l in lines if l.lstrip().startswith("Quinn, Q.")), None)
    C.true(oak is not None and not oak.startswith(" "),
           "REGRESSION GUARD: the right column's entries are shifted to the left column's edge")
    C.true(any(l.startswith("  in invented digraphs") for l in lines),
           "and its continuations keep their hanging indent")
    C.true(not any(l.strip() == "36" for l in lines),
           "the centred page number the gutter cut is dropped, not moved to the entry column")

    section = P._references_section(P._strip_line_numbers(lines)[0])
    C.eq(P._dominant_style(section), "author-year",
         "REGRESSION GUARD: bare trailing years and years in the venue field still vote "
         "author-year; two continuations opening with digits do not make it numeric")
    C.eq(info.style, "author-year", "extract_references reports the style")
    starts = [r.raw_text.split(",")[0].split(" (")[0] for r in info.refs]
    C.eq(len(info.refs), 13,
         "REGRESSION GUARD: thirteen entries across both pages, and none for the biographies")
    text = {s: r.raw_text for s, r in zip(starts, info.refs)}
    C.true("Apple" in text and "1142. doi:10.0000/fake.1142." in text["Apple"],
           "REGRESSION GUARD: a continuation opening with digits stays inside its entry")
    C.true(not any(s.startswith("1142") for s in starts), "and opens no entry of its own")
    joined = " ".join(r.raw_text for r in info.refs)
    C.true(re.search(r"\b3[56]\b", joined) is None, "neither page number reaches a reference")
    for who, why in (("Ivy Ash and Jo Kemp. 2011. Practical", "a two-author ACM entry"),
                     ("Karl Knot. A state-of-the-art", "a lone author with the year in the venue"),
                     ("Fred Fig", "a plainnat entry with no year on its first line"),
                     ("OpenAI (2024)", "an organisation"),
                     ("popular-3k python (2023)", "a lowercase organisation with a (year)"),
                     ("Rose, R.", "a right-column entry"), ("Vale, V.", "the last right-column entry")):
        C.true(any(r.raw_text.startswith(who) for r in info.refs),
               f"REGRESSION GUARD: {why} opens its own entry")
    C.true("Lime" in text and "invented mobile systems" in text["Lime"],
           "a left-column entry keeps its continuations")
    C.true("assistant professor" not in joined and "Ph.D." not in joined,
           "REGRESSION GUARD: the author biographies after the bibliography are not references")
    C.true(all(r.reference is not None for r in info.refs), "every entry parses")

    def parsed(prefix):
        return next((r.reference for r in info.refs if r.raw_text.startswith(prefix)), None)
    C.eq(getattr(parsed("Apple"), "title", None), "A fictional study of invented widgets",
         "REGRESSION GUARD: Elsevier's comma-joined venue (\", in: Proceedings ...\") is not title")
    C.eq(getattr(parsed("Ivy Ash"), "authors", None), ["Ivy Ash", "Jo Kemp"],
         "the two-author ACM entry reads both names")

    # The vote itself: with a hanging indent, a continuation that opens with digits is not a
    # numeric label, however many there are. Three Elsevier entries whose wrapped page ranges and
    # URLs outnumber them would otherwise read as a four-entry numeric bibliography.
    digits = ["Apple, A., Berry, B., 2024. A fictional study of invented widgets. Imaginary Software",
              "  1142. URL: https://doi.org/10.0000/fake.1142.",
              "  423. OpenJDK JDK Enhancement Proposal.",
              "Cherry, C., Date, D., 2021. Deep learning for placeholder detection. Imaginary Journal 48,",
              "  276. doi:10.0000/fake.276.",
              "Elder, E., 2020. A third invented entry. Imaginary Letters 12,",
              "  353. doi:10.0000/fake.353. special issue on widgets."]
    C.eq(P._dominant_style(digits), "author-year",
         "REGRESSION GUARD: continuations opening with digits outnumbering the entries do not "
         "vote the section numeric")

    # A plain-numeric bibliography with a hanging indent stays numeric under the same vote.
    numeric = ["1. Xavier Xu, Yara Young. A numeric entry with a hanging indent. Venue,",
               "   2019.",
               "2. Zack Zeal. Another numeric entry. Venue, 2020.",
               "3. Wendy West. A third numeric entry. Venue, 2021.",
               "   pp. 1-9."]
    C.eq(P._dominant_style(numeric), "numeric",
         "a numbered hanging-indent bibliography is not pulled into author-year")


def tier5_reference_parser() -> None:
    """The parse half of VERIFICATION-SPEC.md, on one entry of each style the corpus prints.

    Both title conventions (quoted, and the field between the authors and the venue), both author
    orders, surname particles, hyphenated surnames, "et al.", the repeated-author dash, and DOIs
    and arXiv ids in every form they are written in. The last group is the one worth guarding
    hardest: a truncated identifier resolves to a real record that the paper never cited."""
    print("Tier 5: reference parsing (no network/DB)")
    import reference_parser as P

    def parsed(text, prev=None):
        return P.parse_reference(text, prev)

    r = parsed('A. Author and B. Other, "A study of things," in Proc. ICSE, 2020, pp. 1-10.')
    C.eq((r.title, r.authors), ("A study of things", ["A. Author", "B. Other"]),
         "IEEE: the quoted span is the title and what precedes it the authors")

    r = parsed("Jane Doe and John Roe. 2023. An unquoted title. In Proceedings of X. ACM, 1-10.")
    C.eq((r.title, r.authors), ("An unquoted title", ["Jane Doe", "John Roe"]),
         "ACM: the standalone year separates the authors from the title")

    r = parsed("Wohlin C, Runeson P, Host M. Experimentation in things. Springer; 2012.")
    C.eq((r.title, r.authors),
         ("Experimentation in things", ["Wohlin C", "Runeson P", "Host M"]),
         "Vancouver: a run of surname-and-initials ends at the period after its last initial")
    C.eq(parsed("Thomas G. Dietterich. Approximate statistical tests for comparing learners. "
                "Neural Computation, 10(7):1895-1923, 1998.").authors,
         ["Thomas G. Dietterich"],
         "REGRESSION GUARD: a lone author with a middle initial is not read as that run")

    r = parsed("Wohlin, Claes, Per Runeson, and Martin Host. Experimentation in things. "
               "Springer, 2012.")
    C.eq(r.authors, ["Wohlin, Claes", "Per Runeson", "Martin Host"],
         "Chicago inverts only its first author, and writes the given name out")

    C.eq(parsed("Alice Cooper and Bob Marley. In search of effective recommendation. "
                "Journal of Systems and Software, 2020.").title,
         "In search of effective recommendation",
         "REGRESSION GUARD: a title may open with the word 'In' without being a venue")

    r = parsed('A. B. Smith and C. Doe, The "Goodness" of Code Reviews. IEEE Software, 2020.')
    C.eq((r.title, r.authors),
         ('The "Goodness" of Code Reviews', ["A. B. Smith", "C. Doe"]),
         "REGRESSION GUARD: a quoted word inside a title is not the author/title boundary")

    C.eq(parsed("John Doe. 2020. A study of U.S. software firms. In Proc. X. 1-10.").title,
         "A study of U.S. software firms",
         "an abbreviation of more than one letter does not end the title")

    # A title may open with a quotation and run on past it; IEEE style, which tucks the entry's own
    # comma inside the closing mark, means the opposite.
    C.eq(parsed('Ann Bee. 2021. "How Was Your Weekend?" Software Teams Working From Home. '
                "In Proceedings of ICSE. 624-636.").title,
         "How Was Your Weekend? Software Teams Working From Home",
         "REGRESSION GUARD: a quoted opener does not cut the title short")
    C.eq(parsed('R. Tufano and G. Bavota, "Code review automation: Strengths and weaknesses," '
                "IEEE Trans. Softw. Eng., vol. 50, no. 1, 2024.").title,
         "Code review automation: Strengths and weaknesses",
         "the comma inside the closing quote ends the title, as IEEE style intends")
    C.eq(parsed('Q. Zhang and Z. Chen, "Automated repair: How far are we?" IEEE Trans. '
                "Dependable Secur. Comput., vol. 21, no. 3, 2024.").title,
         "Automated repair: How far are we?",
         "a venue of abbreviations still reads as one field, not as several sentences")

    C.eq(parsed("A. One, B. Two, et al. 2025. Deepseek-v3. 2: Pushing the frontier. "
                "arXiv:2512.02556").title,
         "Deepseek-v3. 2: Pushing the frontier",
         "REGRESSION GUARD: a version number the layout broke is not two sentences")
    C.eq(parsed("Ann Bee. 2006. Pixy: a static tool. 2006 IEEE Symposium on Security, 6-263.").title,
         "Pixy: a static tool",
         "a venue that opens with its year still ends the title")

    for text, title in (
            ("Ann Bee. 2025. Phraselette: A Poet's Palette (DIS '25). ACM, 1-15.",
             "Phraselette: A Poet's Palette"),
            ("Jacob Cohen. 1988. Statistical Power Analysis (2 ed.). Routledge.",
             "Statistical Power Analysis"),
            ("Ann Bee. Causes of unreproducible builds in java (2025). URL https://x.org/a",
             "Causes of unreproducible builds in java")):
        C.eq(parsed(text).title, title,
             f"the parenthesis an entry appends to its own title comes off: {text[-24:-1]!r}")

    C.eq(parsed("OpenAI, :, Aaron Hurst, et al. 2024. GPT-4o System Card. arXiv:2410.21276").authors,
         ["OpenAI", "Aaron Hurst"],
         "REGRESSION GUARD: a stray mark between two names does not disqualify the author list")

    # A segmentation slip is how an entry of thousands of question marks arrives.
    started = time.monotonic()
    parsed("A. Author. " + "Really? " * 4000)
    C.true(time.monotonic() - started < 1.0,
           "REGRESSION GUARD: a 32 KB entry parses in well under a second, not in five")

    r = parsed("Wohlin, C., Runeson, P., van den Bergh, J.: Experimentation in things. Springer (2012)")
    C.eq((r.title, r.authors),
         ("Experimentation in things", ["Wohlin, C.", "Runeson, P.", "van den Bergh, J."]),
         "Springer: an inverted list ends at its colon, particles intact")

    r = parsed("Nenad Kolahdouz-Rahimi, Marcelo d'Amorim, and Andrea De Lucia. 2019. "
               "Pixy: a static tool. 2006 IEEE Symposium on Security and Privacy, 6-263.")
    C.eq(r.authors, ["Nenad Kolahdouz-Rahimi", "Marcelo d'Amorim", "Andrea De Lucia"],
         "hyphenated surnames and particles survive the author split")
    C.eq(r.title, "Pixy: a static tool",
         "REGRESSION GUARD: a venue introduced by no 'In' stays out of the title")

    r = parsed("A. One, B. Two, C. Three, et al. 2024. Some title of a paper. In Proc. X. 1-9.")
    C.eq(r.authors, ["A. One", "B. Two", "C. Three"], "'et al.' is not an author")

    r = parsed("D. Four, E. Five, et al. A title with no year beside the names: and a subtitle. "
               "arXiv preprint arXiv:2407.08138, 2024.")
    C.eq((r.title, r.authors, r.arxiv_id),
         ("A title with no year beside the names: and a subtitle", ["D. Four", "E. Five"],
          "2407.08138"),
         "'et al.' closes the author list even where no year follows it")

    r = parsed("----. 2021. A later work by the same people. In Proc. Y. 3-4.",
               ["Jane Doe", "John Roe"])
    C.eq((r.title, r.authors), ("A later work by the same people", ["Jane Doe", "John Roe"]),
         "the repeated-author dash takes the previous entry's authors")

    r = parsed("Ann Bee. 2020. Can a title ask something? Studying how it reads. In Proc. Z. 1-2.")
    C.eq(r.title, "Can a title ask something? Studying how it reads",
         "REGRESSION GUARD: a question mark inside a title does not end it")
    r = parsed("Ann Bee. 2020. Where are the fixes? IEEE Security & Privacy 22, 2 (2024), 49-59.")
    C.eq(r.title, "Where are the fixes?", "a question mark before the venue does end it")

    for text, doi in (
            ("A. B. 2020. T of things. doi:10.1145/1234.5678", "10.1145/1234.5678"),
            ("A. B. 2020. T of things. https://doi.org/10.1145/1234.5678.", "10.1145/1234.5678"),
            ("A. B. 2020. T of things. DOI: 10.1145/1234.5678, 2020", "10.1145/1234.5678"),
            ("A. B. 2020. T of things. doi:10.1145/ 3663529.3663801 [Online]",
             "10.1145/3663529.3663801")):
        C.eq(parsed(text).doi, doi, f"DOI read from {text.split('T of things. ')[1][:34]!r}")

    C.eq(parsed("A. B. 2020. T of things. arXiv:cs.SE/0303001.").arxiv_id, "cs.SE/0303001",
         "an old-form arXiv id is read")
    C.eq(parsed("A. B. 2020. T of things. arXiv:2407.08138v2.").arxiv_id, "2407.08138",
         "a version suffix is not part of the identifier")
    C.eq(parsed("A. B. 2020. T of things. doi:10.48550/arXiv.2602.01107").arxiv_id, "2602.01107",
         "an arXiv id is read out of its DOI")
    C.eq(parsed("A. B. 2020. T of things. arXiv:2407.081385.").arxiv_id, None,
         "REGRESSION GUARD: a malformed six-digit id is refused, not truncated to a real one")
    C.eq(parsed('A. B., "T of things," CoRR, vol. abs/2410.15631, 2024.').arxiv_id, "2410.15631",
         "an identifier written as a CoRR volume is read")

    # A DOI cut in half by a line break resolves to nothing, which triage reads as a dead DOI.
    for text, doi in (
            ("Ann Bee. 2020. A title. doi:10.1007/978-3-030- 66534-0_2",
             "10.1007/978-3-030-66534-0_2"),
            ("Ann Bee. 2020. A title. doi:10.48550/arXiv. 2503.14713", "10.48550/arXiv.2503.14713"),
            ("Ann Bee. 2020. A title. doi:10.48550/arXiv.2411. 19043.", "10.48550/arXiv.2411.19043"),
            ("Ann Bee. 2020. A title. doi:10.1109/FOSE. 2007.25", "10.1109/FOSE.2007.25")):
        C.eq(parsed(text).doi, doi, f"a DOI broken at {text.split('doi:')[1][:22]!r} is rejoined")
    C.eq(parsed("Ann Bee. 2020. A title. doi:10.1145/3498537. Retrieved March 2025.").doi,
         "10.1145/3498537",
         "REGRESSION GUARD: an ordinary sentence after a complete DOI is not joined to it")

    for text in ("[12]", "1769-1786.", "pp. 1-10, doi: 10.1109/ICSE.2019.00035", "  ", ".,;:--"):
        C.true(parsed(text) is None,
               f"{text.strip()!r} is not a reference, and says so instead of inventing a title")
    C.eq(parsed('"Ck," https://github.com/mauricioaniche/ck/releases/tag/ck-0.7.0, 2022.').title,
         "Ck", "a tool's name is a title even at two letters")

    r = parsed("Jane Doe. 2023. A title. In Proc. X. 1-10.")
    C.eq((r.doi, r.arxiv_id), (None, None),
         "fields the entry does not carry are absent, never invented")

    C.eq(parsed("Deep Learning. MIT Press, 2016.").authors, [],
         "REGRESSION GUARD: an entry with no author does not read its own title as one")


    # A hyphenated initial ("K.-W. Chang") whose period read as a sentence end, and Elsevier's
    # comma-joined venue, which no sentence break separates from the title.
    r = parsed("W. U. Ahmad, S. Chakraborty, B. Ray, and K.-W. Chang. Unified pre-training for "
               "program understanding and generation. arXiv preprint arXiv:2103.06333, 2021.")
    C.eq((r.title, r.authors[-1]) if r else None,
         ("Unified pre-training for program understanding and generation", "K.-W. Chang"),
         "REGRESSION GUARD: a hyphenated initial does not end the author sentence")
    r = parsed("Cao, S., Sun, X., Liu, W., 2024. Coca: Improving and explaining fictional detection "
               "systems, in: Proceedings of the 46th Imaginary Conference, pp. 1-13.")
    C.eq(r.title if r else None, "Coca: Improving and explaining fictional detection systems",
         "REGRESSION GUARD: Elsevier's \", in: Proceedings ...\" is the venue, not the title")
    # LaTeX abbreviates an accented given name to "J.ã.P." and pdftotext drops the tilde.
    r = parsed("Pereira, R., Couto, M., Fernandes, J.a.P., Saraiva, J.a., 2016. The influence of "
               "the fictional collection framework on energy, in: Proceedings of GREENS, pp. 1-9.")
    C.eq(r.authors if r else None, ["Pereira, R.", "Couto, M.", "Fernandes, J.a.P.", "Saraiva, J.a."],
         "REGRESSION GUARD: a dotted lowercase initial beside a capital stays with its surname")

    # Springer labels the address it prints, and the label is not the title's last word: eleven
    # corpus references parsed to the title "URL".
    r = parsed("Podman. URL https://podman.io/")
    C.eq((r.title, r.authors) if r else None, ("Podman", []),
         "REGRESSION GUARD: `Podman. URL https://...` is a title and an address, not an author "
         "and the title `URL`")
    r = parsed("Chowdhury, N., Madry, A.: Introducing SWE-bench verified (2024). URL "
               "https://openai.com/index/x/")
    C.eq((r.title, r.authors) if r else None,
         ("Introducing SWE-bench verified", ["Chowdhury, N.", "Madry, A."]),
         "and an inverted Springer list still ends at its colon when the address follows the year")

    # A ? or ! ends the title only when the *next field* is the venue -- not when the sentence
    # after it runs on through the rest of the title and into a comma-joined venue.
    C.eq(parsed("Ann Bee and Bob Cee. Hey! are you committing tangled changes? In Proceedings of "
                "the 22nd International Conference on Program Comprehension, ICPC 2014, page "
                "262-265, New York, NY, USA, 2014. ACM.").title,
         "Hey! are you committing tangled changes?",
         "REGRESSION GUARD: an exclamation mark inside a title does not cut it to its first word")
    C.eq(parsed('Frey, G., Drath, R., 2012. "safety automata" - A new specification language for '
                "PLC safety applications, in: Proceedings of 2012 17th International Conference on "
                "Emerging Technologies & Factory Automation, IEEE, Krakow, Poland. pp. 1-8.").title,
         "safety automata - A new specification language for PLC safety applications",
         "REGRESSION GUARD: a title that opens with a quoted phrase runs on past it even when "
         "Elsevier's `, in:` venue follows in the same sentence")
    C.eq(parsed("Weber, M., Apel, S., 2023. Twins or false friends? a study on energy consumption "
                "and performance of configurable software, in: 2023 IEEE/ACM 45th International "
                "Conference on Software Engineering (ICSE), IEEE. pp. 2098-2110.").title,
         "Twins or false friends? a study on energy consumption and performance of configurable "
         "software",
         "REGRESSION GUARD: nor does a question mark cut the title when Elsevier's `, in:` venue "
         "follows in the same sentence")
    C.eq(parsed("Lev Sorokin and Shiva Nejati. 2025. Can search-based testing effectively cover "
                "failure-revealing test inputs? Empirical Software Engineering 30, 1 (2025), 26. "
                "doi:10.1007/s10664-024-10564-3").title,
         "Can search-based testing effectively cover failure-revealing test inputs?",
         "REGRESSION GUARD: a journal named without a venue word still ends the title at the "
         "question mark, on its `30, 1 (2025)`")

    # A numbered heading, and a listed role.
    C.eq(parsed("Pearson, K.: VII. Note on regression and inheritance in the case of two parents. "
                "Proceedings of the Royal Society of London 58(347-352), 240-242 (1895).").title,
         "VII. Note on regression and inheritance in the case of two parents",
         "REGRESSION GUARD: a title that opens with its own roman numeral is not cut to the numeral")
    C.eq(parsed("John Smith III. A title of a paper. In Proc. X, 2020.").authors, ["John Smith III"],
         "and a name suffix still ends the author sentence")
    r = parsed("M. P. Robillard, W. Maalej, R. J. Walker, and T. Zimmermann, editors. Recommendation "
               "Systems in Software Engineering. Springer, 2014.")
    C.eq((r.title, len(r.authors)) if r else None,
         ("Recommendation Systems in Software Engineering", 4),
         "REGRESSION GUARD: the role after IEEE's comma-delimited names is not the title `editors`")

    # Elsevier's numeric style joins the venue to the title with a comma and no "in:".
    r = parsed("J. White, Q. Fu, S. Hays, et al., A prompt pattern catalog to enhance prompt "
               "engineering with ChatGPT, arXiv preprint arXiv:2302.11382")
    C.eq((r.title, r.arxiv_id) if r else None,
         ("A prompt pattern catalog to enhance prompt engineering with ChatGPT", "2302.11382"),
         "REGRESSION GUARD: an `et al.` followed by a comma says the venue is the next comma field")
    C.eq(parsed('A. One, B. Two, et al., "A study of things," in Proc. ICSE, 2020, pp. 1-10.').title,
         "A study of things", "and a quoted title after such an `et al.` still marks its own end")
    for text, title in (
            ("C. Wohlin, P. Runeson, Experimentation in Software Engineering, Springer, Berlin, "
             "Heidelberg, 2012. doi:10.1007/978-3-642-29044-2.",
             "Experimentation in Software Engineering"),
            ("E. Calboreanu, LATTICE: Layered architecture for trusted intelligence, SSRN, "
             "https://ssrn.com/abstract=6151128 (Jan. 2026).",
             "LATTICE: Layered architecture for trusted intelligence"),
            ("S. M. Barnett, S. J. Ceci, When and where do we apply what we learn? a taxonomy for "
             "far transfer, Psychological Bulletin 128 (4) (2002) 612-637.",
             "When and where do we apply what we learn? a taxonomy for far transfer"),
            ("A. V. Aho, R. Sethi, J. D. Ullman, Compilers: Principles, Techniques, and Tools, "
             "Addison-Wesley, Reading, Massachusetts, U.S.A., 1986.",
             "Compilers: Principles, Techniques, and Tools")):
        C.eq(parsed(text).title, title,
             f"REGRESSION GUARD: the comma-joined venue field comes off the title: {title[-30:]!r}")

    # A DOI the layout broke on one of its own periods, or right after a two-character suffix, or
    # before a hyphen: the front half of an ACM DOI is the proceedings volume, another work.
    for text, doi in (
            ("Ann Bee. 2020. A title. doi:10.1109/ICET.2017. 8281704", "10.1109/ICET.2017.8281704"),
            ("Ann Bee. 2020. A title. doi:10.1145/3395363. 3397366", "10.1145/3395363.3397366"),
            ("Ann Bee. 2020. A title. doi:10.1109/CoG47356. 2020.9231762",
             "10.1109/CoG47356.2020.9231762"),
            ("Ann Bee. 2020. A title. DOI 10.1007/s1 1219-009-9075-x. URL http://x.org/",
             "10.1007/s11219-009-9075-x"),
            ("Ann Bee. 2020. A title. doi:10.1016/B978 -0-12-396535-6.00001-6.",
             "10.1016/B978-0-12-396535-6.00001-6")):
        C.eq(parsed(text).doi, doi,
             f"REGRESSION GUARD: {doi} is rejoined across the break the layout put in it")
    C.eq(parsed("Ann Bee. 2020. A title. doi:10.1145/3498537. 2020.").doi, "10.1145/3498537",
         "REGRESSION GUARD: the entry's own year after a complete DOI is not joined to it")


def tier5b_verifier() -> None:
    """The check half of VERIFICATION-SPEC.md, on a fixture DBLP file with every online backend
    disabled. What is guarded is the vocabulary the audit and the triage rules are built on:
    results align 1:1 with the input, `verified` means a backend matched, a real title with the
    wrong authors is `mismatch` rather than `not_found`, a backend that did not answer lands in
    `failed_dbs` and never reads as `no_match`, and a disabled backend leaves no trace at all --
    which is what keeps the audit's --offline tripwire honest."""
    print("Tier 5b: verification contract (fixture DBLP, no network)")
    import verifier as V

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "dblp.db"
        con = sqlite3.connect(str(db))
        c = con.cursor()
        c.executescript("""
            CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
            CREATE TABLE publication_authors (pub_id INTEGER NOT NULL, author_id INTEGER NOT NULL,
                PRIMARY KEY (pub_id, author_id));
            CREATE TABLE publications (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, title TEXT NOT NULL);
            CREATE VIRTUAL TABLE publications_fts USING fts5(title, content='publications', content_rowid='id');
        """)
        # Two records share the title, as real ones do -- a book and an article, a preprint and
        # its published version.
        c.execute("INSERT INTO publications(id,key,title) VALUES(1,'conf/x/One20',"
                  "'A placeholder title about fictional pipelines')")
        c.execute("INSERT INTO publications(id,key,title) VALUES(2,'journals/x/Other86',"
                  "'A Placeholder Title About Fictional Pipelines')")
        names = ["Alpha Aaron", "Beta Brown", "Gamma Green", "Delta Drew"]
        for i, name in enumerate(names, start=1):
            c.execute("INSERT INTO authors(id,name) VALUES(?,?)", (i, name))
        for pub, ids in ((1, (1, 2)), (2, (3, 4))):
            for i in ids:
                c.execute("INSERT INTO publication_authors(pub_id,author_id) VALUES(?,?)", (pub, i))
        c.execute("INSERT INTO publications_fts(publications_fts) VALUES('rebuild')")
        con.commit()
        con.close()

        offline = {"dblp_path": str(db),
                   "disabled_dbs": (V.CROSSREF, V.DOI, V.ARXIV, V.SEMANTIC_SCHOLAR)}
        refs = [
            V.Reference(title="A placeholder title about fictional pipelines",
                        authors=["Alpha Aaron", "Beta Brown"]),
            V.Reference(title="A placeholder title about fictional pipelines",
                        authors=["Fake F. Faker", "Invented I. Inventor"]),
            V.Reference(title="A wholly invented title never stored anywhere",
                        authors=["Alpha Aaron"]),
        ]
        got = V.check(refs, **offline)
        C.eq(len(got), len(refs), "one result per reference, aligned to the input")
        C.eq(got[0].status, "verified", "a stored title with its own authors verifies")
        C.eq((got[0].source, got[0].paper_url),
             ("DBLP", "https://dblp.org/rec/conf/x/One20"),
             "the confirming backend and its record travel with the result")
        C.eq(got[0].found_authors, ["Alpha Aaron", "Beta Brown"],
             "the matched record's author list travels too")
        C.eq(got[1].status, "mismatch",
             "REGRESSION GUARD: a real title with the wrong authors is a mismatch, not not_found")
        C.eq([d.status for d in got[1].db_results if d.db_name == "DBLP"], ["author_mismatch"],
             "the backend reports which of the two questions it answered no to")
        C.eq(got[2].status, "not_found", "an invented title is not found")
        padded = V.check([V.Reference(title="A placeholder title about fictional pipelines",
                                      authors=["Alpha Aaron", "Beta Brown", "Quentin Fabrikant"])],
                         **offline)[0]
        C.eq((padded.status, padded.paper_url),
             ("mismatch", "https://dblp.org/rec/conf/x/One20"),
             "REGRESSION GUARD: of two records sharing a title, the near miss reported is the one "
             "accounting for most of the cited authors")
        C.true(all(not r.failed_dbs for r in got),
               "nothing failed, so no reference carries a backend failure")
        C.true(all(all(d.db_name == "DBLP" for d in r.db_results) for r in got),
               "REGRESSION GUARD: a disabled backend leaves no db_results row to mistake for a run")

        # Batching: a backend is asked only about what the ones before it did not match. Checked
        # by standing in for the HTTP call, both to keep the tier offline and because the point is
        # exactly *which* references produce a request.
        asked: list[str] = []

        def no_network(url, timeout, user_agent, retries):
            asked.append(url)
            return {"message": {"items": []}}, "ok"

        real = V._fetch_json
        V._fetch_json = no_network
        try:
            got = V.check(refs, dblp_path=str(db),
                          disabled_dbs=(V.DOI, V.ARXIV, V.SEMANTIC_SCHOLAR),
                          max_workers=1)
        finally:
            V._fetch_json = real
        C.eq([d.status for d in got[0].db_results if d.db_name == "CrossRef"], ["skipped"],
             "a matched reference is not sent on to the next backend")
        C.eq(len(asked), 2, "only the two references DBLP did not match reach CrossRef")

    # Record shapes, without asking a backend anything.
    record = V._crossref_record({
        "title": ["RETRACTED: Mining <i>N</i>-grams &amp; more"], "subtitle": ["A study"],
        "author": [{"given": "Ada", "family": "Byte"}], "DOI": "10.1234/x",
        "update-to": [{"DOI": "10.1234/notice", "type": "retraction", "source": "publisher"}]})
    C.eq(record.title, "Mining N-grams & more: A study",
         "a CrossRef title loses its markup and its retraction marker, and keeps its subtitle")
    C.true(record.retraction is not None and record.retraction.is_retracted,
           "REGRESSION GUARD: a retraction deposited under update-to is still a retraction")
    C.eq(V._crossref_record({"title": ["RETRACTED: A paper"]}).retraction.retraction_source,
         "CrossRef title", "the marker publishers write into the title counts on its own")
    C.true(V._crossref_record({"title": ["An ordinary paper"]}).retraction is None,
           "an ordinary record reports no retraction")

    C.eq(V._arxiv_key("cs.SE/0303001v2"), "cs/0303001",
         "REGRESSION GUARD: an old-form arXiv id drops the subject class its citation prints -- "
         "asked for with it, arXiv omits the record from the answer without saying so")

    entries = V._arxiv_entries(b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>http://arxiv.org/abs/2407.08138v2</id><title>A title\n  of a preprint</title>
        <author><name>Ada Byte</name></author></entry></feed>""")
    C.eq(list(entries), ["2407.08138"], "an arXiv id is read back without its version suffix")
    C.eq(entries["2407.08138"].title, "A title of a preprint",
         "a wrapped arXiv title comes back on one line")

    # An identifier a batch omitted is asked for again alone before it is called dead.
    asked_ids: list[str] = []

    def one_empty_feed(url, accept, timeout, user_agent, retries):
        asked_ids.append(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["id_list"][0])
        return b'<feed xmlns="http://www.w3.org/2005/Atom"/>', "ok"

    real, V._fetch, V._ARXIV_PAUSE_REAL = V._fetch, one_empty_feed, V._ARXIV_PAUSE
    V._ARXIV_PAUSE = 0.0
    try:
        got = V.check([V.Reference(title="Some preprint", authors=["Ada Byte"],
                                   arxiv_id="2310.99999")],
                      dblp_path=None,
                      disabled_dbs=(V.DBLP, V.CROSSREF, V.DOI,
                                    V.SEMANTIC_SCHOLAR))[0]
    finally:
        V._fetch, V._ARXIV_PAUSE = real, V._ARXIV_PAUSE_REAL
    C.eq(asked_ids, ["2310.99999", "2310.99999"],
         "an identifier missing from the batch is asked for again on its own")
    C.true(got.arxiv_info is not None and got.arxiv_info.valid is False,
           "an identifier absent from both answers is reported as not existing")

    # A rate limit is not an answer about the reference.
    real = V._fetch
    V._fetch = lambda *a, **k: (None, V.RATE_LIMITED)
    try:
        got = V.check([V.Reference(title="Some preprint", authors=["Ada Byte"],
                                   arxiv_id="2407.08138")],
                      dblp_path=None,
                      disabled_dbs=(V.DBLP, V.CROSSREF, V.DOI,
                                    V.SEMANTIC_SCHOLAR))[0]
    finally:
        V._fetch = real
    C.eq([d.status for d in got.db_results if d.db_name == "arXiv"], ["rate_limited"],
         "REGRESSION GUARD: a rate-limited arXiv request is not read as a missing preprint")
    C.eq((got.failed_dbs, got.arxiv_info), (["arXiv"], None),
         "the backend that did not answer is named, and claims nothing about the identifier")

    C.eq(V._query_forms("Modeling library popu-larity within a software ecosystem"),
         ["Modeling library popu-larity within a software ecosystem",
          "Modeling library popularity within a software ecosystem"],
         "REGRESSION GUARD: a search is asked for the joined reading of a line-break hyphen too")
    C.eq(V._query_forms("A title with no hyphen"), ["A title with no hyphen"],
         "a title carrying no hyphen is asked for once")

    # doi.org redirects to whichever registry holds the DOI, and a DataCite record can take half a
    # minute to come back. The ordinary ceiling turned those answers into timeouts.
    timeouts = []
    real = V._fetch

    def note_timeout(url, accept, timeout, *a, **k):
        timeouts.append((url.split("/")[2], timeout))
        return None, "not_found"

    V._fetch, real_json = note_timeout, V._fetch_json
    V._fetch_json = lambda url, timeout, *a, **k: (timeouts.append(
        (url.split("/")[2], timeout)), (None, "not_found"))[1]
    try:
        V.check([V.Reference(title="A paper", authors=["Ada Byte"], doi="10.5281/zenodo.1")],
                dblp_path=None, timeout=15.0,
                disabled_dbs=(V.DBLP, V.CROSSREF, V.ARXIV, V.SEMANTIC_SCHOLAR))
    finally:
        V._fetch, V._fetch_json = real, real_json
    C.eq([t for host, t in timeouts if host == "doi.org"], [V._DOI_ORG_TIMEOUT],
         "REGRESSION GUARD: doi.org content negotiation gets its own, longer ceiling")

    # Semantic Scholar is asked only where a key is configured: anonymous callers share one small
    # quota, and asking anyway marks an arbitrary handful of references degraded.
    reached = []
    batch = [V.Reference(title="Some paper about things", authors=["Ada Byte"])] * (
        V._S2_GIVE_UP_AFTER + 3)
    real = V._fetch
    V._fetch = lambda *a, **k: (reached.append(a[0]), (None, V.RATE_LIMITED))[1]
    try:
        got = V.check(batch, dblp_path=None, s2_api_key="",
                      disabled_dbs=(V.DBLP, V.CROSSREF, V.DOI, V.ARXIV))
        C.eq((reached, [d.status for d in got[0].db_results]), ([], ["skipped"]),
             "with no key, Semantic Scholar is not asked and claims nothing")
        got = V.check(batch, dblp_path=None, s2_api_key="fake-key", rate_limit_retries=0,
                      disabled_dbs=(V.DBLP, V.CROSSREF, V.DOI, V.ARXIV))
    finally:
        V._fetch = real
    C.eq(len(reached), V._S2_GIVE_UP_AFTER,
         "REGRESSION GUARD: a keyed run that keeps being refused stops asking, but not before "
         f"{V._S2_GIVE_UP_AFTER} of them -- a burst must not sit out the rest of the corpus")
    C.eq([d.status for d in (r.db_results[0] for r in got)],
         [V.RATE_LIMITED] * V._S2_GIVE_UP_AFTER + [V.SKIPPED] * 3,
         "the references it did ask about are degraded; the rest claim nothing")

    # The failure vocabulary, without asking a backend anything.
    result = V.ValidationResult(status="", db_results=[
        V.DbResult("DBLP", "no_match"), V.DbResult("CrossRef", "rate_limited"),
        V.DbResult("DOI", "timeout"), V.DbResult("arXiv", "error")])
    V.Verifier._finish(result)
    C.eq(result.status, "not_found", "no backend matched, so the reference is not found")
    C.eq(result.failed_dbs, ["CrossRef", "DOI", "arXiv"],
         "REGRESSION GUARD: every backend that did not answer is named, none folded into no_match")
    C.eq(result.source, None, "an unconfirmed reference names no deciding backend")


def tier5c_shared_title_record() -> None:
    """Which of several matching records `paper_url` points at.

    Where several DBLP records share a title and every one carries the cited authors, the audit
    showed whichever row order put first, CoRR last: Fowler's "Refactoring" pointed at the XP 2002
    talk rather than the 1999 book, Tokuda and Batory's 2001 journal article at their 1999
    conference paper, Wohlin's 2012 book at its 2024 edition. The year the citation prints names
    the right record; measured over the 55-paper corpus it moves 21 verified references and every
    one to the record whose year the citation prints. The published record stays ahead of the
    preprint whatever the years say, and nothing here ever changes a status."""
    print("Tier 5c: the record shown among several that match (fixture DBLP, no network)")
    import dblp_check as D
    import verifier as V

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "dblp.db"
        con = sqlite3.connect(str(db))
        c = con.cursor()
        c.executescript("""
            CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
            CREATE TABLE publication_authors (pub_id INTEGER NOT NULL, author_id INTEGER NOT NULL,
                PRIMARY KEY (pub_id, author_id));
            CREATE TABLE publications (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL, year INTEGER, venue TEXT, ee TEXT, kind TEXT);
            CREATE VIRTUAL TABLE publications_fts USING fts5(title, content='publications', content_rowid='id');
        """)
        book = "A placeholder book about fictional refactoring"
        paper = "Evolving placeholder designs with fictional refactorings"
        # Row order puts the talk before the book and the conference paper before the journal
        # article, which is the order the audit used to show.
        pubs = [
            (1, "conf/xpu/November02", book, 2002, "XP/Agile Universe", "inproceedings", ["Mike November"]),
            (2, "books/daglib/0000001", book, 1999, "Addison-Wesley", "book", ["Mike November"]),
            (3, "journals/corr/abs-9901-00001", book, 1999, "CoRR", "article", ["Mike November"]),
            (4, "conf/kbse/TangoUniform99", paper, 1999, "ASE", "inproceedings",
             ["Tango Uniform", "Victor Whiskey"]),
            (5, "journals/ase/TangoUniform01", paper, 2001, "Autom. Softw. Eng.", "article",
             ["Tango Uniform", "Victor Whiskey"]),
            (6, "journals/corr/abs-0001-00002", paper, 2000, "CoRR", "article",
             ["Tango Uniform", "Victor Whiskey"]),
        ]
        aid: dict[str, int] = {}
        for pid, key, title, year, venue, kind, authors in pubs:
            c.execute("INSERT INTO publications(id,key,title,year,venue,ee,kind) VALUES(?,?,?,?,?,?,?)",
                      (pid, key, title, year, venue, None, kind))
            for a in authors:
                if a not in aid:
                    c.execute("INSERT INTO authors(name) VALUES(?)", (a,))
                    aid[a] = c.lastrowid
                c.execute("INSERT INTO publication_authors(pub_id,author_id) VALUES(?,?)",
                          (pid, aid[a]))
        c.execute("INSERT INTO publications_fts(publications_fts) VALUES('rebuild')")
        con.commit()
        con.close()
        db = str(db)
        offline = {"dblp_path": db, "disabled_dbs": (V.CROSSREF, V.DOI, V.ARXIV, V.SEMANTIC_SCHOLAR)}

        def url(raw, title=book, authors=("Mike November",)):
            got = V.check([V.Reference(title=title, authors=list(authors), raw_citation=raw)],
                          **offline)[0]
            return got.status, (got.paper_url or "").rsplit("/rec/", 1)[-1]

        C.eq(url("M. November, A placeholder book about fictional refactoring, Addison-Wesley, 1999."),
             ("verified", "books/daglib/0000001"),
             "REGRESSION GUARD: of several records sharing the cited title and authors, the one "
             "whose year the citation prints is shown -- the 1999 book, not the 2002 talk")
        C.eq(url("M. November. A placeholder book about fictional refactoring. In XP/Agile "
                 "Universe, 2002."),
             ("verified", "conf/xpu/November02"),
             "and the talk when the citation prints its year")
        C.eq(url(""), ("verified", "conf/xpu/November02"),
             "a reference handed in without its text gets the published-first order alone")
        C.eq(url("T. Uniform, V. Whiskey, Evolving placeholder designs with fictional "
                 "refactorings, Automated Software Engineering 8 (1) (2001) 89-120.",
                 paper, ("Tango Uniform", "Victor Whiskey")),
             ("verified", "journals/ase/TangoUniform01"),
             "REGRESSION GUARD: the journal article the citation dates, not the conference paper "
             "row order puts first")
        C.eq(url("T. Uniform and V. Whiskey. Evolving placeholder designs with fictional "
                 "refactorings. CoRR abs/0001.00002, 2000.",
                 paper, ("Tango Uniform", "Victor Whiskey")),
             ("verified", "conf/kbse/TangoUniform99"),
             "REGRESSION GUARD: the published record stays ahead of the preprint even where only "
             "the preprint carries the cited year -- 51 corpus references cite the arXiv version "
             "with its year, and each is shown the published one")
        near = V.check([V.Reference(title=book, authors=["Mike November", "Papa Invented"],
                                    raw_citation="Addison-Wesley, 1999.")], **offline)[0]
        C.eq((near.status, (near.paper_url or "").rsplit("/rec/", 1)[-1]),
             ("mismatch", "books/daglib/0000001"),
             "the near miss a mismatch shows follows the same order, and the choice never "
             "changes a status")
        C.eq([c.key for c in D.title_candidates(db, book, {"1999"})],
             ["books/daglib/0000001", "conf/xpu/November02", "journals/corr/abs-9901-00001"],
             "the candidate list carries the order: the cited year first, the preprint last")

    C.eq(D.cited_years("A. Author, Title, in: Proc. ICSE, pp. 1965-1985, 2018. "
                       "doi:10.1109/ICSE.2017.42 arXiv:2005.14165 v. 2001.12345"),
         {"1965", "1985", "2018"},
         "REGRESSION GUARD: the year of an IEEE DOI segment and an arXiv identifier's are not "
         "years the citation prints; a page range that looks like one is the documented cost")
    C.eq(D.cited_years(""), set(), "no text, no years")


def tier6_measured_values() -> None:
    """The measurements themselves, pinned as literals.

    Every constant below is a number somebody measured against the corpus, and each of them was
    once the other value and cost something. A guard written as `C.eq(x, MODULE.THE_CONSTANT)`
    passes whichever value the constant holds, so it guards the shape and not the finding -- and a
    mutation run over the suite found seven fixes that could be reverted with the tests still
    green, these among them. The literals are the point."""
    print("Tier 6: measured values, pinned as literals (no network/DB)")
    import verifier as V
    import dblp_check as D
    import triage as T

    C.eq(V._S2_GIVE_UP_AFTER, 25,
         "REGRESSION GUARD: the Semantic Scholar breaker survives a burst -- at three consecutive "
         "refusals it sat out the rest of the corpus and cost 27 confirmations")
    C.eq(V._S2_PATIENCE, 25,
         "REGRESSION GUARD: under an *intermittent* block -- which never produces 25 refusals in a "
         "row -- the retries stop but the asking does not; the ladder is what put a "
         "2065-reference replay three hours in this one backend")
    C.eq(V._DOI_ORG_TIMEOUT, 45.0,
         "REGRESSION GUARD: doi.org content negotiation keeps its longer ceiling -- DataCite took "
         "8 to 32 s for real Zenodo DOIs, and those references have no other identifier")
    C.eq(V._S2_TIMEOUT, 45.0,
         "REGRESSION GUARD: Semantic Scholar keeps its longer ceiling; a timeout claims nothing")
    C.eq(D._MAX_CANDIDATES, 20000,
         "REGRESSION GUARD: the FTS ceiling stays off the row-order cliff -- at 50 it dropped 3 "
         "corpus confirmations, one of them a record at row 2,507")
    C.true(D._author_matches("O\u2019Donoghue, P.", "Paul O'Donoghue"),
           "a curly apostrophe and a straight one are one surname")
    C.true(D._author_matches("P. ODonoghue", "Paul O'Donoghue"),
           "REGRESSION GUARD: an apostrophe is dropped rather than compared, because extraction "
           "sometimes loses it altogether -- the two mechanisms together were worth 7 corpus "
           "confirmations")
    C.true(D._author_matches("A. Przybylek", "Adam Przyby\u0142ek"),
           "REGRESSION GUARD: a letter carrying a stroke folds to its ASCII form")
    C.true(D._author_matches("O. LeBenich", "Olaf Le\u00dfenich"),
           "REGRESSION GUARD: an eszett a PDF renders as a capital B is read as one")
    C.true(D.authors_match(["Stefan Buettcher"], ["Stefan B\u00fcttcher"]),
           "REGRESSION GUARD: the German transliteration of an umlaut pairs with the letter -- "
           "two corpus references, and the corruption harness unchanged")
    C.true(D.authors_match(["Juergens, E."], ["Elmar J\u00fcrgens"]),
           "in either author order")
    C.true(not D.authors_match(["Miguel Roe"], ["Migul Roe"]),
           "REGRESSION GUARD: the reading is taken off the umlaut, never by contracting 'ue' in "
           "a name that has none")
    C.eq(D._NEAREST_EDITS, 2,
         "REGRESSION GUARD: the mirror's nearest title is at most two word edits away -- the "
         "shapes read in the corpus residue; at three a title is a different title")

    # triage: which db_results rows are a matched record. Named positively, so a failure value the
    # verifier adds later cannot read as a match -- an exclusion list did exactly that with
    # `timeout`, and reverting that fix left this suite green.
    for status in ("timeout", "error", "rate_limited", "no_match", "skipped", "quota_exceeded"):
        C.eq(T._matched_records({"db_results": [{"db": "X", "status": status}]}), [],
             f"a backend row of {status!r} is not a matched record")
    C.eq([r["status"] for r in T._matched_records(
        {"db_results": [{"db": "X", "status": "match"}, {"db": "Y", "status": "author_mismatch"}]})],
        ["match", "author_mismatch"],
        "REGRESSION GUARD: the two statuses that do mean a candidate came back still travel")


def tier6b_completeness_tier() -> None:
    """The phantom-author rule's two tiers, which VERIFICATION-SPEC.md requires be decided from the
    data rather than from a backend's name.

    The strict side is what the tool exists for and must not move: over 250 real DBLP records,
    appending one, two or three invented names is confirmed 0 times. The lenient side is what keeps
    it from accusing people: a record that declares itself truncated, a collaboration byline, and a
    mirror whose ingest dropped its accented authors are all the record's gap, not the citation's --
    42 corpus references were being refused on that account, and 154 more against a stock-built
    mirror."""
    print("Tier 6b: the author-completeness tier (no network)")
    import dblp_check as D
    import verifier as V

    C.true(D.record_authors_complete(["Claes Wohlin", "Per Runeson"]),
           "an ordinary byline of people is a complete author list")
    C.true(not D.record_authors_complete(["Jane Doe", "et al."]),
           "REGRESSION GUARD: a record storing a literal `et al.` says its own list is cut short")
    for byline in (["OpenAI"], ["Qwen Team"], ["Llama Team"], ["DeepSeek-AI"]):
        C.true(not D.record_authors_complete(byline),
               f"REGRESSION GUARD: {byline[0]!r} is a collaboration byline, not an author list")
    C.true(D.authors_match(["Josh Achiam", "Steven Adler", "Sandhini Agarwal"], ["OpenAI"],
                           record_complete=False),
           "a correct citation of a collaboration-credited work is not an author accusation")
    C.true(not D.authors_match(["Claes Wohlin", "Mallory Invented"],
                               ["Claes Wohlin", "Per Runeson"], record_complete=True),
           "REGRESSION GUARD: against a complete record an unmatched cited name still refutes")
    C.true(not D.authors_match(["Jane Roe"], ["Jane Doe", "et al."], record_complete=False),
           "REGRESSION GUARD: a *contradicted* surname refutes whatever tier the record is in")
    C.true(D.authors_match(["Zeller", "Andreas"], ["Andreas Zeller"]),
           "REGRESSION GUARD: one inverted author split across two chunks is one person, not a "
           "phantom -- the record is what settles it")
    C.true(not D.authors_match(["Zeller", "Andreas", "Mallory Fake"], ["Andreas Zeller"]),
           "REGRESSION GUARD: and an invented name alongside the split is still caught")

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "tiny.db"
        con = sqlite3.connect(str(db))
        con.executescript("CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT);")
        con.executemany("INSERT INTO authors (name) VALUES (?)",
                        [(f"Plain Name {i}",) for i in range(2000)])
        con.commit(); con.close()
        C.true(not D.mirror_authors_complete(str(db)),
               "REGRESSION GUARD: a mirror holding no accented name at all had its authors dropped "
               "by the ingest, and its absences cannot be held against a citation")
        con = sqlite3.connect(str(db))
        con.execute("INSERT INTO authors (name) VALUES ('Martin H\u00f6st')"); con.commit(); con.close()
        C.true(D.mirror_authors_complete(str(db)),
               "a repaired mirror gets the strict rule back, with no code change")

    rec = V._Record(title="A Study of Things in Software", authors=["Jane Doe", "John Roe"])
    ref = type("R", (), {"title": "A Study of Things in Software",
                         "authors": ["Privacy (SP)", "Evolution (ICSME)"], "doi": None,
                         "arxiv_id": None})()
    C.eq(V._verdict(ref, rec), V.NO_MATCH,
         "REGRESSION GUARD: an author list of nothing but venue fragments was never compared, so "
         "it is `no_match` -- `author_mismatch` would show a triager a near miss that never was")


def tier6c_answers_and_parsing() -> None:
    """A 200 that is not an answer, and the parse cases VERIFICATION-SPEC.md names by example.

    The first is the contract's sharpest rule: a backend that did not answer must never be
    equivalent to `no_match`, because a `not_found` from an incomplete run is a weaker claim and
    triage is told to treat it as one. An HTML outage page parses as perfectly good XML with no
    entries -- which is exactly what an arXiv identifier that does not exist looks like."""
    print("Tier 6c: non-answers, and the parse examples the contract names (no network)")
    import verifier as V
    import reference_parser as rp
    import pdf_references as P

    ATOM = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    for body, want, label in (
            (ATOM, V.NO_MATCH, "a real feed with no entries is a real negative"),
            (b"<html><body>502</body></html>", V.ERROR,
             "REGRESSION GUARD: an HTML outage page is well-formed XML with no entries -- the root "
             "tag is what separates it from a preprint that does not exist"),
            (b"<?xml version=", V.ERROR, "a truncated body is not an answer"),
            (b"", V.ERROR, "an empty body is not an answer")):
        entries = V._arxiv_entries(body)
        C.eq(V.NO_MATCH if entries is not None else V.ERROR, want, label)

    real = V._fetch
    try:
        for payload, want, label in (
                (b'{"data": []}', V.NO_MATCH, "an empty Semantic Scholar result set is a negative"),
                (b'{"message": "Too Many Requests"}', V.RATE_LIMITED,
                 "REGRESSION GUARD: this backend's soft refusal is a 200 carrying no `data` key, "
                 "and reading it as an empty result reports a clean negative and resets the "
                 "give-up counter"),
                (b'not json at all', V.ERROR, "a body that is not JSON is not an answer")):
            V._fetch = lambda *a, **k: (payload, "ok")
            got = V.check([rp.Reference(title="Some paper about things", authors=["Ada Byte"])],
                          dblp_path=None, s2_api_key="k", rate_limit_retries=0,
                          disabled_dbs=(V.DBLP, V.CROSSREF, V.DOI, V.ARXIV))[0]
            C.eq(got.db_results[0].status, want, label)
        V._fetch = lambda *a, **k: (None, "not_found")
        got = V.check([rp.Reference(title="Some paper about things", authors=["Ada Byte"])],
                      dblp_path=None, s2_api_key="", rate_limit_retries=0,
                      disabled_dbs=(V.DBLP, V.DOI, V.ARXIV, V.SEMANTIC_SCHOLAR))[0]
        C.eq((got.db_results[0].status, got.failed_dbs), (V.ERROR, ["CrossRef"]),
             "REGRESSION GUARD: a 404 from a *search* endpoint says the endpoint moved, not that "
             "the work does not exist")
    finally:
        V._fetch = real

    # Retrieval has to cover a word the layout split with nothing to mark it. `titles_match`
    # compares on letters alone and never sees the space, so the record was always there to match;
    # what was missing was a query that could find it.
    from dblp_check import _glued_query, queryable, titles_match
    C.true(titles_match("A study of synthetic widgets in distributed sy stems",
                        "A study of synthetic widgets in distributed systems"),
           "a word split with no hyphen is the same title once the letters are compared")
    C.true(any('"systems"' in q for q in
               _glued_query("A study of synthetic widgets in distributed sy stems")),
           "REGRESSION GUARD: and a query that can find it is asked -- one fragment glued at a "
           "time, because a title's real short words are short too")
    C.eq(_glued_query("Experimentation software engineering practice"), [],
         "a title carrying no short token asks no extra query")
    C.true(len(_glued_query("A B C study of the sy stems in a lab")) <= 8,
           "the fallback is bounded, not a sweep")
    C.true(queryable("Ck sy stems for code"), "a title of fragments is still askable")

    # Intermittent throttling: refusals accumulate but never 25 in a row, so the backend keeps
    # being asked -- and stops being retried, which is where the wall clock went.
    asked, retries_used = [], []
    def flaky(url, accept, timeout, ua, retries, headers=None):
        asked.append(url); retries_used.append(retries)
        # one answer in five, so `refused_in_a_row` never reaches _S2_GIVE_UP_AFTER
        if len(asked) % 5 == 0:
            return b'{"data": []}', "ok"
        return None, V.RATE_LIMITED
    batch = [rp.Reference(title=f"A paper about things number {i}", authors=["Ada Byte"])
             for i in range(V._S2_PATIENCE + 20)]
    real = V._fetch
    try:
        V._fetch = flaky
        got = V.check(batch, dblp_path=None, s2_api_key="k",
                      disabled_dbs=(V.DBLP, V.CROSSREF, V.DOI, V.ARXIV))
    finally:
        V._fetch = real
    C.eq([d.status for d in (r.db_results[0] for r in got)].count(V.SKIPPED), 0,
         "REGRESSION GUARD: an intermittent block never stops the asking -- capping that instead "
         "cost five confirmations no other backend reaches")
    C.true(retries_used[0] > 0 and retries_used[-1] == 0,
           "REGRESSION GUARD: it stops the retrying instead, which is the 31 s a refusal costs")

    # The three particle surnames the contract names, in the inverted order it also requires.
    got = rp.parse_reference("van den Bergh, J., De Lucia, A., d\u2019Amorim, M.: A study of things "
                             "in software. Journal of Systems and Software (2020)")
    C.eq(len(got.authors if got else []), 3,
         "REGRESSION GUARD: `d'Amorim` written surname-first is an author -- its only capital "
         "follows the particle, and without it the whole byline read as no author list at all")
    got = rp.parse_reference("Institute of Electrical and Electronics Engineers. 2019. IEEE "
                             "Standard for Floating-Point Arithmetic. IEEE.")
    C.eq(got.authors if got else [], ["Institute of Electrical and Electronics Engineers"],
         "REGRESSION GUARD: one body's name is one author, however many `and`s it contains")
    got = rp.parse_reference("A. Author. On Video Game Balancing: Joining Player- and Data-Driven "
                             "Analytics. In Proc. FDG, 2021.")
    C.true(got and "Player- and" in got.title,
           "REGRESSION GUARD: a *suspended* hyphen is not a line break -- closing it invents the "
           "word `Player-and`")
    got = rp.parse_reference("B. Author. Test Co- Evolution in Software Projects. In ICSE, 2019.")
    C.true(got and "Co-Evolution" in got.title,
           "a line break inside a word still closes, and the matchers try both readings")
    got = rp.parse_reference("N. Someone. A Study of Things. Springer, 2020. "
                             "doi:10.1007/978-1-84800-044-5 2.")
    C.eq(got.doi if got else "-", "10.1007/978-1-84800-044-5_2",
         "REGRESSION GUARD: a Springer chapter DOI is rejoined at the underscore pdftotext dropped "
         "-- the half that survives is the *book's* DOI, which resolves, to another work")
    got = rp.parse_reference("N. Someone. Guide to Things. Springer, 2008. "
                             "doi:10.1007/978-3-540-95880-2")
    C.eq(got.doi if got else "-", "10.1007/978-3-540-95880-2",
         "REGRESSION GUARD: and a citation of the whole *book* correctly carries the bare ISBN "
         "suffix -- withholding those cost a real corpus confirmation")
    got = rp.parse_reference("N. Someone. A Study. TACL, 2020. https://doi.org/10.1162/tacl a 00335")
    C.eq(got.doi if got else "-", "10.1162/tacl_a_00335",
         "an ACL DOI loses two underscores to the line break, and both are put back")
    got = rp.parse_reference("N. Someone. A Study. Springer, 2019. doi:10.1007/978-3-030-16145-3 2019.")
    C.eq(got.doi if got else "-", "10.1007/978-3-030-16145-3",
         "REGRESSION GUARD: the entry's own year running on after the DOI is not a chapter number")
    got = rp.parse_reference("N. Someone. A Study of Things. Venue, 2020. doi:10.1145/3597503.3639187")
    C.eq(got.doi if got else None, "10.1145/3597503.3639187", "an intact DOI still comes through")

    class E:
        def __init__(self, n, t):
            self.number, self.raw_text = n, t
    C.eq(P._missing_numbers([E(n, f"[{n}] A. B, T. V, 2020.") for n in (3, 4, 5)],
                            "bracket-numeric"), [1, 2],
         "REGRESSION GUARD: entries lost from the *front* leave no hole in the run, so the run is "
         "walked from 1 -- one corpus bibliography starts at [2] and nothing else could say so")
    C.eq(P._missing_numbers([E(n, f"{n}. A. B, T. V, 2020. Accessed: 2026-05- 30. Next Author")
                             for n in (1, 2)], "numeric"), [],
         "REGRESSION GUARD: a bare `30.` is not an entry label -- over the corpus the bare-number "
         "tail check found one thing, a broken access date, and no real swallowed entry")


def tier6d_extraction_and_env() -> None:
    """The two extraction fixes that recover whole references, and the `.env.local` reader.

    All three were revertible with the suite green. The extraction pair is worth 15 references
    across the corpus and neither has a fixture small enough for tier 4h to have caught; the reader
    could take the whole audit down without the sentinel that is the one thing run.sh promises."""
    print("Tier 6d: gutter placement, page furniture, and the .env.local reader")
    import pdf_references as P

    # A band the 97% tolerance accepts, with one line running into the middle of it. The cut has
    # to fall in the longest run of columns blank on *every* line -- at the band's midpoint it
    # lands inside that line's word, leaves a letter behind, and glues the next entry onto its
    # predecessor. Asserted through `_gutter`, not through its helper: the helper can be correct
    # while the caller ignores it.
    page = ["x" * 40 + " " * 7 + "y" * 33 for _ in range(40)]
    page.append("x" * 40 + "word" + " " * 3 + "y" * 33)          # runs into columns 40-43
    C.eq(P._gutter(page), 45,
         "REGRESSION GUARD: the gutter cut falls in the longest run of columns blank on every "
         "line, not at the midpoint of a band found at 97% tolerance")

    # A running head spans both columns, so the gutter is not blank on its line, and `_gutter`
    # weighs such lines as a *proportion* -- so the same head passes on a full page and loses the
    # column split on a short one, which cost one corpus paper the last seven references of its
    # bibliography. It has to come off before the gutter is measured.
    head = "IEEE TRANSACTIONS ON SOFTWARE ENGINEERING, VOL. 51, NO. 3, MARCH 2025      %d"
    def body(tag):
        # Distinct lines: identical ones would themselves look like a repeated footer.
        return [f"Left column line {tag}{i:02d}" + " " * 20 + f"Right column line {tag}{i:02d}"
                for i in range(10)]
    pages = ["\n".join([head % n] + body(t)) for n, t in ((1234, "a"), (1235, "b"), (1236, "c"))]
    real_pages = P._pages
    try:
        P._pages = lambda _path: pages
        out = P._linearize("ignored.pdf")
    finally:
        P._pages = real_pages
    C.true(any("Right column line a00" == l.strip() for l in out),
           "REGRESSION GUARD: the running head is removed before the gutter is measured, so a "
           "short two-column page still splits -- left as it is, the right column is appended to "
           "the left column's lines and half the bibliography disappears")
    C.true(P._furniture_norm(head % 1234) in P._page_furniture(pages),
           "a head differing only in its page number is recognised as furniture")
    C.true(P._furniture_norm("Smith et al. Some Title 2020") not in P._page_furniture(pages),
           "a line that appears once is not furniture")

    # `.env.local` shapes an ordinary file carries. Any of them used to end the run with a bash
    # error and no sentinel, which is the failure mode SKILL.md's stop conditions key on.
    run_sh = SCRIPTS / "run.sh"
    if which("bash") is None:
        C.skip("bash not available; .env.local reader skipped")
        return
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "skills" / "hallucite" / "scripts").mkdir(parents=True)
        (root / "skills" / "hallucite" / "scripts" / "run.sh").write_bytes(run_sh.read_bytes())
        os.chmod(root / "skills" / "hallucite" / "scripts" / "run.sh", 0o755)
        for label, text in (
                ("an indented comment", "  # a note about the key\nS2_API_KEY=abc\n"),
                ("an `export` prefix", "export S2_API_KEY=abc\n"),
                ("CRLF line endings", "S2_API_KEY=abc\r\n"),
                ("a value containing `=`", "S2_API_KEY=a=b=c\n"),
                ("a blank file", "\n\n")):
            (root / ".env.local").write_text(text)
            env = {k: v for k, v in os.environ.items() if k != "S2_API_KEY"}
            env["HALLUCITE_NO_VERSION_CHECK"] = "1"
            proc = subprocess.run(
                ["bash", str(root / "skills" / "hallucite" / "scripts" / "run.sh"), "no-such-cmd"],
                capture_output=True, text=True, env=env)
            C.true("HALLUCITE_BOOTSTRAP_FAILED:" in proc.stderr,
                   f"REGRESSION GUARD: {label} in .env.local does not take run.sh down without "
                   f"its sentinel")


def tier6e_dblp_ingest() -> None:
    """The mirror hallucite now builds for itself, on a dump small enough to check by eye.

    Two failures put the whole author rule out of true and neither shows in a count or a title. An
    ingest that cannot resolve the dump's own character entities drops every author whose name
    carries a diacritic, which makes the mirror disagree with correctly cited references; and one
    that splices UTF-8 into a document declaring ISO-8859-1 turns "Jürgen" into "JÃ¼rgen", which is
    the same failure wearing a different mask. The dump is 4.5 GB, so both are guarded here on
    twenty lines of it."""
    print("Tier 6e: hallucite's own DBLP ingest (no network)")
    import build_dblp
    import dblp_check as D

    dump = b"""<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE dblp SYSTEM "dblp.dtd">
<dblp>
<article mdate="2020-01-01" key="journals/x/Beyerer14">
<author>J&uuml;rgen Beyerer</author><author>Fran&ccedil;ois Chaumette</author>
<title>Semantics of context-free languages</title><year>2014</year>
<journal>Math. Systems Theory</journal><volume>2</volume><pages>127-145</pages>
<ee>https://doi.org/10.1007/BF01692511</ee></article>
<book mdate="2020-01-01" key="books/x/Ikeuchi14">
<editor>Katsushi Ikeuchi</editor><title>Computer Vision, A Reference Guide</title>
<year>2014</year><publisher>Springer</publisher></book>
<www mdate="2020-01-01" key="homepages/12/345"><author>Jane Doe</author>
<title>Home Page</title></www>
</dblp>
"""
    with tempfile.TemporaryDirectory() as td:
        gz = Path(td) / "dblp.xml.gz"
        with gzip.open(gz, "wb") as fh:
            fh.write(dump)
        db = Path(td) / "dblp.db"
        build_dblp.build(gz, db, None, 0)
        con = sqlite3.connect(str(db))
        names = {r[0] for r in con.execute("SELECT name FROM authors")}
        C.true("Jürgen Beyerer" in names,
               "REGRESSION GUARD: a named entity resolves to its character -- an ingest that drops "
               "them loses every author whose name carries a diacritic")
        C.true("JÃ¼rgen Beyerer" not in names,
               "REGRESSION GUARD: and it is spliced back as a numeric reference, not as UTF-8 "
               "bytes -- the dump declares ISO-8859-1, which would decode them as Latin-1")
        C.true("Katsushi Ikeuchi" in names,
               "REGRESSION GUARD: an edited book records its people in <editor>, and that is who a "
               "citation of it names")
        C.true("Jane Doe" not in names,
               "REGRESSION GUARD: a <www> person homepage is not a publication -- three million of "
               "them would put a person's name in the title index")
        row = con.execute("SELECT title, year, venue, ee, kind, volume, pages FROM publications "
                          "WHERE key='journals/x/Beyerer14'").fetchone()
        C.eq(row, ("Semantics of context-free languages", 2014, "Math. Systems Theory",
                   "https://doi.org/10.1007/BF01692511", "article", "2", "127-145"),
             "every column the second opinion and the triage evidence read is populated")
        con.close()
        C.true(D.mirror_authors_complete(str(db)),
               "the completeness tier reads this mirror as one that kept its authors")
        got = D.title_candidates(str(db), "Semantics of Context-Free Languages")
        C.eq([(c.key, c.authors) for c in got],
             [("journals/x/Beyerer14", ["Jürgen Beyerer", "François Chaumette"])],
             "and dblp_check queries the result through its own FTS index")




def main() -> int:
    tier1_packaging()
    tier1b_runner()
    tier1c_codex_cli_marketplace()
    tier3_logic()
    tier3d_duplicate_entries()
    tier3e_reference_labels()
    tier3f_degraded_verification()
    tier3b_triage_concurrency()
    tier3c_title_first_gate()
    tier3g_stale_verdicts()
    tier3j_residue_evidence()
    tier3k_authors_absent()
    tier3h_author_absence()
    tier3i_dblp_author_encoding()
    tier4_end_to_end()
    tier4b_extraction_lineno()
    tier4e_smallcaps_heading()
    tier4c_extraction_authoryear_lineno()
    tier4d_dblp_second_opinion()
    tier4f_dblp_record_metadata()
    tier4g_two_column_gutter()
    tier4h_extraction_furniture()
    tier4i_hanging_indent_author_first()
    tier5_reference_parser()
    tier5b_verifier()
    tier5c_shared_title_record()
    tier6_measured_values()
    tier6b_completeness_tier()
    tier6c_answers_and_parsing()
    tier6d_extraction_and_env()
    tier6e_dblp_ingest()
    print()
    if C.failed:
        print(f"SMOKE FAILED: {C.failed} check(s) failed, {C.skipped} skipped")
        return 1
    print(f"SMOKE OK: all checks passed ({C.skipped} skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
