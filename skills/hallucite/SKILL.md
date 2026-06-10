---
name: hallucite
description: >-
  Detect hallucinated (fabricated) references in academic paper PDF files. Use when the user asks
  to check, audit, or verify the references/bibliography of one or more papers for hallucinated or
  fabricated citations, or names a paper PDF file (or directory of PDF files) to check. Extracts each
  reference, verifies it against academic databases (offline DBLP plus CrossRef, arXiv, Semantic
  Scholar, and other open databases) without using an LLM, then triages only the
  database-unverified residue via web search and writes a report of likely-hallucinated
  references plus per-paper manual-verification sheets.
license: MIT
compatibility: Requires Python 3.12, the hallucinator pip package, pdftotext (poppler), and a prebuilt offline DBLP database at ~/hallucite/dblp.db (override the location with $HALLUCITE_DBLP). Tool-agnostic; usable by any agent that can run the scripts. Packaged for Claude Code and Codex CLI.
metadata:
  version: "1.8.1"
---

# hallucite

Detect fabricated references in academic paper PDF files. Three stages: extract and verify use no
LLM (verification queries the online databases unless `--offline` restricts it to the local ones);
triage is the only step that uses an LLM (cloud or local), run
on the references that no database could confirm.

## Stop conditions -- never fabricate a verdict

This skill exists to catch fabricated references; it must never produce one. A hallucination
verdict is a serious accusation against named authors, so every claim you make must trace to real
tool output, not to your own reading of a `.bib`/`.bbl`/PDF.

- **No script output ⇒ no verdict.** A reference may be called real, partial-match,
  likely-hallucinated, or unclear **only** on the basis of (a) a Stage 1+2 `db_verification` record
  the audit actually wrote, or (b) Stage 3 web-search evidence you actually gathered. Eyeballing a
  bibliography is not a verification method and never yields a verdict.
- **Treat any non-zero exit or a `HALLUCITE_BOOTSTRAP_FAILED:` line as a blocking error.** Stop,
  report the failure verbatim to the user, and do not work around it by inspecting the references
  yourself. "The tool would not run" is the correct, honest outcome -- not a hand-written report.
- **Run the preflight (`check-env`) first.** If it does not print `HALLUCITE_OK`, the environment is
  not ready; surface its message and stop.
- If commands start erroring or returning empty output, **halt and say so.** Do not begin
  assembling findings from memory or from the source files while the pipeline is broken.

## Running the pipeline

Always invoke the pipeline through the `run.sh` wrapper. It resolves (or, on first use, provisions)
a Python 3.12 that can `import hallucinator`, so you never call a bare `python`/`mise`/`uv` that may
be missing from the plugin's shell. It is the single supported entry point.

```sh
resolve_hallucite_run() {
  # 1. Claude Code plugin install.
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    candidate="${CLAUDE_PLUGIN_ROOT}/skills/hallucite/scripts/run.sh"
    [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  fi

  # 2. Codex repo-local skill discovery shim.
  candidate=".agents/skills/hallucite/scripts/run.sh"
  [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }

  # 3. Direct repo clone.
  candidate="skills/hallucite/scripts/run.sh"
  [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }

  # 4. Codex plugin cache. Prefer the hallucite marketplace's hallucite, then any
  # marketplace's hallucite, choosing the highest cached version (sort -V, so
  # 1.10.0 beats 1.9.0 -- plain lexicographic sort would invert them).
  cache_root="${CODEX_HOME:-$HOME/.codex}/plugins/cache"
  if [ -d "$cache_root" ]; then
    candidate="$(find "$cache_root" -path '*/hallucite/hallucite/*/skills/hallucite/scripts/run.sh' -type f 2>/dev/null | sort -V | tail -n 1)"
    [ -n "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
    candidate="$(find "$cache_root" -path '*/hallucite/*/skills/hallucite/scripts/run.sh' -type f 2>/dev/null | sort -V | tail -n 1)"
    [ -n "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  fi

  printf '%s\n' 'HALLUCITE_BOOTSTRAP_FAILED: cannot locate hallucite scripts/run.sh' >&2
  return 3
}

RUN="$(resolve_hallucite_run)" || exit $?
```

