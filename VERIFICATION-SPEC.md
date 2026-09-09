# Verification contract

What hallucite needs from a reference verifier, written as a contract rather than as a description
of any particular implementation. It exists so the verifier can be replaced without changing the
audit, the triage rules, or the reports.

The behaviour below was characterised against the implementation hallucite currently runs on;
`skills/hallucite/scripts/characterize.py` records that behaviour on real references and holds a
candidate replacement to the recording, so this document and the differential test stay in step.

## Surface

hallucite depends on exactly two operations.

### 1. Parse one reference

```text
parse(citation_text, prev_authors) -> { title, authors[], doi?, arxiv_id? } | None
```

`citation_text` is one already-segmented bibliography entry; hallucite does its own PDF reading and
segmentation (`pdf_references.py`) and never asks the verifier to find or split the section.
`prev_authors` supports the `----.` repeated-author convention. `None` means the text could not be
read as a reference, which the audit records as `unparsed` and sends to triage rather than dropping.

Required behaviour:

- **Title.** Quoted titles win where the style uses them (`A. Author, "Title," in Proc.`); otherwise
  the title is the field between the author list and the venue (`Author. 2023. Title. In Venue`).
  Both are common in the corpus and neither may be privileged. A soft line-break hyphen inside a
  word must not become part of the title.
- **Authors.** Both orders (`Surname, I.` and `Surname AB`), surname particles (`van den Bergh`,
  `De Lucia`, `d'Amorim`), and hyphenated surnames. Trailing `et al.` is not an author.
- **Identifiers.** A DOI anywhere in the entry, with or without a `https://doi.org/` prefix; an
  arXiv id in either the old (`cs.SE/0303001`) or new (`2407.08138`) form.
- Fields absent from the entry are absent from the result. Inventing a venue or year from context is
  a defect, not a convenience.

### 2. Verify a batch of references

```text
check(references[]) -> result[] aligned 1:1 with the input
```

Each result carries: `status`, `source` (the backend that decided it), `found_authors` (the matched
record's author list), `paper_url`, `doi_info`, `arxiv_info`, `retraction_info`, `failed_dbs`, and
`db_results[]` of `{db, status, elapsed_ms, found_authors, paper_url}`.

Batching matters: backends are asked only about references an earlier backend has not already
matched, so the hard residue — exactly the references a human will be asked to judge — is where rate
limiting concentrates.

## Status vocabulary

Two levels, and they must stay distinct.

**Per reference:** `verified`, `not_found`, `mismatch`.

**Per backend:** `match`, `no_match`, `author_mismatch`, `timeout`, `error`, `rate_limited`,
`skipped`.

Rules hallucite relies on:

- `verified` means some backend matched. **Any other value means the reference needs human review**
  — hallucite defines that by negation (`status != "verified"`), never by an allow-list, so a status
  added later cannot fall through the gap.
- A backend that did not answer (`timeout`, `error`, `rate_limited`) must be reported in
  `failed_dbs` and must never be silently equivalent to `no_match`. A `not_found` from an incomplete
  run is a weaker claim than one from a complete run, and triage is told not to treat it as evidence
  of fabrication.
- `skipped` means the backend was not applicable, not that it disagreed.

## Author matching

The part that decides most verdicts, and the part most easily got wrong in both directions.

- Compare on a `<initial>:<surname>` fingerprint, not on surnames alone: it keeps `J. Smith` and
  `A. Smith` apart, and it survives a particle appearing on one side only (`Emiliano De Cristofaro`
  against `Cristofaro, E.`).
- Fold diacritics, and fold the letters that carry a stroke or bar rather than a combining mark —
  `ł`, `ø`, `đ`, `ß` survive Unicode decomposition and must be mapped explicitly, or `Przybyłek` and
  `Przybylek` read as different people.
- Tolerate a middle initial present on one side only, a hyphenated surname written with a space, and
  given/surname order swapped.
- A citation may legitimately list fewer authors than the record (`et al.`).

**The phantom-author rule.** When a citation lists *more* authors than the record, the additional
names are the signal: an invented author constellation spliced onto a real paper is the fabrication
pattern this tool exists to catch, and it is invisible when title, venue and pages are all correct.
How strictly to apply it depends on the source:

- **A database that stores complete author lists** (CrossRef, arXiv, OpenAlex, and DBLP *when the
  local mirror was built by an ingest that preserves accented names*) — one unmatched cited author
  is enough to flag.
- **A database whose records may be truncated** — require several unmatched names before flagging,
  because the absence may be the record's fault. Measured over a 95-paper corpus, every DBLP author
  complaint against an otherwise-confirmed reference traced to a mirror that had dropped authors,
  not to a bad citation.

This distinction cannot be hard-coded per backend name. It is a property of the data in hand:
hallucite decides it per run (`_complete_author_dbs`), because a mirror can be repaired, and a
hard-coded exclusion that outlived its reason let a reference with two invented authors verify
again.

## Title matching

- Compare on a normalised form: case, punctuation, diacritics and internal whitespace removed.
- Subtitles may be present on one side only.
- Try both readings of a hyphen — a compound (`Model-Driven`, two tokens) and a line break
  (`Experimen-tation`, one) — because the wrong reading simply finds nothing.
- Where several records share a title, the record type and year separate them: `Experimentation in
  Software Engineering` is three book editions, a 1986 TSE article, a 1997 survey and a 2008
  conference paper. Comparing against whichever ranks first is how a real work gets reported
  missing.

## Non-goals

Deliberately outside this contract, because hallucite already owns them and its own implementations
are what the audit depends on:

- PDF text extraction, section finding and reference segmentation (`pdf_references.py`).
- The all-candidates offline DBLP check (`dblp_check.py`).
- Deciding what reaches triage, and every verdict category (`triage.py`, `SKILL.md`).

## Coverage, for sizing an implementation

Which backend actually decides a verdict, over 1016 confirmations from a 95-paper corpus:

| source | share |
|---|---|
| DBLP (offline) | 84.4% |
| CrossRef | 8.1% |
| DOI resolver | 4.4% |
| Open Library | 1.3% |
| arXiv, Semantic Scholar, Europe PMC, PubMed, Standards | 1.8% combined |

Three sources carry 96.9%, and hallucite already implements its own DBLP path. An implementation
that covers DBLP, CrossRef and DOI resolution, and reports the rest honestly as unchecked, would
serve the audit — provided the status vocabulary and the phantom-author rule above are respected,
since those are what the triage rules and the reports are built on.
