<p align="center">
  <img src="assets/logo-readme.png" alt="hallucite logo" width="320">
</p>

# hallucite

Finds fabricated ("hallucinated") references in academic paper PDF files. Each reference is checked
against academic databases (the offline DBLP mirror, then CrossRef, DOI resolution, arXiv and
Semantic Scholar); references that no database can confirm are escalated to an interactive
LLM triage step, which writes a report for human review.

Three stages: extract and verify use no LLM (verification queries the online databases unless
`--offline` restricts it to the offline DBLP mirror); triage is the only step that uses an LLM,
which can be a cloud or a local model. See [PLAN.md](PLAN.md) for the design and architecture.

One repo serves as the runnable project (the mise tasks below) and one shared plugin tree for
Claude Code and Codex CLI. The Claude metadata lives under `.claude-plugin/`; the Codex metadata
lives under `.codex-plugin/` and `.agents/plugins/marketplace.json`. The bundled skill in
`skills/hallucite/` drives the same scripts for both tools.

## Setup (once)

Run from this directory.

| Dependency | Needed for | Install |
|---|---|---|
| [mise](https://mise.jdx.dev) | provisions Python and uv | see mise docs |
| `pdftotext` (poppler) | reference extraction shells out to it | `brew install poppler` |
| `sqlite3` | `build-dblp` checks the database it just built | ships with macOS |
| Playwright + Chromium | `fetch-dblp-dump` only; needs a display | `pip install playwright && playwright install chromium` |

```sh
mise install               # provision Python + uv (auto-venv)
mise run fetch-dblp-dump   # download dblp.xml.gz with a real browser (~1 GB)
mise run build-dblp        # build ~/hallucite/dblp.db from it (~4 min)
```

The pipeline itself has no Python dependencies: extraction, parsing, verification and the DBLP
ingest are all standard library, and `pdftotext` is the only outside program it calls.

The offline DBLP database lives at `~/hallucite/dblp.db`, outside this repo, which keeps the
3.5 GB file out of git. Set `$HALLUCITE_DBLP` to store it somewhere else.

### API keys

Put them in `.env.local` in the repo root, one `NAME=value` per line. The file is gitignored, and
both mise and `skills/hallucite/scripts/run.sh` read it, so the tasks below and the installed
plugin see the same values. A variable already set in the environment wins.

```sh
S2_API_KEY=s2k-...   # Semantic Scholar: https://www.semanticscholar.org/product/api
```

Only Semantic Scholar needs one. Anonymous callers share a small quota, and a rate-limited lookup
leaves a reference degraded rather than cleanly negative, which moves the boundary between
`verified` and "needs triage" between otherwise identical runs. CrossRef wants no key, only the
`--mailto` contact that puts a caller in its faster pool.

## Run the audit (Stages 1+2, no LLM)

```sh
mise run audit -- <pdf-file-or-dir>            # required: a PDF file, or a directory of PDF files
mise run audit -- <pdf-file-or-dir> [options]  # everything after the target is forwarded as-is
```

Writes `out/<paper_id>.json` (every reference plus per-database verification) and
`out/summary.json` (status counts plus the DBLP build date). Options: `--dblp PATH`, `--out DIR`,
`--mailto EMAIL`, `--s2-api-key KEY`, `--offline` (no network; the offline DBLP mirror stays
live), `--disable-dbs LIST` (comma-separated), `--no-verify`, `--no-candidates` (skip the CrossRef
lookup that attaches candidate records; implied by `--offline`), `--rate-limit-retries N`,
`--retry-degraded N` (re-check what a backend failure left degraded; default 1, 0 disables) and
`--retry-delay SECONDS` (default 5). The DBLP path defaults to
`$HALLUCITE_DBLP` (else `~/hallucite/dblp.db`) and the output dir to `out`. A reference the
backends miss is re-verified once with its line-break hyphens removed before it reaches triage.
The DBLP backend checks the cited title and authors against every record sharing that title, and
where several match it reports the published record the citation locates -- the one whose DOI,
page range or volume it prints, and failing those the one whose year it prints. A
reference needs triage when its `db_verification.status` is anything other than `verified`
(`not_found`, `mismatch`, or `unparsed`). Re-running into the same `--out` is idempotent (`triage_verdicts.json` accumulates by `paper_id:number`).

## Triage the residue (Stage 3, an interactive LLM agent)

```sh
mise exec -- python skills/hallucite/scripts/triage.py worklist --out out          # add --pending to skip done
mise exec -- python skills/hallucite/scripts/triage.py worklist --paper <id> --out out  # one paper's slice
mise exec -- python skills/hallucite/scripts/triage.py status --out out             # per-paper done / pending
```

Stage 3 reads the per-paper JSON the audit has already written, so it can run on finished papers
while the audit is still processing the rest. There is no need to wait for the whole corpus. Verdicts
accumulate, and `worklist --pending` surfaces only references not yet recorded. Each worklist entry
carries what the audit knew about the reference: which backends matched it and which were never
asked, CrossRef's closest records, DBLP's record for the cited title or its nearest title under the
same authors, and what a cited DOI or arXiv id resolves to. To fan triage out,
hand each worker its own `worklist --paper <id>` slice (exact id match) instead of the shared
worklist, so a worker can't grab the wrong paper (e.g. `paper6` vs `paper66`); `record` locks the
verdicts file, so concurrent workers don't lose each other's verdicts.

Hand the worklist to an interactive LLM agent such as Claude Code or Codex CLI ("triage the
unverified references in `out`"), or use the installed plugin (below). The agent classifies each reference
**title-first**: a `partial-match` is a real, locatable publication with the cited title but a
slipped metadata field (a citation error); a title that matches no real publication is
`likely-hallucinated`, not a partial-match, even when a different paper by the same authors exists.
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
rollup for review: a severity table, then a **Desk-reject candidates** section listing references
whose cited title matches no real publication, compounded by a fabricated author constellation,
venue, or DOI), and `verify-<paper>.md` (a manual-check sheet for each flagged paper, with a
per-reference verdict line, the matched title, the signals, and one-click Scholar/Google/DOI/arXiv
links). Triage is the slow step that calls an LLM; do one paper at a time unless you ask for the
whole corpus.

## Updating the offline DBLP database

Recent papers cite recent work, so an out-of-date database produces false "not found" results.
The audit checks the database's age at run time and prints a warning when `~/hallucite/dblp.db`
is more than 30 days old. Rebuild it with `mise run build-dblp`, which builds to a scratch file
and swaps it in only after checking that the result is mirror-sized and that accented author names
survived the ingest.

dblp.org and both its mirrors front `dblp.xml.gz` with an Anubis proof-of-work bot check. A plain
HTTP client such as `curl` receives the challenge page instead of the dump, and an ingest reads it
as zero publications, so `build-dblp` verifies what it built before installing it.

`mise run fetch-dblp-dump` drives a real browser, which answers the challenge with its own JS
engine the way it does for a person clicking the link. It has to run headed: Anubis refuses a
headless browser outright ("Access Denied"), while the headed one completes the proof-of-work
normally. On a machine without a display, download the dump on a desktop and copy it over. Either
way, point the build at the file:

```sh
mise run fetch-dblp-dump   # -> ~/hallucite/dblp.xml.gz, where build-dblp looks for it
mise run build-dblp        # set DBLP_XML_GZ to build from a dump kept elsewhere
```

### Why the ingest is ours

DBLP writes Latin-1 letters as the named entities its DTD declares (`M&aacute;rcio Ribeiro`), and
an ingest that cannot resolve them drops the author entirely: `journals/tse/SoaresRGAS23` kept 3 of
its 5, `books/sp/WohlinRHOR00` 3 of its 6. DBLP's own records are complete; the loss happened on
ingest, and it is unsound in exactly one direction -- the mirror then reports an author mismatch
for references that are cited *correctly*, 154 of them across a 2065-reference corpus.

`build_dblp.py` resolves the entities in the byte stream, as numeric character references so the
dump's own ISO-8859-1 declaration cannot turn them back into mojibake, and `build-dblp` refuses to
swap in a database whose authors carry no diacritic at all. The audit reads the same property off
whatever mirror it is handed and stops holding an absence against a citation when the mirror cannot
support one. Checked against 5000 records of a mirror built by the previous Rust ingest, all 5000
agree on title, year, type, electronic edition and the full author list.

## Install as a plugin

```sh
claude plugin marketplace add se-uhd/hallucite      # GitHub, or a local clone path
claude plugin install hallucite@hallucite
```

For Codex CLI, add the marketplace and install the plugin:

```sh
codex plugin marketplace add se-uhd/hallucite
codex plugin list --marketplace hallucite
codex plugin add hallucite@hallucite
```

To update later:

```sh
codex plugin marketplace upgrade hallucite
codex plugin add hallucite@hallucite
```

For local development, you can register a local checkout instead:

```sh
codex plugin marketplace add /path/to/hallucite
codex plugin add hallucite@hallucite
```

The local path install uses the `plugins/hallucite -> ..` compatibility shim and may copy the
current working tree into Codex's plugin cache, including ignored local directories. Use a clean
checkout when testing local installs.

Then in any session: "check the references in `<dir>` for hallucinations" (or `/hallucite` in
Claude Code). The skill (`skills/hallucite/SKILL.md`) resolves the bundled
`skills/hallucite/scripts/run.sh` from a Claude plugin install, a Codex repo-local skill shim, a
direct repo clone, or the Codex plugin cache. That wrapper is the single entry point
(`check-env | audit | triage | lint | python`). Installed plugins do not need mise:
`run.sh` finds a Python 3.10 or newer with `sqlite3` -- searching PATH and the places a
plugin's non-interactive shell tends to miss -- and fails loud with a
`HALLUCITE_BOOTSTRAP_FAILED:` line rather than running half-configured. There is nothing to
install: the pipeline is standard library only. Set `$HALLUCITE_PYTHON` to pin an interpreter.
You still build the offline DBLP database once (see Setup). `run.sh check-env` reports whether the
environment is ready, including a warning when `pdftotext` is missing.

## Tests and linting

```sh
python skills/hallucite/scripts/tests/run_smoke.py
```

Measuring a change to extraction or verification, all offline (`measure/` in the same directory):

```bash
python skills/hallucite/scripts/measure/extraction_census.py ~/hallucite/corpus --out ~/hallucite/census.json
python skills/hallucite/scripts/measure/corruptions.py score ~/hallucite/corruptions.json
python skills/hallucite/scripts/measure/head_to_head.py run --source corpus --refs refs.json out.json
python skills/hallucite/scripts/measure/mutations.py
```

The corruption harness has to come back unchanged from any change to the author or title rules:
250 correct citations confirmed, one, two or three invented names appended confirmed 0. The
head-to-head needs `pip install hallucinator` and nothing else does.

A dependency-light smoke suite, also run in CI by `.github/workflows/smoke.yml`: version and
Claude/Codex packaging consistency, the `run.sh` bootstrap contract, an optional Codex CLI
marketplace check, logic-contract checks on the per-paper JSON (including a guard that a
`mismatch` reference reaches triage), and an offline end-to-end audit against a tiny generated
fixture DBLP database and a synthetic fixture PDF. Markdown lint runs as a separate CI step;
locally, run `mise run lint-md` (below).

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
