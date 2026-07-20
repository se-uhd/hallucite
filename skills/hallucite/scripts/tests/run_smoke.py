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
  1b run.sh bootstrap       -- the wrapper syntax-checks, rejects an unknown command, and fails
                              loud (sentinel + non-zero) when its Python lacks hallucinator.
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
  3g stale verdicts        -- a verdict recorded against reference text a re-audit then changed
                              is quarantined: report shows it as stale/pending (never the old
                              category against the new reference) and --pending resurfaces it.
  3d repeated entries      -- entries sharing authors+title under different citation keys are
                              grouped and classified: identical in every field = duplicate (a
                              fact), differing venue/volume/pages = conflicting (an open question).
  3e reference labels      -- a numeric bibliography reports its printed "[N]"; an unnumbered
                              author-year one reports the citation key the paper itself uses, and
                              any tool-internal index is marked as not appearing in the paper.
  4  end-to-end (offline)   -- build a tiny fixture DBLP DB, run the real audit --offline on a
                              synthetic fixture PDF, assert verified/not_found. Needs the
                              hallucinator package and pdftotext (poppler); skipped if absent.
  4b extraction segmentation -- a bracket-numeric bibliography under LaTeX lineno margins, across a
                              page-break margin reset, segments as [1]..[N] (the margin numbers do
                              not hijack the sequence, drop the first entry, or collapse the tail).
                              Pure pdf_references logic; no network, DB, or poppler.
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
    C.true("upgrade" in r.stderr, "usage lists the upgrade subcommand")

    # `upgrade` manages only the venv run.sh itself built. Pointing HALLUCITE_PYTHON at an
    # interpreter and having run.sh pip-install into it would mutate an environment the user owns,
    # so that combination must refuse rather than "helpfully" upgrade.
    r = run(["upgrade"], env_add={"HALLUCITE_PYTHON": sys.executable})
    C.true(r.returncode != 0 and SENTINEL in r.stderr and "HALLUCITE_PYTHON" in r.stderr,
           "REGRESSION GUARD: upgrade refuses to modify a user-provided HALLUCITE_PYTHON")

    # FAIL-LOUD, exercised deterministically regardless of the host's Pythons: a HALLUCITE_PYTHON
    # that is not even executable can never import hallucinator, so resolve_python must `die` with
    # the sentinel rather than fall through to a silent run. This is the guarantee that stops a
    # broken environment from masquerading as a clean audit.
    r = run(["check-env"], env_add={"HALLUCITE_PYTHON": str(TESTS / "no-such-python")})
    C.true(r.returncode != 0 and SENTINEL in r.stderr,
           "REGRESSION GUARD: run.sh fails loud (sentinel) when HALLUCITE_PYTHON is unusable")

    # HAPPY PATH + subcommand dispatch, when a hallucinator-capable Python exists. Point
    # HALLUCITE_PYTHON at it so no venv is provisioned, then check both `check-env` and that an unknown
    # *script* flag is forwarded (proving args reach the underlying script, not swallowed by run.sh).
    if subprocess.run([sys.executable, "-c", "import hallucinator"],
                      capture_output=True).returncode == 0:
        r = run(["check-env"], env_add={"HALLUCITE_PYTHON": sys.executable})
        C.true(r.returncode == 0 and "HALLUCITE_OK:" in r.stdout,
               "run.sh check-env prints HALLUCITE_OK for a hallucinator-capable Python")
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
    try:
        from audit_references import reference_label
    except SystemExit:
        C.skip("hallucinator absent; audit_references import skipped")
        return
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
    try:
        import audit_references as audit
    except SystemExit:
        C.skip("hallucinator absent; audit_references import skipped")
        return

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
    tier4_end_to_end()
    tier4b_extraction_lineno()
    tier4c_extraction_authoryear_lineno()
    print()
    if C.failed:
        print(f"SMOKE FAILED: {C.failed} check(s) failed, {C.skipped} skipped")
        return 1
    print(f"SMOKE OK: all checks passed ({C.skipped} skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
