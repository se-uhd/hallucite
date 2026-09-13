# Verification contract

What hallucite needs from a reference verifier, written as a contract rather than as a description
of any particular implementation. It exists so the verifier can be replaced without changing the
audit, the triage rules, or the reports.

`skills/hallucite/scripts/characterize.py` records these operations on real references and holds a
candidate implementation to the recording, so this document and the differential test stay in step.

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
  Both are common in the corpus and neither may be privileged. A line break inside a word leaves
  a hyphen behind and it stays in the title: nothing in the string says whether the hyphen is the
  layout's or the word's own, deleting it is wrong for every real compound, and every comparison
  downstream has to try both readings anyway (see *Title matching*). A **suspended** hyphen is the
  one that must not survive as written -- `Player- and Data-Driven` elides the second half of a
  compound, and closing the gap invents the word `Player-and`.
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
`db_results[]` of `{db_name, status, elapsed_ms, found_authors, paper_url}`.

`check` reads `title`, `authors`, `doi` and `arxiv_id` off each reference, and `raw_citation` where
the reference carries it. The raw text never decides whether a record matches; it only chooses
which of several matching records `paper_url` and `found_authors` report (see *Title matching*).

Batching matters: backends are asked only about references an earlier backend has not already
matched, so the hard residue -- exactly the references a human will be asked to judge -- is where rate
limiting concentrates.

## Status vocabulary

Two levels, and they must stay distinct.

**Per reference:** `verified`, `not_found`, `mismatch`.

**Per backend:** `match`, `no_match`, `author_mismatch`, `timeout`, `error`, `rate_limited`,
`skipped`.

Rules hallucite relies on:

- `verified` means some backend matched. **Any other value means the reference needs human review**
  -- hallucite defines that by negation (`status != "verified"`), never by an allow-list, so a status
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
- Fold diacritics, and fold the letters that carry a stroke or bar rather than a combining mark --
  `ł`, `ø`, `đ`, `ß` survive Unicode decomposition and must be mapped explicitly, or `Przybyłek` and
  `Przybylek` read as different people.
- Read the German transliteration off a name that carries an umlaut (`Büttcher` answers to
  `Buettcher`, `Jürgens` to `Juergens`), never by contracting `ue`/`oe`/`ae` in a name that has
  none -- that would rewrite `Miguel` and `Rodriguez` into spellings an invented author could hide
  behind.
- Tolerate a middle initial present on one side only, a hyphenated surname written with a space, and
  given/surname order swapped.
- A citation may legitimately list fewer authors than the record (`et al.`).

**The phantom-author rule.** When a citation lists *more* authors than the record, the additional
names are the signal: an invented author list spliced onto a real paper is the fabrication
pattern this tool exists to catch, and it is invisible when title, venue and pages are all correct.
How strictly to apply it depends on the source:

- **A database that stores complete author lists** (CrossRef, arXiv, OpenAlex, and DBLP *when the
  local mirror was built by an ingest that preserves accented names*) -- one unmatched cited author
  is enough to flag.
- **A database whose records may be truncated** -- an unmatched cited name is absence of evidence
  and does not flag, because the absence may be the record's fault. Measured over a 95-paper corpus,
  every DBLP author complaint against an otherwise-confirmed reference traced to a mirror that had
  dropped authors, not to a bad citation. The tier still needs a floor: the people such a record
  does list have to account for at least one cited name, or it clears any author list on any title
  it shares.

The record in hand can say so for itself, and where it does that outranks anything known about
the source. DBLP writes a literal `et al.` row where it truncated a long author list, and it
credits a collaboration to the group rather than the people -- `OpenAI`, `Qwen Team`, `Llama Team`
-- which is how the LLM technical reports an SE bibliography now cites constantly are stored. A
correct citation of one names the individual authors, and none of them is in the record.

This distinction cannot be hard-coded per backend name. It is a property of the data in hand:
hallucite decides it per run and per record, because a mirror can be repaired, and a hard-coded
exclusion that outlived its reason let a reference with two invented authors verify again.

An unmatched cited name is only ever *absence* of evidence. A name the record **contradicts** --
it carries that surname, under a different person -- refutes whatever tier the record is in.

A truncated record is still a partial list, and the people it does list are evidence: a citation
that pairs with **none** of them has had every name it lists come back unmatched, and is not
confirmed. DBLP keeps the first authors when it truncates and a citation names them first, so a
correct citation of a truncated record pairs at least one. Without this bar the lenient tier was a
wildcard -- "StarCoder 2" cited under two invented names verified against its 57-person record, and
a title 922 records share verified any author list at all through the one record carrying an
`et al.` row. A record that lists no person, only a group, has nothing to pair against and clears on
the title alone; that is the limit of what a bibliographic database can say about such a work.

## Title matching

- Compare on a normalised form: case, punctuation, diacritics and internal whitespace removed.
- An edition suffix on the record ("(2. ed.)", ", 3rd Edition") is not part of its title.
- Subtitles may be present on one side only.
- Try both readings of a hyphen -- a compound (`Model-Driven`, two tokens) and a line break
  (`Experimen-tation`, one) -- because the wrong reading simply finds nothing.
- Where several records share a title, the record type and year separate them: `Experimentation in
  Software Engineering` is three book editions, a 1986 TSE article, a 1997 survey and a 2008
  conference paper. Comparing against whichever ranks first is how a real work gets reported
  missing.
- Where several of them match the cited authors too, the one reported is the one a human will be
  pointed at: a published record before its preprint, and among those the record the citation
  locates -- the record whose DOI, page range or volume it prints, and failing all three the record
  whose year it prints -- each read off the entry's raw text. A reference handed in without its text
  gets the published-first order alone. The choice never changes a status.

## Non-goals

Deliberately outside this contract, because hallucite already owns them and its own implementations
are what the audit depends on:

- PDF text extraction, section finding and reference segmentation (`pdf_references.py`).
- The all-candidates offline DBLP check (`dblp_check.py`).
- Deciding what reaches triage, and every verdict category (`triage.py`, `SKILL.md`).

## Coverage, for sizing an implementation

Which backend actually decides a verdict, over the 1669 confirmations `characterize.py` records
across the 41-paper corpus, against a mirror whose accented authors survived its ingest and with an
authenticated Semantic Scholar:

| source | share |
|---|---|
| DBLP (offline) | 91.5% |
| DOI resolver | 2.8% |
| CrossRef | 2.8% |
| Semantic Scholar | 1.4% |
| PubMed | 0.5% |
| Open Library | 0.5% |
| Europe PMC | 0.4% |
| arXiv | 0.1% |

The offline mirror decides nine confirmations in ten, so an implementation's accuracy is mostly
its DBLP path. No other source is worth more than three percent, so the question for each is
whether its share is worth a request per unverified reference. Semantic Scholar's 1.4% is only
reachable with an API key -- anonymous callers share a quota that refuses almost everything -- and
PubMed, Open Library and Europe PMC decide 1.4% between them, mostly the statistics classics and
the books an SE bibliography cites without a DOI.

A backend a replacement leaves out has to be reported as unchecked rather than as `no_match`,
which in practice means leaving its name out of `db_results` rather than inventing a negative for
it. The status vocabulary and the phantom-author rule above matter more than any of this: they are
what the triage rules and the reports are built on.
