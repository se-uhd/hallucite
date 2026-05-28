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
3. Triage (`triage.py` with an interactive LLM agent): investigate only the database-unverified residue (DOI
   and publisher pages, Google Scholar, web search), classify each, and write the reports.

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
into a ~2.5 GB SQLite + FTS5 file (8.4 M publications) at `~/hallucite/dblp.db`, outside the
repo (not committed). The audit checks the database's age at run time and warns when it is over 30
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

A reference goes to triage when `db_verification.status` is `not_found`, `author_mismatch`, or
`unparsed`. Triage verdicts are not written back into this file: `triage.py record` stores them
separately in `triage_verdicts.json`, keyed `"<paper_id>:<number>"` (resumable), and
`triage.py report` joins the two when it assembles the reports.

## Reports

`triage.py report` writes to `out/reports/`: `reference-check-<paper>.md` (per paper),
`potential-hallucinations.md` (corpus rollup, led by a per-paper severity table), and
`verify-<paper>.md` (a manual-check sheet with one-click search links for each flagged paper).

## Packaging

One repo (`se-uhd/hallucite`) is the runnable project and an installable Claude Code plugin: its
root is the plugin (`.claude-plugin/plugin.json`) and its own single-plugin marketplace
(`.claude-plugin/marketplace.json`, name `se-uhd`, plugin `source "./"`). The scripts live once
in `skills/hallucite/scripts/`, used both by mise and by the bundled skill (`skills/hallucite/SKILL.md`
references them via `${CLAUDE_PLUGIN_ROOT}`). Generated artifacts under `out/` are gitignored.
See `README.md` for commands.
