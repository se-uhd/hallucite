# Claude Code guidance for hallucite

## What this is

`hallucite` finds hallucinated (fabricated) references in academic paper PDF files. Stages 1 and 2
(extract, then verify against DBLP, CrossRef, arXiv, and others) are local and deterministic.
Stage 3 (triage the database-unverified residue) is the LLM step, done interactively by you. See
`PLAN.md` for the design and architecture, `README.md` for commands.

One repo, two roles: it is the runnable project (mise tasks) and an installable Claude Code
plugin. The repo root is the plugin (`.claude-plugin/plugin.json`), and
`.claude-plugin/marketplace.json` (name `se-uhd`, plugin `source: "./"`) makes it its own
single-plugin marketplace. The pipeline scripts live once in `skills/hallucite/scripts/`, used
both by mise and by the bundled skill (`skills/hallucite/SKILL.md`, which calls them via
`${CLAUDE_PLUGIN_ROOT}`). No separate plugin repo, no submodule.

## Running things

- Use mise tasks rather than hand-rolled venvs: `mise run install | install-cli | build-dblp |
  audit | lint-md`. Python is pinned to 3.12 (hallucinator's wheels).
- The offline DBLP database is at `~/hallucite/dblp.db`, outside this repo (large, not committed).
  The audit warns at run time when it is over 30 days old. Do not move it back under the repo.
- Stage 1/2 driver: `skills/hallucite/scripts/audit_references.py` (parses each reference via
  `pdf_references.py` plus hallucinator's `parse_reference`, then runs `Validator`). The target
  is 0 unparsed references.
- Stage 3: `triage.py worklist | status | record | report`. Verdicts persist in
  `out/triage_verdicts.json` (keyed `paper_id:number`, resumable), so triage can run on finished
  papers while the audit is still going: `worklist --pending` lists only un-recorded references and
  `status` shows per-paper progress. `report` writes the per-paper checks, the
  `potential-hallucinations.md` rollup, and `verify-<paper>.md` sheets, and auto-lints every file
  it writes.

## Triage conventions (Stage 3)

- Investigate with parallel web queries; resolve DOIs via `api.crossref.org/works/<doi>`.
- Fabrication signatures: dead or mismatched DOIs, non-existent or defunct journals, an
  impossible volume/year, initials-only generic authors, real authors attached to a non-existent
  title, placeholder arXiv IDs such as `2310.XXXX`.
- Categories: `real-published`, `real-grey-literature`, `real-preprint-or-unpublished` (low);
  `partial-match` (citation error, medium); `likely-hallucinated` (high); `unclear`.
- Do not push borderline cases into `real-*` to make a report look clean. `unclear` is a valid,
  useful verdict, and a "hallucinated" call against named authors is serious: flag it for review,
  do not accuse.

## Conventions

- Editing a script under `skills/hallucite/scripts/` updates it for both mise and the plugin
  (one copy). On a real release, bump the version in `.claude-plugin/plugin.json` and
  `skills/hallucite/SKILL.md` (`metadata.version`) and add a `CHANGELOG.md` entry.
- Plans and READMEs describe only the current approach. Do not narrate dropped or superseded
  ideas, or "out of scope" history. After a scope change, rewrite the doc as if the final
  approach were always the plan.
- Keep Markdown lint-clean: `mise run lint-md` (`MD_FIX=1` to auto-fix). The vendored PyMarkdown
  in `skills/hallucite/scripts/` is synced from se-uhd/pymarkdown-skill; do not hand-edit
  `_vendor/`, `lint_markdown.py`, or `check_baseline.py` (re-sync instead). The hallucite-owned
  files are `schema_checks.py` and `lint_markdown.yaml`.
