<p align="center">
  <img src="assets/logo-readme.png" alt="hallucite logo" width="320">
</p>

# hallucite

Finds fabricated ("hallucinated") references in academic paper PDF files. Each reference is checked
against academic databases (offline DBLP, plus CrossRef, arXiv, OpenAlex, and Semantic Scholar);
references that no database can confirm are escalated to an interactive LLM triage step, which
writes a report for human review.

Three stages: extract and verify are local and deterministic (no LLM); triage is the only step
that uses an LLM, which can be a cloud or a local model. See [PLAN.md](PLAN.md) for the design and
architecture.

One repo serves as the runnable project (the mise tasks below) and one shared plugin tree for
Claude Code and Codex CLI. The Claude metadata lives under `.claude-plugin/`; the Codex metadata
lives under `.codex-plugin/` and `.agents/plugins/marketplace.json`. The bundled skill in
`skills/hallucite/` drives the same scripts for both tools.

## Setup (once)

Run from this directory. Requires [mise](https://mise.jdx.dev).

```sh
mise install          # provision Python 3.12 + uv (auto-venv)
mise run install      # uv pip install -r requirements.txt  (hallucinator)
mise run install-cli  # download the hallucinator CLI binary into .bin/ (checksum-verified)
mise run build-dblp   # build the offline DBLP database at ~/hallucite/dblp.db (~4.6 GB, ~20-30 min)
```

The offline DBLP database lives at `~/hallucite/dblp.db`, outside this repo, which keeps the
2.5 GB file out of git. Set `$HALLUCITE_DBLP` to store it somewhere else.

## Run the audit (Stages 1+2, no LLM)

```sh
mise run audit -- <pdf-file-or-dir>            # required: a PDF file, or a directory of PDF files
mise run audit -- <pdf-file-or-dir> <out-dir>  # optional 2nd arg sets the output dir (default: out)
```

Writes `out/<paper_id>.json` (every reference plus per-database verification) and
`out/summary.json` (status counts plus the DBLP build date). Options: `--dblp PATH`, `--out DIR`,
`--mailto EMAIL`, `--offline` (DBLP-only), `--no-verify`. The DBLP path defaults to
`$HALLUCITE_DBLP` (else `~/hallucite/dblp.db`). A reference needs triage when its
`db_verification.status` is anything other than `verified` (`not_found`, `mismatch`, or
`unparsed`). Re-running into the
same `--out` is idempotent (`triage_verdicts.json` accumulates by `paper_id:number`).

## Triage the residue (Stage 3, an interactive LLM agent)

```sh
mise exec -- python skills/hallucite/scripts/triage.py worklist --out out          # add --pending to skip done
mise exec -- python skills/hallucite/scripts/triage.py worklist --paper <id> --out out  # one paper's slice
mise exec -- python skills/hallucite/scripts/triage.py status --out out             # per-paper done / pending
```

Stage 3 reads the per-paper JSON the audit has already written, so it can run on finished papers
while the audit is still processing the rest — no need to wait for the whole corpus. Verdicts
accumulate, and `worklist --pending` surfaces only references not yet recorded. To fan triage out,
hand each worker its own `worklist --paper <id>` slice (exact id match) instead of the shared
worklist, so a worker can't grab the wrong paper (e.g. `paper6` vs `paper66`); `record` locks the
verdicts file, so concurrent workers don't lose each other's verdicts.

Hand the worklist to an interactive LLM agent such as Claude Code or Codex CLI ("triage the
unverified references in `out`"), or use the installed plugin (below). The agent classifies each reference
**title-first**: a `partial-match` is a real, locatable publication with the cited title but a
slipped metadata field (a citation error); a title that matches no real publication is
`likely-hallucinated`, not a partial-match — even when a different paper by the same authors exists.
Categories: `real-published`, `real-grey-literature`, `real-preprint-or-unpublished`,
`partial-match`, `likely-hallucinated`, `unclear`. The agent records verdicts with structured
fabrication signals, then assembles the reports:

```sh
mise exec -- python skills/hallucite/scripts/triage.py record <paper_id> <number> <category> "<finding>" \
  --signals '{"title_match":"no","authors_match":"yes","venue_match":"no","doi_status":"none"}' --out out
mise exec -- python skills/hallucite/scripts/triage.py report --out out
```

`record` enforces the title-first rule via `--signals`: `partial-match` needs `title_match=yes`
(plus a `matched_title`) or `na`; `likely-hallucinated` needs `title_match=no`. `report` writes to
`out/reports/`: `reference-check-<paper>.md` (per paper), `potential-hallucinations.md` (corpus
rollup for review — a severity table, then a **Desk-reject candidates** section listing references
whose cited title matches no real publication, compounded by a fabricated author constellation,
venue, or DOI), and `verify-<paper>.md` (a manual-check sheet for each flagged paper, with a
per-reference verdict line, the matched title, the signals, and one-click Scholar/Google/DOI/arXiv
links). Triage is the slow step that calls an LLM; do one paper at a time unless you ask for the
whole corpus.

## Updating the offline DBLP database

Recent papers cite recent work, so an out-of-date database produces false "not found" results.
The audit checks the database's age at run time and prints a warning when `~/hallucite/dblp.db`
is more than 30 days old. Rebuild it with `mise run build-dblp`.

## Install as a plugin

```sh
claude plugin marketplace add se-uhd/hallucite      # GitHub once pushed, or a local clone path
claude plugin install hallucite@se-uhd
```

For Codex CLI, install from a pushed release tag for normal use:

```sh
codex plugin marketplace add se-uhd/hallucite --ref v1.7.0
codex plugin list --marketplace se-uhd
codex plugin add hallucite@se-uhd
```

For local development, you can register a local checkout instead:

```sh
codex plugin marketplace add /path/to/hallucite
codex plugin add hallucite@se-uhd
```

The local path install uses the `plugins/hallucite -> ..` compatibility shim and may copy the
current working tree into Codex's plugin cache, including ignored local directories. Use a clean
checkout when testing local installs.

Then in any session: "check the references in `<dir>` for hallucinations" (or `/hallucite` in
Claude Code). The skill (`skills/hallucite/SKILL.md`) resolves the bundled
`skills/hallucite/scripts/run.sh` from a Claude plugin install, a Codex repo-local skill shim, a
direct repo clone, or the Codex plugin cache. That wrapper is the single entry point
(`doctor | audit | triage | lint | python`). Installed plugins do not need mise: on first use
`run.sh` provisions a Python 3.12 that can `import hallucinator` at
`${XDG_CACHE_HOME:-~/.cache}/hallucite/venv` (preferring `uv`, else a stdlib `venv` over a
discovered 3.12), reuses it on later runs, and fails loud with a `HALLUCITE_BOOTSTRAP_FAILED:`
line rather than running half-configured. Set `$HALLUCITE_PYTHON` to reuse an existing
hallucinator environment and skip provisioning. You still build the offline DBLP database once
(see Setup). `run.sh doctor` reports whether the environment is ready.

## Tests and linting

```sh
python skills/hallucite/scripts/tests/run_smoke.py
```

A dependency-light smoke suite, also run in CI by `.github/workflows/smoke.yml`: version and
Claude/Codex packaging consistency, logic-contract checks on the per-paper JSON (including a guard
that a `mismatch` reference reaches triage), Markdown lint, and an offline end-to-end audit against
a tiny generated fixture DBLP database and a synthetic fixture PDF.

The repo's Markdown is checked with a vendored PyMarkdown (synced from
[se-uhd/pymarkdown-skill](https://github.com/se-uhd/pymarkdown-skill); self-contained under
`skills/hallucite/scripts/`, no pip install):

```sh
mise run lint-md            # check every tracked Markdown file
MD_FIX=1 mise run lint-md   # auto-fix in place
```

## Contributing

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
(`type(scope): summary`, for example `fix(extract): ...`); keep the release version out of the
message and record it with a `v*` git tag instead. Run `mise run lint-md` and the smoke tests
(`python skills/hallucite/scripts/tests/run_smoke.py`) before a release.
