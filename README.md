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

One repo serves two roles. It is the runnable project (the mise tasks below) and an installable
Claude Code plugin: the repo root is the plugin, and `.claude-plugin/marketplace.json` makes it
its own single-plugin marketplace. The bundled skill in `skills/hallucite/` drives the same
scripts.

## Setup (once)

Run from this directory. Requires [mise](https://mise.jdx.dev).

```sh
mise install          # provision Python 3.12 + uv (auto-venv)
mise run install      # uv pip install -r requirements.txt  (hallucinator)
mise run install-cli  # download the hallucinator CLI binary into .bin/ (checksum-verified)
mise run build-dblp   # build the offline DBLP database at ~/hallucite/dblp.db (~4.6 GB, ~20-30 min)
```

The offline DBLP database lives at `~/hallucite/dblp.db`, outside this repo, which keeps the
2.5 GB file out of git.

## Run the audit (Stages 1+2, no LLM)

```sh
mise run audit -- <pdf-file-or-dir>            # required: a PDF file, or a directory of PDF files
mise run audit -- <pdf-file-or-dir> <out-dir>  # optional 2nd arg sets the output dir (default: out)
```

Writes `out/<paper_id>.json` (every reference plus per-database verification) and
`out/summary.json` (status counts plus the DBLP build date). Options: `--dblp PATH`, `--out DIR`,
`--mailto EMAIL`, `--offline` (DBLP-only), `--no-verify`. A reference needs triage when its
`db_verification.status` is `not_found`, `author_mismatch`, or `unparsed`. Re-running into the
same `--out` is idempotent (`triage_verdicts.json` accumulates by `paper_id:number`).

## Triage the residue (Stage 3, an interactive LLM agent)

```sh
mise exec -- python skills/hallucite/scripts/triage.py worklist --out out   # add --pending to skip done
mise exec -- python skills/hallucite/scripts/triage.py status --out out      # per-paper done / pending
```

Stage 3 reads the per-paper JSON the audit has already written, so it can run on finished papers
while the audit is still processing the rest — no need to wait for the whole corpus. Verdicts
accumulate, and `worklist --pending` surfaces only references not yet recorded.

Hand the worklist to an interactive LLM agent such as Claude Code ("triage the unverified
references in `out`"), or use the installed plugin (below). The agent checks each reference on the web,
classifies it (`real-published`,
`real-grey-literature`, `real-preprint-or-unpublished`, `partial-match`, `likely-hallucinated`,
`unclear`), records verdicts, then assembles the reports:

```sh
mise exec -- python skills/hallucite/scripts/triage.py record <paper_id> <number> <category> "<finding>" --out out
mise exec -- python skills/hallucite/scripts/triage.py report --out out
```

`report` writes to `out/reports/`: `reference-check-<paper>.md` (per paper),
`potential-hallucinations.md` (corpus rollup for review, severity table first), and
`verify-<paper>.md` (a manual-check sheet for each flagged paper, with a per-reference verdict
line and one-click Scholar/Google/DOI/arXiv links). Triage is the slow step that calls an LLM; do
one paper at a time unless you ask for the whole corpus.

## Updating the offline DBLP database

Recent papers cite recent work, so an out-of-date database produces false "not found" results.
The audit checks the database's age at run time and prints a warning when `~/hallucite/dblp.db`
is more than 30 days old. Rebuild it with `mise run build-dblp`.

## Install as a Claude Code plugin

```sh
claude plugin marketplace add se-uhd/hallucite      # GitHub once pushed, or a local clone path
claude plugin install hallucite@se-uhd
```

Then in any session: "check the references in `<dir>` for hallucinations" (or `/hallucite`). The
skill (`skills/hallucite/SKILL.md`) invokes the bundled `skills/hallucite/scripts/` via
`${CLAUDE_PLUGIN_ROOT}`.

## Linting the docs

The repo's Markdown is checked with a vendored PyMarkdown (synced from
[se-uhd/pymarkdown-skill](https://github.com/se-uhd/pymarkdown-skill); self-contained under
`skills/hallucite/scripts/`, no pip install):

```sh
mise run lint-md            # check every tracked Markdown file
MD_FIX=1 mise run lint-md   # auto-fix in place
```