Subcommands: `run.sh check-env` (preflight), `audit ...`, `triage ...`, `lint ...`,
`python ...`.
On success it is transparent (runs the script, forwards its exit code); on a setup failure it
prints `HALLUCITE_BOOTSTRAP_FAILED: <reason>` to stderr and exits non-zero -- that sentinel means
**no audit ran**, so there is nothing to interpret.

First run builds a cached venv at `${XDG_CACHE_HOME:-~/.cache}/hallucite/venv` (needs `uv` or a
Python 3.12, plus network for `pip install hallucinator`); set `$HALLUCITE_VENV` to relocate it.
Later runs reuse it and are instant.
To reuse an environment that already has hallucinator, set `$HALLUCITE_PYTHON` to its interpreter
and no venv is built. (In a repo clone you can equivalently use the `mise run ...` tasks.)

### Preflight (every session, before any audit)

```sh
"$RUN" check-env    # must print `HALLUCITE_OK: <python> (hallucinator <version>)`
```

If it prints `HALLUCITE_BOOTSTRAP_FAILED:` instead, relay that line to the user and stop -- see the
stop conditions above.

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
"$RUN" audit <pdf-file-or-dir> --out <outdir> --mailto <your-email>
```

Writes `<outdir>/<paper_id>.json` (every reference, parsed fields plus per-database verification)
and `<outdir>/summary.json`. The offline DBLP DB defaults to `$HALLUCITE_DBLP` (else
`~/hallucite/dblp.db`); override it with `--dblp PATH`. Flags: `--offline` (no network: offline
DBLP plus hallucinator's built-in Standards matcher; a missing DBLP file disables DBLP rather
than falling back to dblp.org), `--disable-dbs LIST` (disable named backends, comma-separated),
`--no-verify` (extraction only). Extraction is `lineno`- and two-column-aware and handles numeric,
bracket-label, and author-year bibliographies; the target is 0 unparsed references.

If this exits non-zero -- whether a `HALLUCITE_BOOTSTRAP_FAILED:` line (no Python/hallucinator) or
a per-paper error from the audit -- stop and report it; do not infer verdicts by hand (see the stop
conditions above).

## Stage 3: triage the residue (LLM)

```sh
"$RUN" triage worklist --out <outdir>             # -> <outdir>/triage_worklist.json
"$RUN" triage worklist --pending --out <outdir>   # only refs not yet recorded
"$RUN" triage worklist --paper <paper_id> --out <outdir>  # one paper's slice
"$RUN" triage status --out <outdir>               # per-paper done / pending counts
```

These read the per-paper JSON the audit has already written, so Stage 3 can run on finished
papers while Stage 1+2 is still processing the rest. Verdicts accumulate per `<paper_id>:<number>`,
and `--pending` surfaces only the references that have not been recorded yet.

To fan triage out across papers, give each worker its own slice with
`worklist --paper <paper_id>` (exact id match, written to `triage_worklist-<paper_id>.json`)
rather than the shared worklist -- a worker that self-filters the corpus-wide file by id can grab
the wrong paper (e.g. `paper6` vs `paper66`); the per-paper slice removes that step and errors out
on an unknown id. `record` takes an exclusive lock on the verdicts file, so concurrent workers can
record in parallel without losing each other's verdicts.

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
Classify title-first. Two independent questions, asked in order -- do not collapse them:

1. **Does a publication bearing the cited title exist?** Match on the *title* (allowing only
   trivial OCR/formatting/word-order differences, never a different topic). Finding a real paper
   by the same authors, or in the same venue, with a *different* title does **not** answer yes --
   that is a different work, and the cited one still does not exist.
2. **Only if step 1 is yes:** are the metadata fields (authors, venue, year, volume/pages, DOI)
   consistent with that real publication?

Match the title on meaning, not exact string, in two steps:

- *Formatting-only differences are the same title* (`title_match=yes`, normally `real-*`): a present
  or absent subtitle, spacing, hyphenation (including line-break hyphens such as `distribu-tional`),
  capitalization, punctuation, `&` vs `and`, diacritics, ligatures, other OCR/extraction artifacts,
  and British/American spelling.
- *A wrong, missing, or added content word* (one that changes what the work is about -- `PLS` where
  the real paper says `cluster analysis`) still counts as `title_match=yes` **only if an independent
  identifier pins the citation to one specific real publication**: a DOI that resolves to it, or an
  exact author+venue+year(+pages) match. Then record that publication as `matched_title` and use
  `partial-match` -- the wrong title is the citation error. If only a loose resemblance links it to a
  real work -- a shared title template, the same topic, or a single shared author, with no resolving
  identifier -- the cited title names no real publication: `title_match=no` (`likely-hallucinated`,
  or `unclear` if you cannot tell).

Then assign the category:

- `real-published` / `real-grey-literature` / `real-preprint-or-unpublished` (low): a publication
  with the cited title exists and the metadata matches.
- `partial-match` (citation error, medium): a publication with the cited title **exists**, but one
  or two metadata fields are wrong -- wrong year, an off-by-one DOI digit, an abbreviated or
  swapped venue, a misspelled/missing co-author, a wrong first name. State the matched
  publication's *actual title* in the finding to prove the title matched. Regular human mistakes
  look like this: a real, locatable work with a slipped field. **They do not invent titles.**
- `likely-hallucinated` (high): no publication bears the cited title after a thorough escalating
  search. A real author (or real author group) or a real venue attached to a non-existent title is
  the canonical case -- do **not** rescue it to `partial-match` because the authors/venue happen to
  match some other real paper. State explicitly in the finding that no work bears the cited title.
- `unclear` (leave for a human): you cannot establish whether a work with the title exists (e.g. an
  obscure/predatory venue, an embargoed artifact). A valid verdict -- use it rather than guessing
  either way.

Independent fabrication signals (note each that applies in the finding): **(T) no publication has
the cited title** -- the decisive one; **(A)** the author set/order never co-published, or
initials-only generic authors; **(V)** an impossible or non-existent venue/year/volume (e.g. a
proceedings entry and page range that do not exist, a defunct journal); **(D)** a DOI that 404s or
resolves to an unrelated paper, or a placeholder arXiv id such as `2310.XXXX`. **A non-existent
title (T) is itself a fabrication signature and grounds to flag the paper for desk-rejection** --
even when the authors and venue are otherwise real (a real author group on an invented title is the
hardest case to catch); A, V, and D strengthen the case but are not required. Do not push borderline
cases to `real-*` to make the report look clean.

Record each verdict (it persists immediately and is resumable) with the structured signals that
back the category:

```sh
"$RUN" triage record <paper_id> <number> <category> "<finding>" \
  --signals '{"title_match":"no","authors_match":"yes","venue_match":"no","doi_status":"none"}' \
  --out <outdir>
```

`--signals` is a JSON object: `title_match` (`yes`|`no`|`unsure`|`na`), `matched_title` (the real
publication's title), `authors_match`/`venue_match` (`yes`|`no`|`partial`|`unsure`|`na`), and
`doi_status` (`resolves`|`404`|`mismatch`|`none`|`unsure`). `record` enforces the title-first rule:
a `partial-match` requires `title_match=yes` (plus a `matched_title`) or `na`, and
`likely-hallucinated` requires `title_match=no` -- so a fabricated title cannot be filed as a mere
citation error, nor vice versa. Use `unclear` when `title_match` is `unsure`. Signals are optional
for `real-*`. `report` then prints each flag's matched title and signal summary and lists papers
with a non-existent-title reference under a **Desk-reject candidates** heading.

Then assemble the reports:

```sh
"$RUN" triage report --out <outdir>
```

- `<outdir>/reports/reference-check-<paper_id>.md`: per paper.
- `<outdir>/reports/potential-hallucinations.md`: corpus rollup for human review, led by a
  per-paper severity table and a **Desk-reject candidates** section (references whose cited title
  matches no real publication, compounded by a fabricated author constellation, venue, or DOI).
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
