# hallucite: design and architecture

Finds fabricated ("hallucinated") references in academic paper PDF files and produces a triaged
list of suspects for human review. Verification runs against academic databases first; only
references no database can confirm reach the LLM step.

Papers are identified by their id, the PDF file name (a file `paper1.pdf` has id `paper1`).

## Pipeline

1. Extract (`pdf_references.py`): pull every reference from a paper's PDF file.
2. Verify (`audit_references.py`): check each against DBLP (local offline database), CrossRef,
   DOI resolution, arXiv and Semantic Scholar. Anything a database confirms is cleared. No LLM.
3. Triage (`triage.py` with an interactive LLM agent): investigate only the database-unverified
   residue (DOI and publisher pages, Google Scholar, web search) and classify each **title-first** --
   first ask whether a publication bearing the cited title exists at all, then whether its metadata
   matches. A reference whose cited title matches no real publication is a fabrication
   (`likely-hallucinated`), distinct from a real, locatable work cited with a slipped field
   (`partial-match`); finding a different paper by the same authors does not make the cited title
   real. The agent records a structured set of fabrication signals with each verdict and writes the
   reports. To fan out across papers, `triage.py worklist --paper <id>` emits one paper's slice by
   exact id match, so a worker reads only its own references.

## Extraction, parsing and verification

Three modules, all standard library. `pdf_references.py` does the PDF-to-references step:
`pdftotext -layout`, drop the running head and footer, split two-column pages at the gutter, strip
margin line numbers, find the References section, auto-detect the entry style (numeric /
bracket-label / author-year), segment -- the numbered styles on a sequentiality guard, the
author-first ones on their hanging indent, which is the only mark an Elsevier or Springer journal
entry carries on its first line -- then hand each clean reference string to
`reference_parser.parse_reference`, which reliably yields 0 unparsed references. A numbered
bibliography reports the entry numbers it prints that no reference carries.

`verifier.py` then asks five backends, cheapest first, each only about the references the ones
before it did not match: the offline DBLP mirror through `dblp_check.py`, CrossRef's bibliographic
search, DOI resolution, arXiv by identifier, and Semantic Scholar where a key is configured.
Nothing is decided on a similarity score: a backend confirms only when a record's title matches
after normalisation and its authors match on an initial-and-surname fingerprint. `build_dblp.py`
builds the mirror from the DBLP dump. `VERIFICATION-SPEC.md` is the contract the parse and check
halves meet.

The head is removed first because it defeats gutter detection: it spans both columns, so the
column gap is not blank on its line, and a page short enough for that one line to matter loses its
column split and every reference in the right-hand column with it. A numbered bibliography catches
such a loss, because it is the one invariant that costs nothing to check: it numbers itself
consecutively, so extraction reports any printed entry number no reference carries, and the audit
warns about it. Nothing later in the pipeline can. A reference that never arrives cannot be
reported as unverified.

`dblp_check.py` answers over *all* records sharing the cited title rather than the one an FTS
query ranks first: "Experimentation in Software Engineering" is three book editions, a 1986 TSE
article, a 1997 survey and a 2008 conference paper, and comparing a citation against whichever
comes back first is how a real work gets reported missing. Retrieval is generous -- both readings
of a hyphen, both foldings of a stroked letter, a word-wise AND, and a fragment-gluing fallback for
a word the layout split with no hyphen -- and the decision is strict: exact normalized-title
equality plus a match of every cited name that reads as a person. The audit also retries a failed
reference with its line-break-join hyphens removed, since the kept-hyphen form defeats FTS phrase
matching.

## DBLP dump

`build_dblp.py` builds the offline DB from DBLP's XML dump (~1 GB compressed) into a ~3.5 GB
SQLite + FTS5 file (8.7 M publications, 4.3 M authors) at `~/hallucite/dblp.db` (or
`$HALLUCITE_DBLP` if set), outside the repo (not committed). It takes about five minutes and
resolves the dump's character entities as numeric references, so the authors whose names carry a
diacritic survive the ingest -- an ingest that drops them makes the mirror disagree with references
that are cited correctly. The audit checks the database's age at run time and warns when it is over 30
days old; rebuild with `mise run build-dblp`.

## Per-paper JSON (the contract between stages)

`audit_references.py` writes one record per paper, named by `paper_id` (the PDF file name):

```jsonc
{
  "paper_id": "paper1",
  "pdf_path": "paper1.pdf",   // relative to the run directory
  "num_references": 16,
  "extraction": {"style": "numeric", "lineno_on": true, "section_found": true, "parsed": 16, "unparsed": 0},
  "references": [{
    "original_number": 5,
    "raw_citation": "...",
    "parsed": {"title": "...", "authors": ["..."], "doi": "...", "arxiv_id": null},
    "db_verification": {"status": "verified", "source": "DBLP", "paper_url": "...", "db_results": [...]}
  }]
}
```

