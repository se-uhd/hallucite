---
name: hallucite
description: >-
  Detect hallucinated (fabricated) references in academic paper PDF files. Use when the user asks
  to check, audit, or verify the references/bibliography of one or more papers for hallucinated or
  fabricated citations, or names a paper PDF file (or directory of PDF files) to check. Extracts each
  reference, verifies it against academic databases (offline DBLP plus CrossRef/arXiv/OpenAlex)
  without using an LLM, then triages only the database-unverified residue via web search and writes
  a report of likely-hallucinated references plus per-paper manual-verification sheets.
license: MIT
compatibility: Requires Python 3.12, the hallucinator pip package, pdftotext (poppler), and a prebuilt offline DBLP database at ~/hallucite/dblp.db (override the location with $HALLUCITE_DBLP). Tool-agnostic; usable by any agent that can run the scripts. Only the plugin/marketplace packaging is Claude Code-specific.
metadata:
  version: "1.4.1"
---

# hallucite

Detect fabricated references in academic paper PDF files. Three stages: extract and verify are
local and deterministic (no LLM); triage is the only step that uses an LLM (cloud or local), run
on the references that no database could confirm.

The pipeline scripts live in this skill's `scripts/` directory (`pdf_references.py`,
`audit_references.py`, `triage.py`). Run them with a Python that has `hallucinator` installed.
When the skill is installed as a plugin, reference them under `${CLAUDE_PLUGIN_ROOT}`:

```sh
SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/hallucite/scripts"
```

(In a clone of the repo you can instead run `mise run audit`.)

## Setup (once)

1. `pip install hallucinator`. It ships CPython 3.12 wheels; on 3.13 pip builds from source, so a
   3.12 venv is the easy path (`uv venv -p 3.12`).
2. Build the offline DBLP database with the hallucinator CLI (prebuilt binary from
   `https://github.com/gianlucasb/hallucinator/releases/latest`, checksum-verified, or
   `cargo install hallucinator-cli`):
   `hallucinator-cli update-dblp ~/hallucite/dblp.db` (about 4.6 GB download, 20-30 min, builds
   a ~2.5 GB SQLite+FTS5 file). Keep it outside protected dirs such as ~/Downloads. To store it
   elsewhere, set `$HALLUCITE_DBLP` to the target path and pass that path here instead.
3. Updates: the audit (Stage 1+2 below) checks the database's age at run time and warns when it is
   over 30 days old. Recent papers cite recent work, so rebuild it when that warning appears.

## Resolve the target

A directory of PDF files, or a single `<file>.pdf`. Given a bare paper number or name, resolve it
against the directory the user means (ask if ambiguous).

## Stage 1+2: extract and verify (no LLM)

```sh
python "$SCRIPTS"/audit_references.py <pdf-file-or-dir> --out <outdir> --mailto <your-email>
```

Writes `<outdir>/<paper_id>.json` (every reference, parsed fields plus per-database verification)
and `<outdir>/summary.json`. The offline DBLP DB defaults to `$HALLUCITE_DBLP` (else
`~/hallucite/dblp.db`); override it with `--dblp PATH`. Flags: `--offline` (DBLP-only, no
network), `--no-verify` (extraction only). Extraction is `lineno`- and two-column-aware and handles numeric,
bracket-label, and author-year bibliographies; the target is 0 unparsed references.

## Stage 3: triage the residue (LLM)

```sh
python "$SCRIPTS"/triage.py worklist --out <outdir>             # -> <outdir>/triage_worklist.json
python "$SCRIPTS"/triage.py worklist --pending --out <outdir>   # only refs not yet recorded
python "$SCRIPTS"/triage.py status --out <outdir>               # per-paper done / pending counts
```

These read the per-paper JSON the audit has already written, so Stage 3 can run on finished
papers while Stage 1+2 is still processing the rest. Verdicts accumulate per `<paper_id>:<number>`,
and `--pending` surfaces only the references that have not been recorded yet.

For each entry (references whose `db_verification.status` is anything other than `verified` --
`not_found`, `mismatch`, or `unparsed`), investigate with parallel web queries and classify it:

- Search in escalating breadth; only conclude "not found" after the broad pass. Start with the
  DOI (resolve `https://api.crossref.org/works/<doi>`; a 404, or resolution to an unrelated
  paper, is a strong fabrication signal), then the exact title in quotes plus the first-author
  surname (and `site:arxiv.org "<title>"`), then the exact title in quotes alone and on Google
  Scholar.
- If those find nothing, drop the quotes and search the title as plain keywords, then read the
  results for a genuine match. Obscure or predatory venues are poorly indexed, so a narrow query
  returning nothing is not evidence of fabrication; broaden first, and fetch the venue page or
  any embedded DOI/URL directly.
- Fabrication signatures: non-existent or defunct journals, an impossible volume/year,
  initials-only generic authors, real researchers' names attached to a non-existent title,
  placeholder arXiv IDs such as `2310.XXXX`.

Categories: `real-published`, `real-grey-literature`, `real-preprint-or-unpublished` (low);
`partial-match` (a real paper exists but the title/author/venue/DOI is wrong: a citation error,
medium); `likely-hallucinated` (no such paper after a thorough search, high); `unclear` (no
confident verdict; leave for a human). `unclear` is a valid verdict. Do not push borderline cases
to `real-*` to make the report look clean.

Record each verdict (it persists immediately and is resumable):

```sh
python "$SCRIPTS"/triage.py record <paper_id> <number> <category> "<finding>" --out <outdir>
```

Then assemble the reports:

```sh
python "$SCRIPTS"/triage.py report --out <outdir>
```

- `<outdir>/reports/reference-check-<paper_id>.md`: per paper.
- `<outdir>/reports/potential-hallucinations.md`: corpus rollup for human review, led by a
  per-paper severity table.
- `<outdir>/reports/verify-<paper_id>.md`: for each paper with flags, a manual-verification
  checklist (per-reference verdict line plus one-click Scholar/Google/DOI/arXiv links).

`report` auto-lints every file it writes with the bundled Markdown linter
(`lint_markdown.py`), so the reports are valid GFM without a manual pass.

## Notes

- Triage is the slow step that calls an LLM. Default to one paper at a time; confirm before the whole corpus.
- Most database-unverified references are real but uncovered (books, standards, tech reports,
  vendor docs, preprints). Verify them; do not assume fabrication. Genuine hallucinations cluster
  and show the signatures above. A "hallucinated" call against named authors is serious: flag it
  for review, do not accuse.
