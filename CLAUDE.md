# Claude Code guidance for hallucite

## What this is

`hallucite` finds hallucinated (fabricated) references in academic paper PDF files. Stages 1 and 2
(extract, then verify against DBLP, CrossRef, arXiv, and others) are local and deterministic.
Stage 3 (triage the database-unverified residue) is the LLM step, done interactively by you. See
`PLAN.md` for the design and architecture, `README.md` for commands.

One repo, two roles: it is the runnable project (mise tasks) and an installable plugin for Claude
Code and Codex CLI. Claude Code uses `.claude-plugin/plugin.json` plus
`.claude-plugin/marketplace.json` (name `se-uhd`, plugin `source: "./"`). Codex CLI uses
`.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `plugins/hallucite -> ..`, and
`.agents/skills/hallucite -> ../../skills/hallucite`. The pipeline scripts live once in
`skills/hallucite/scripts/`, used by mise and by the bundled skill (`skills/hallucite/SKILL.md`).
No separate plugin repo, no submodule.

## Running things

- The bundled skill drives the pipeline through `skills/hallucite/scripts/run.sh`, the single
  entry point (`check-env | audit | triage | lint | python`). It resolves the wrapper from a Claude
  Code plugin install, a Codex repo-local skill shim, a direct repo clone, or the Codex plugin
  cache. The wrapper resolves -- or on first use provisions at
  `${XDG_CACHE_HOME:-~/.cache}/hallucite/venv` -- a Python 3.12 that can `import hallucinator`,
  never relying on a bare `python`/`uv`/`mise` being on the plugin shell's PATH (the failure that
  made the plugin silently un-runnable). It fails loud with a `HALLUCITE_BOOTSTRAP_FAILED:`
  sentinel and a non-zero exit; `$HALLUCITE_PYTHON` reuses an existing hallucinator environment and
  skips provisioning. `run.sh check-env` is the preflight.
- In a repo clone you can equivalently use mise tasks: `mise run install | install-cli |
  build-dblp | audit | lint-md`. Python is pinned to 3.12 (hallucinator's wheels). Both paths run
  the same scripts in `skills/hallucite/scripts/`.
- The offline DBLP database defaults to `~/hallucite/dblp.db`, outside this repo (large, not
  committed); override the location with `$HALLUCITE_DBLP`. The audit warns at run time when it is
  over 30 days old. Do not put it under the repo: an installed plugin is cloned to a managed dir
  the user never sees, so an in-repo (even gitignored) path would not work for marketplace installs.
- Stage 1/2 driver: `skills/hallucite/scripts/audit_references.py` (parses each reference via
  `pdf_references.py` plus hallucinator's `parse_reference`, then runs `Validator`). The target
  is 0 unparsed references.
- Stage 3: `triage.py worklist | status | record | report`. Verdicts persist in
  `out/triage_verdicts.json` (keyed `paper_id:number`, resumable), so triage can run on finished
  papers while the audit is still going: `worklist --pending` lists only un-recorded references and
  `status` shows per-paper progress. To fan out, give each worker its own `worklist --paper <id>`
  slice (exact id match, errors on an unknown id) so it never self-filters the shared worklist and
  grabs the wrong paper (`paper6` vs `paper66`); `record` takes an `fcntl` lock on the verdicts file
  so concurrent workers don't lose updates. `record --signals '<json>'` carries the structured
  fabrication signals and enforces the title-first rule (`partial-match` needs `title_match=yes`+
  `matched_title` or `na`; `likely-hallucinated` needs `title_match=no`). `report` writes the
  per-paper checks, the `potential-hallucinations.md` rollup (severity table + a **Desk-reject
  candidates** section keyed on `is_fabrication`), and `verify-<paper>.md` sheets, and auto-lints
  every file it writes.

## Triage conventions (Stage 3)

- Never fabricate a verdict. A verdict may rest only on a Stage 1+2 `db_verification` record the
  audit wrote or Stage 3 web evidence you actually gathered -- never on reading the `.bib`/`.bbl`/PDF
  by eye. If `run.sh` exits non-zero or prints `HALLUCITE_BOOTSTRAP_FAILED:`, or output starts
  coming back empty, stop and report it verbatim; "the tool would not run" is the correct outcome,
  not a hand-written report. This rule lives in full in `SKILL.md` ("Stop conditions") and is
  guarded by smoke tier 1b.
- Investigate with parallel web queries; resolve DOIs via `api.crossref.org/works/<doi>`. If a
  narrow query (title + author) finds nothing, broaden to the bare title (unquoted) and screen the
  results before judging; obscure/predatory venues are poorly indexed, so "not found" on a narrow
  query is not fabrication evidence.
- Classify title-first, and keep two questions separate: (1) does a publication bearing the cited
  *title* exist (matching on title, not on a same-authors/same-venue paper with a different title)?
  (2) only if yes, do the metadata fields match? Match the title on meaning: formatting, subtitle,
  hyphen/spacing/spelling/OCR differences are the same title; a wrong content word counts as found
  only when a resolving DOI or an exact author+venue+year match pins it to one real publication.
  `partial-match` requires question 1 to be *yes* -- a real, locatable work with the cited title but
  a slipped field (wrong year/DOI digit/venue/co-author). If no work bears the cited title, the
  cited work does not exist: `likely-hallucinated`
  (thorough search + fabrication signals) or `unclear`. Never rescue a non-existent title to
  `partial-match` just because the authors or venue match some *other* real paper -- that conflation
  is what misfiled a fabricated reference as a citation error and forced a long correction.
- Honest human mistakes do not invent titles; they slip a metadata field on a real, findable work.
  Independent fabrication signals: **(T) no publication has the cited title** (decisive); **(A)** an
  author set/order that never co-published, or initials-only generic authors; **(V)** an impossible
  or non-existent venue/year/volume (e.g. a proceedings entry + page range that do not exist, a
  defunct journal); **(D)** a dead/mismatched DOI or placeholder arXiv id (`2310.XXXX`). A
  non-existent title (T) is itself a fabrication and grounds to desk-reject -- even with real
  authors and a real venue (the hardest case); A/V/D strengthen it but are not required. This is
  what `is_fabrication` keys on.
- Categories: `real-published`, `real-grey-literature`, `real-preprint-or-unpublished` (low);
  `partial-match` (citation error, medium); `likely-hallucinated` (high); `unclear`.
- Do not push borderline cases into `real-*` to make a report look clean. `unclear` is a valid,
  useful verdict, and a "hallucinated" call against named authors is serious: flag it for review,
  do not accuse. Equally, do not downgrade a fabricated title to a citation error to avoid the
  accusation -- record what the evidence shows.

## Conventions

- Editing a script under `skills/hallucite/scripts/` updates it for mise, Claude Code, and Codex
  CLI (one copy). On a real release, bump the version in `.claude-plugin/plugin.json`,
  `.codex-plugin/plugin.json`, and `skills/hallucite/SKILL.md` (`metadata.version`), add a
  `CHANGELOG.md` entry, and tag the release commit: `git tag v<version>` (lightweight, matching the
  existing `v*` tags and the CHANGELOG link footers). Run the smoke tests
  (`python skills/hallucite/scripts/tests/run_smoke.py`) and do not consider a release done until
  it is tagged and they pass.
- Commit messages follow Conventional Commits: `type(scope): imperative summary`. Types: `feat`,
  `fix`, `docs`, `test`, `ci`, `chore`, `refactor`; the scope is the pipeline area (`audit`,
  `extract`, `triage`) or tooling, and is omitted for cross-cutting changes. Keep the summary short
  and imperative and put detail in the body. Do not put the release version in the message -- the
  `v*` tag records the release.
- Verification `status` and `db_name` strings come from the external `hallucinator` package; treat
  them as a contract that can drift. Define "needs triage" by negation (`status != "verified"`),
  never by an allow-list of failure strings, and keep the invariant that every reference is
  verified, unverified, or pending (none silently dropped). Validate any hard-coded hallucinator
  name against what the package actually emits (`run_smoke.py` and the audit's `--offline`
  tripwire do this); a silent name mismatch is what caused both the `mismatch` and the
  `DOI Resolver` bugs.
- Plans and READMEs describe only the current approach. Do not narrate dropped or superseded
  ideas, or "out of scope" history. After a scope change, rewrite the doc as if the final
  approach were always the plan.
- Check prose you write -- docs, README, PLAN, CHANGELOG, commit and PR messages, the triage
  reports -- against the AI-slop tropes in
  <https://gist.github.com/ossa-ma/f3baa9d25154c33095e22272c631f5a1>. The frequent offenders here:
  "it's not X, it's Y" negative parallelism, filler transitions ("it's worth noting",
  "importantly"), grandiose stakes, vague attributions ("experts say") instead of a named source,
  invented concept labels, and inflated verbs (`use`, not `utilize`/`leverage`). Em dashes (`--`)
  and bold-lead bullets already appear in these files; do not pile on more than the surrounding
  text uses. Plain, specific, and varied beats ornate.
- Keep Markdown lint-clean: `mise run lint-md` (`MD_FIX=1` to auto-fix). The vendored PyMarkdown
  in `skills/hallucite/scripts/` is synced from se-uhd/pymarkdown-skill; do not hand-edit
  `_vendor/`, `lint_markdown.py`, or `check_baseline.py` (re-sync instead). The hallucite-owned
  files are `schema_checks.py` and `lint_markdown.yaml`.