A reference goes to triage when `db_verification.status` is anything other than `verified`
(`not_found`, `mismatch`, or `unparsed`); every reference is thus verified, unverified, or pending
(`--no-verify`), and the audit derives the `unverified` count by negation so that a status added
later cannot silently fall through uncounted. Triage verdicts are not written back
into this file: `triage.py record` stores them
separately in `triage_verdicts.json`, keyed `"<paper_id>:<number>"` (resumable). Each verdict
carries its category, a one-line finding, and structured fabrication signals (`title_match`,
`matched_title`, `authors_match`, `venue_match`, `doi_status`). `record` takes an `fcntl` lock on
the file so parallel workers do not lose each other's verdicts, and enforces the title-first rule:
a `partial-match` must name a matched real title (`title_match=yes` plus `matched_title`, or `na`
for a non-publication resource) and a `likely-hallucinated` must assert the title was not found
(`title_match=no`). `triage.py report` joins the two when it assembles the reports.

## Reports

`triage.py report` writes to `out/reports/`: `reference-check-<paper>.md` (per paper),
`potential-hallucinations.md` (corpus rollup, led by a per-paper severity table and a **Desk-reject
candidates** section -- references whose cited title matches no real publication), and
`verify-<paper>.md` (a manual-check sheet for each flagged paper, with the matched title, the
signal summary, and one-click search links). The rollup shows each flag's cited-vs-matched title,
so a reviewer sees the discriminating fact without re-investigating. The per-paper report and the
sheet print what the audit knew about each unverified reference under its DB status: the backends
that were never asked (`skipped`, so a `not_found` with the mirror among them was never put to
it), DBLP's record where one carries the cited title or its nearest title where none does (within
two word edits, and only with every cited author on it), what each cited DOI or arXiv id resolves
to and whether that is the cited title, and what each backend matched. The worklist entry carries
the same fields (`skipped_dbs`, `dblp_record`, `dblp_nearest`, `identifiers`, `matched`).

## Tests

`skills/hallucite/scripts/tests/run_smoke.py` is a dependency-light smoke suite (run by
`.github/workflows/smoke.yml` on push and pull request, and locally before a release): version and
Claude/Codex packaging consistency (including that `SKILL.md` drives the pipeline via `run.sh`,
carries the stop conditions, and documents every runner resolver branch); the `run.sh` bootstrap
contract (syntax, unknown-command rejection, fail-loud with the sentinel when its Python is
unusable, and subcommand+argument forwarding); logic-contract unit tests on synthetic
per-paper records (a `mismatch` reference reaches triage; the title-first record gate; the verdicts
lock under concurrent writes; per-paper worklist slice isolation, including the `paper6`/`paper66`
prefix case; and the desk-reject heuristic); an optional isolated Codex CLI
marketplace-list check when `codex` is installed; and an offline end-to-end audit (driven through
`run.sh`) against a generated fixture DBLP database and a synthetic fixture PDF. Markdown lint
runs as a separate CI step (`lint_markdown.py` over the tracked Markdown files; locally,
`mise run lint-md`). The full DBLP database, the online backends, and `run.sh`'s network
auto-provision path are not exercised in CI.

## Packaging

One repo (`se-uhd/hallucite`) is the runnable project and an installable plugin for Claude Code and
Codex CLI. Claude Code uses `.claude-plugin/plugin.json` plus
`.claude-plugin/marketplace.json` (name `hallucite`, plugin `source "./"`). Codex CLI uses
`.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` (name `hallucite`, plugin
`source.path "./plugins/hallucite"`), `plugins/hallucite -> ..` as the marketplace compatibility
shim, and `.agents/skills/hallucite -> ../../skills/hallucite` for repo-local skill discovery.
The scripts live once in `skills/hallucite/scripts/`, used by mise and by the bundled skill.
Generated artifacts under `out/` are gitignored. See `README.md` for commands.

The skill drives the scripts through `skills/hallucite/scripts/run.sh`, a single entry point
(`check-env | audit | triage | lint | python`). It resolves the wrapper from a Claude Code plugin
install, the Codex repo-local skill shim, a direct repo clone, or the Codex plugin cache (preferring
the `hallucite` marketplace's cached plugin and then any cached `hallucite`, with the highest
cached version, compared with `sort -V`). The wrapper resolves a Python 3.10 or newer with
`sqlite3` (on PATH, in the common install dirs, or via `mise where`), so installed plugins do not
depend on a bare `python`/`uv`/`mise` being on the shell's PATH. There is nothing to install: the
pipeline is standard library only. On any setup failure it prints a `HALLUCITE_BOOTSTRAP_FAILED:`
sentinel and exits non-zero; `$HALLUCITE_PYTHON` pins an interpreter. This is also the guardrail behind the "never fabricate a
verdict" rule: no script output means no verdict.
