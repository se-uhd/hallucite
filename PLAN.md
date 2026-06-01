# hallucite: design and architecture

Finds fabricated ("hallucinated") references in academic paper PDF files and produces a triaged
list of suspects for human review. Verification runs against academic databases first; only
references no database can confirm reach the LLM step.

Papers are identified by their id, the PDF file name (a file `paper1.pdf` has id `paper1`).

## Pipeline

1. Extract (`pdf_references.py`): pull every reference from a paper's PDF file.
2. Verify (`audit_references.py`): check each against DBLP (local offline database), CrossRef, arXiv,
   OpenAlex, Semantic Scholar, and other open bibliographic databases. Anything a database
   confirms is cleared. No LLM.
3. Triage (`triage.py` with an interactive LLM agent): investigate only the database-unverified
   residue (DOI and publisher pages, Google Scholar, web search) and classify each **title-first** --
   first ask whether a publication bearing the cited title exists at all, then whether its metadata
   matches. A reference whose cited title matches no real publication is a fabrication
   (`likely-hallucinated`), distinct from a real, locatable work cited with a slipped field
   (`partial-match`); finding a different paper by the same authors does not make the cited title
   real. The agent records a structured set of fabrication signals with each verdict and writes the
   reports. To fan out across papers, `triage.py worklist --paper <id>` emits one paper's slice by
   exact id match, so a worker reads only its own references.

## Built on hallucinator

Per-reference parsing and database verification reuse the
[`hallucinator`](https://github.com/gianlucasb/hallucinator) package: `PdfExtractor.parse_reference(text)`
for a single clean reference, and `Validator` / `ValidatorConfig` for concurrent multi-DB
verification with offline DBLP (`dblp_offline_path`), author-aware fuzzy matching, and retraction
detection.

hallucinator's built-in `extract()` (which reads the whole PDF file) is not used: many paper PDF
files use the LaTeX `lineno` margin numbers (and some are two-column), which its MuPDF reader
interleaves into the text and so mangles titles and DOIs. Instead `pdf_references.py` does the PDF-to-references step: `pdftotext
-layout`, split two-column pages at the gutter, strip margin line numbers, find the References
section, auto-detect the entry style (numeric / bracket-label / author-year), segment with a
sequentiality guard, then hand each clean reference string to `parse_reference` (with
`min_title_words=1` for short book titles and a prefix-trim retry for venue tails), which
reliably yields 0 unparsed references.

## DBLP dump

`hallucinator-cli update-dblp` builds the offline DB from DBLP's RDF N-Triples dump (~4.6 GB)
into a ~2.5 GB SQLite + FTS5 file (8.4 M publications) at `~/hallucite/dblp.db` (or
`$HALLUCITE_DBLP` if set), outside the repo (not committed). The audit checks the database's age at run time and warns when it is over 30
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
    "db_verification": {"status": "verified", "source": "DBLP Offline", "paper_url": "...", "db_results": [...]}
  }]
}
```

A reference goes to triage when `db_verification.status` is anything other than `verified`
(`not_found`, `mismatch`, or `unparsed`); every reference is thus verified, unverified, or pending
(`--no-verify`), and the audit derives the `unverified` count by negation so that a new
hallucinator status cannot silently fall through uncounted. Triage verdicts are not written back
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
so a reviewer sees the discriminating fact without re-investigating.

## Tests

`skills/hallucite/scripts/tests/run_smoke.py` is a dependency-light smoke suite (run by
`.github/workflows/smoke.yml` on push and pull request, and locally before a release): version and
Claude/Codex packaging consistency (including that `SKILL.md` drives the pipeline via `run.sh`,
carries the stop conditions, and documents every runner resolver branch); the `run.sh` bootstrap
contract (syntax, unknown-command rejection, fail-loud with the sentinel when its Python cannot
import hallucinator, and subcommand+argument forwarding); logic-contract unit tests on synthetic
per-paper records (a `mismatch` reference reaches triage; the title-first record gate; the verdicts
lock under concurrent writes; per-paper worklist slice isolation, including the `paper6`/`paper66`
prefix case; and the desk-reject heuristic); Markdown lint; an optional isolated Codex CLI
marketplace-list check when `codex` is installed; and an offline end-to-end audit (driven through
`run.sh`) against a generated fixture DBLP database and a synthetic fixture PDF. The full DBLP
database, the online backends, and `run.sh`'s network auto-provision path are not exercised in CI.

## Packaging

One repo (`se-uhd/hallucite`) is the runnable project and an installable plugin for Claude Code and
Codex CLI. Claude Code uses `.claude-plugin/plugin.json` plus
`.claude-plugin/marketplace.json` (name `se-uhd`, plugin `source "./"`). Codex CLI uses
`.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` (name `se-uhd`, plugin
`source.path "./plugins/hallucite"`), `plugins/hallucite -> ..` as the marketplace compatibility
shim, and `.agents/skills/hallucite -> ../../skills/hallucite` for repo-local skill discovery.
The scripts live once in `skills/hallucite/scripts/`, used by mise and by the bundled skill.
Generated artifacts under `out/` are gitignored. See `README.md` for commands.

The skill drives the scripts through `skills/hallucite/scripts/run.sh`, a single entry point
(`check-env | audit | triage | lint | python`). It resolves the wrapper from a Claude Code plugin
install, the Codex repo-local skill shim, a direct repo clone, or the Codex plugin cache (preferring
`se-uhd/hallucite` and then any cached `hallucite`, with the lexicographically highest cached
version). The wrapper resolves or, on first use, provisions a Python 3.12 that can
`import hallucinator` (preferring `uv`, else a stdlib `venv` over a 3.12 found on PATH, in common
install dirs, or via `mise where`), so installed plugins do not depend on a bare
`python`/`uv`/`mise` being on the shell's PATH. On any setup failure it prints a
`HALLUCITE_BOOTSTRAP_FAILED:` sentinel and exits non-zero; `$HALLUCITE_PYTHON` reuses an existing
environment and skips provisioning. This is also the guardrail behind the "never fabricate a
verdict" rule: no script output means no verdict.
