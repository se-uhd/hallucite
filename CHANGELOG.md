# Changelog

All notable changes to hallucite are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## [2.5.4] - 2026-11-01

### Fixed

- `build_dblp.py` resolves an entity that a chunk boundary splits, also when a read stops inside the
  held-back start of it. It used to hand the parser `&uu` before `ml;` arrived, and the build died
  on an undefined entity. The real dump has few enough entities that no build hit the alignment,
  but a synthetic dump with one entity per record failed after 35,643 lines.
- `build_dblp.py` detaches each record from the root once it is stored. Cleared records stayed
  attached, and on a synthetic dump of 400,000 records they cost 37 MB of peak memory, about 90
  bytes per record.

## [2.5.3] - 2026-10-29

### Changed

- Synced the vendored PyMarkdown linter to pymarkdown-skill 0.3.0 (PyMarkdown 0.9.40). No change
  to hallucite's own behavior.

## [2.5.2] - 2026-10-29

### Changed

- `AGENTS.md` is a symlink to `CLAUDE.md` instead of a pointer file, so a Codex session in a clone
  loads the same repo guidance as Claude Code.
- `CLAUDE.md` states its rules without their history, such as the dates of the prose and spelling
  passes, and is titled "Agent guidance for hallucite".

### Fixed

- `SKILL.md` and `README.md` no longer say that triage "calls an LLM". The agent reading the skill
  does the triage, and it is slow because each reference takes several web searches.
- In `SKILL.md`, the "Classify title-first" sentence that opens the classification protocol renders
  as its own paragraph instead of the end of the preceding search bullet. The paragraph on repeated
  bibliography entries names the per-paper reports and the rollup instead of "both reports".
- The Claude Code and Codex plugin descriptions list OpenAlex among the verification backends, as
  `SKILL.md` and `README.md` already did.

## [2.5.1] - 2026-10-22

### Fixed

- Integer confidence intervals in tables, such as `153 [112, 201]`, no longer trigger a false
  missing-reference error from the bibliography-tail check. The check now recognizes explicitly
  labeled confidence, credible, and prediction intervals, plus estimates contained by their bounds
  under an interval heading in the same nonblank block. Unlabeled pairs, citation lists and ranges,
  reversed bounds, and bounds that exclude the estimate remain citation candidates.
- Extraction diagnostics and triage reports describe uncertain completeness without asserting that
  bibliography entries were necessarily lost, since citation-like numbers can also be table data.

## [2.5.0] - 2026-09-28

### Changed

- An unsupported bibliography layout stops the run. It used to end in a warning and exit 0, so a
  paper with no extracted references looked checked. For each such paper, the audit now prints
  `HALLUCITE_EXTRACTION_UNSUPPORTED: <paper_id>: <problems>`, exits 4, and records the problems
  under `extraction.problems` in the paper's JSON and `extraction_unsupported` in `summary.json`.
  The other papers in a batch are written as before. `SKILL.md` makes the line a stop condition:
  tell the user that hallucite does not support the template and needs an update, check that the
  install is current, and do not triage the paper, read its bibliography by hand, or patch the
  extraction. The triage report opens the paper's page and the rollup with a *Not fully checked*
  section, so that a "nothing flagged" line cannot cover a paper whose references did not all
  arrive.

  The problems that stop the run are no recognized heading, no entries under it, a printed entry
  number that no reference carries, two author-year blocks in one entry, and body citations past
  the last extracted entry (see Added).

### Added

- Extraction detects a lost tail in a plain-numeric bibliography. A bracketed citation before the
  References heading with a number past the last extracted entry marks a reference that never
  arrived. A subscript glued to an identifier, such as `field_3329[52]` in a code listing, is not
  read as a citation.

## [2.4.4] - 2026-09-18

### Added

- The backend-name drift warnings, for configured online backends that never appear and for live
  backends under `--offline`, run in a function, `drift_warnings`, that tests cover in both
  directions. Tests also hold that a title too short to ask the mirror about is reported `skipped`,
  not `no_match`.

## [2.4.3] - 2026-09-18

### Fixed

- A backend that raises an error is reported under its own name. The name was read off the bound
  method's `__name__`, so a rename or a wrapper would have attributed the failure to a backend
  called "backend", which no disable list or drift warning knows.

### Added

- Tests now guard documented behaviors that a revert could break unnoticed: a backend error on one
  reference does not cost the paper its whole verification, an unanswered unverified reference is
  marked degraded, a retraction reaches the record that triage reads, DBLP's homonym suffix is not
  a second name, and earlier evidence, such as a DOI that does not resolve, survives a later
  backend confirming the title.

## [2.4.2] - 2026-09-18

### Changed

- `measure/mutations.py` no longer reverts fixes in the working tree. It copies the tracked tree
  into a scratch directory per worker, runs the entries concurrently (`--jobs`, default: cores less
  two), and stops each suite run at its first failing check (`SMOKE_FAIL_FAST`). A full run takes
  about three minutes instead of an hour and a half, and the tree stays free to edit while it runs,
  so `CLAUDE.md` drops its tree-freeze rule.

### Fixed

- Tests now cover the check of the downloaded dump's digest against the bytes written, the pacing
  of the arXiv harvesting fallback, the OpenAlex query's request for `is_authors_truncated`, arXiv's
  hundred-identifier batch and three-second pause, and the re-check and fallback caps.

- Four more British spellings, in `organisation`, `centred`, and `recognising`, are now American.

## [2.4.1] - 2026-09-18

### Fixed

- The audit's CrossRef candidate lookup applies the same contact-address check as the verifier, so
  a malformed `--mailto` value is no longer sent to CrossRef from that call.

- The dump fetcher's checksum check and install step are one function, `install()`, which tests
  call without the network. A saved web page or a mismatched checksum is refused and leaves the
  dump on disk in place, and a verified download replaces it.

### Changed

- Spelling is American throughout, and `CLAUDE.md` says so. The file also corrects its claim about
  em dashes (`refresh_vendor.py` carries five) and lists that file among the synced files that must
  not be hand-edited.

- The documentation and the `--offline` help text give the mirror's share of confirmations as
  89.4%, from the 2026-09-17 recording, instead of the 91.5% from the replaced package's recording.
  The mirror size reads ~3.8 GB instead of ~3.5 GB, the coverage table's header says 2359
  confirmations instead of 2357, and two claims that cannot be checked are removed: a "95-paper
  corpus" and a count of `--` occurrences.

## [2.4.0] - 2026-09-18

### Changed

- `fetch-dblp-dump` takes dblp's monthly snapshot by default and needs no browser. dblp publishes
  each snapshot through Schloss Dagstuhl's DROPS under its own DOI (`10.4230/dblp.xml.2026-09-01`)
  with an MD5 file beside it. The fetcher streams the release, computes the digest as it goes, and
  refuses bytes that disagree with the published digest or are not gzip. The default path has no
  Python dependency, and a mirror can be named by the release that built it, which anyone can fetch
  again.

  `-- --daily` keeps the browser path, which answers the proof-of-work challenge in front of
  dblp.org's daily dump, for when currency matters, since a snapshot is dated the first of the
  month. The newest published snapshot is found by asking for the current month and stepping back
  up to six months.

## [2.3.1] - 2026-09-17

### Fixed

- A malformed contact address no longer raises CrossRef from one concurrent request to three. The
  verifier did so whenever `--mailto` or `$CROSSREF_MAILTO` held any value, but CrossRef admits a
  caller to its polite pool only for a value it reads as an address, so a typo sent three
  concurrent requests to the public pool. hallucite now applies CrossRef's own rule, a non-empty
  local part before an `@`, and drops a value that fails it.

## [2.3.0] - 2026-09-17

### Added

- When arXiv's search API (`export.arxiv.org/api/query`) will not answer about an identifier, the
  verifier asks arXiv's harvesting interface (OAI-PMH, `oai2`) instead, with one paced request each
  and at most 60 in a run. An `idDoesNotExist` reply counts as arXiv answering that it holds no
  such preprint, which is fabrication signal (D), and any other error code is not an answer.

- `--mailto` defaults to `$CROSSREF_MAILTO`, which belongs in the gitignored `.env.local` beside
  the API keys. CrossRef allows a caller that identifies itself three concurrent requests and an
  anonymous caller one. `SKILL.md` no longer shows an agent typing an address on a command line, so
  the address stays out of command lines, tracked files, and commit messages.

### Changed

- The online results file is re-recorded with the current parser and covers every backend that
  runs, including OpenAlex. Its remaining backend failures are all Semantic Scholar's. It was
  recorded without a contact address.

## [2.2.2] - 2026-09-16

### Fixed

- A question mark in a cited title no longer makes OpenAlex miss the work. OpenAlex's title filter
  finds nothing for a value that contains one, so the mark is removed from the query along with
  the quotation marks. A trailing period, colon, comma, and exclamation mark do not affect the
  filter and stay. An OpenAlex record that lists fewer authors without marking the list as cut
  still refuses a citation that names the missing ones, which sends the reference to triage.

## [2.2.1] - 2026-09-15

### Fixed

- A byline of one-word names no longer clears any author list on its title. The completeness tier
  read a byline without a two-word name as a group credit, such as `OpenAI`, which clears on the
  title alone, and some OpenAlex works store every author as one word, such as `Hildmann`,
  `Nicolas`, and `Saffre`. A byline now names people when it has two or more entries that are not a
  group name or a truncation mark, however short, and a lone one-word entry still reads as a group.
  The rule is shared, so mirror records with such bylines change too. A citation that writes a
  glued name apart (`Wei Wei` for `Weiwei`) no longer pairs with such a record and goes to triage.

### Changed

- `measure/fabricated_citations.py score` prints each fabricated citation that a backend confirms
  in the columns that must stay at zero, with the record, the cited byline, and the byline it
  confirmed on. It also reports how many citations a backend refused under the right title, counts
  "other record" only for the mirror, and takes `--limit N` to fit a metered backend's daily budget.

## [2.2.0] - 2026-09-14

### Added

- OpenAlex is the sixth backend, asked after arXiv and before Semantic Scholar. It searches works by
  title, one reference at a time, under the same title and author rules as every backend. It reads
  the byline as printed (`raw_author_name`), treats a byline cut at a hundred names as an `et al.`
  row, carries a work's retraction, does not take a review of a book for the book, and asks again by
  the main title when the record lacks the cited subtitle. It is asked with or without a key and
  meters by the day: a hundred searches anonymously and a thousand under a free key
  (`--openalex-api-key`, `$OPENALEX_API_KEY`), reset at midnight UTC. A refusal means the budget is
  gone, so it is not retried, and after three in a row the rest of the batch is reported `skipped`
  without being asked, which the triage worklist shows.

  Some book citations confirm through a journal's review of the book, because OpenAlex lists the
  book's author in the review's byline. The verdict is right but the record shown is the review,
  and only reviews that OpenAlex types `book-review` are told apart.

- `measure/fabricated_citations.py score --backend NAME` scores one backend alone with every other
  disabled, and `--sets` and `--columns` bound what an online backend is asked. A full pass is about
  6,500 requests.

## [2.1.0] - 2026-09-13

### Removed

- Three finished measurement scripts are removed, and with them the last import of the AGPL
  package. `measure/head_to_head.py` compared hallucite's parser and DBLP path with the verifier it
  replaced and was the last file importing `hallucinator`. `measure/residue_evidence.py` measured
  the evidence that every triage worklist entry now carries as `skipped_dbs`, `dblp_nearest`, and
  `identifiers`. `measure/extraction_census.py` and its `census.json` duplicated the committed
  `tests/fixtures/corpus/EXPECTED.tsv`. Also removed from `~/hallucite/`: the previous offline
  recording and the online run's log.

### Changed

- `PLAN.md` states that the author rule is asymmetric and why, how the completeness tier is
  decided, and what the three measurement artifacts and the mutation run each check.

- Each fact is stated in one document. `SKILL.md` holds the triage protocol and the `run.sh`
  wrapper's promises, `PLAN.md` the packaging layout, and `CLAUDE.md` points at them. The smoke
  suite's docstring replaces the stale inventories of what it covers in README and PLAN.

- The measurement tools and their files are renamed. `characterize.py` is
  `verification_results.py`, and its files are `verification-results-offline.json`,
  `verification-results-online.json`, and `verification-results-hallucinator.json`: hallucite's
  result for every corpus reference with the mirror only, the same with every backend, and the old
  external tool's result, frozen and read by nothing. `corruptions.py` is `fabricated_citations.py`,
  and `corruptions.json` and `corruptions-truncated.json` are merged into
  `fabricated-citations.json`, which scores byte-identically. The corpus manifest is `MANIFEST.csv`.

- The mirror is rebuilt from the 2026-09-12 dump, and `verification-results-offline.json` is
  re-recorded against it. `verification-results-online.json` is not, so replaying it shows three
  references that DBLP indexed between the two dumps as moves until it is re-recorded.

### Fixed

- `characterize.py record --help` no longer crashes inside argparse with
  `%o format: an integer is required`. The bare `91.5%` in the `--offline` help text is escaped.

## [2.0.1] - 2026-09-13

### Fixed

- Fourteen documentation claims that no longer matched the code are corrected.
  `VERIFICATION-SPEC.md` names the `db_results` field `db_name`, not `db`, and describes the lenient
  author tier as requiring one matched name. `README.md` documents the five-branch `run.sh`
  resolver, no longer promises a `/hallucite` command or says that a marketplace-installed plugin
  reads the clone's `.env.local`, no longer tells plugin users to build the mirror with mise tasks,
  and mentions the closing warnings that separate an audit from a silent no-op. `CLAUDE.md` names
  `pdftotext` and what `~/hallucite/` holds, and its conventions are regrouped under four
  subheadings. `PLAN.md` no longer describes a `run.sh` auto-provision path.

- `titles_match` strips a `(Reprint)` suffix from a record's title, as it already stripped an
  edition suffix, so Boehm's *Software Engineering Economics*, cited as the Springer 2002 reprint,
  can match `books/sp/02/Boehm02a`. The ICSE 2002 tutorial of that title is still the record shown,
  because it carries the cited year too and the citation prints no DOI, page range, or volume.

- `fetch-dblp-dump` no longer overwrites the existing dump before checking the download. It saves
  to a `.part` file beside the destination and swaps only after the gzip check, so a saved
  proof-of-work challenge page no longer replaces a working dump.

- A repo-wide prose pass with `/ai-slop:review-repo` covered the Markdown, the comments and
  docstrings of the scripts, the config comments, and the ten commit messages since `4dff7bc`.
  `VERIFICATION-SPEC.md` uses the house `--` dash instead of em dashes, and the triage report's own
  output no longer uses negative parallelism.

- `requirements.txt` no longer says that `characterize.py record` needs `hallucinator`. It names
  `measure/head_to_head.py` as the one script that still imports it, and Playwright as the one
  task-level dependency.

### Removed

- `TODO.md` is removed, its last item closed. The inventory of `~/hallucite/`, and what each
  recording can and cannot answer, is in `CLAUDE.md`. The widenings of name and title matching that
  were measured and rejected are listed in the 2.0.0 entry.

## [2.0.0] - 2026-09-12

hallucite no longer depends on the package it was built around. Stages 1 and 2 are its own
extraction, parsing, verification, and DBLP ingest, written against a black-box recording of the
external verifier rather than from its source, which lets this MIT repo drop an AGPL-3.0-or-later
dependency.

### Added

- The audit runs on hallucite's own modules: `audit_references.py` builds a `Verifier` and parses
  through `reference_parser`, and nothing on the audit path imports `hallucinator`. The separate
  second-opinion and author-absence passes are gone, because the DBLP backend checks all
  candidates and the author rule decides inside the check.

  `parse_reference` recognizes each citation style by the mark that separates the author list from
  the title, such as a standalone or parenthesized year, an "et al.", an opening quote, or a colon
  after inverted names, and falls back to the leading sentence. A venue that follows the title
  without an "In" is no longer read as part of the title.

  `check` asks five backends, cheapest first, each only about what the earlier ones missed: the
  offline DBLP mirror, CrossRef's bibliographic search, DOI resolution through CrossRef and then
  doi.org content negotiation, arXiv by identifier a hundred at a time, and Semantic Scholar's paper
  search one reference at a time. Open Library, PubMed, and Europe PMC are not asked, so a reference
  that only they would match is reported `not_found`. Retraction status is read wherever CrossRef
  answered anyway, so a reference that the mirror confirms is not checked for retraction.

  Semantic Scholar is asked only when `--s2-api-key` or `$S2_API_KEY` supplies a key. Anonymous
  callers share one small quota, and asking anyway would mark a different handful of references
  degraded on each run and move the boundary between `verified` and "needs triage" between
  identical audits.

  A word that a two-column layout splits without a hyphen ("distributed sy stems") is also queried
  glued to its neighbor when nothing else matched. A citation that drops an elided particle
  ("Marcelo Amorim" for "Marcelo d'Amorim") still matches, provided the given name pairs.

- The offline mirror is hallucite's own ingest. `build_dblp.py` replaces
  `hallucinator-cli update-dblp`, and with it the Rust toolchain, the prebuilt binary,
  `install-cli`, `install-cli-patched`, and `dblp-entity-fix.patch`. It resolves the dump's
  character entities as numeric character references, so authors with diacritics survive without
  mojibake ("JÃ¼rgen" for "Jürgen"). An edited book's `<editor>` entries are read where it has no
  author, and `<www>` person homepages are skipped. The ingest needs only the standard library and
  takes 4.8 minutes instead of 20 to 30.

- The triage worklist and report show evidence that the audit already had about an unverified
  reference. No status changes.

  - A `not_found` shows whether the mirror was asked at all. The DBLP backend reports `skipped` for
    a title it does not query, such as a one- or two-word title, which used to read as a clean
    negative. The worklist entry carries `skipped_dbs`, and the report prints
    `Not asked: DBLP, ...`.

  - The worklist entry carries `identifiers`, with each cited identifier's kind, id, whether it
    resolves, its resolved title, and whether that matches the cited title. The report prints one
    line per identifier: dead, resolves to the cited title, or resolves to a different title, named.

  - Where the DBLP backend answered `no_match`, `dblp_check.nearest_title` offers a record with a
    title within two word-level edits of the cited one, provided that every cited person is on it.
    The authorship requirement keeps out different works with nearly the same title, at the cost of
    refusing a record that lists fewer authors without marking itself truncated.

- `measure/` holds the measurements that this entry cites, as scripts. `extraction_census.py`
  tabulates what each corpus paper extracts against a baseline. `corruptions.py` builds a
  fabricated-citation set once from a fixed seed and scores an implementation against it.
  `head_to_head.py` compares the old and new parser and DBLP check offline. `mutations.py` reverts
  one fix at a time, requires the suite to fail, and stops if a tracked file changes mid-run.
  `residue_evidence.py` prints, per unverified reference, what the three evidence items above found.

- `tests/fixtures/make_corpus_fixtures.py` derives one synthetic test fixture per corpus paper,
  since the papers are other people's manuscripts and stay outside the repo. Each fixture is the
  real `pdftotext -layout` output with every author name and title word replaced by an invented
  word of the same length, so the layout survives and nobody's authorship does. The generator
  refuses to write a fixture whose extraction differs from the real paper's, and smoke tier 4j
  checks all 55 fixtures against `corpus/EXPECTED.tsv`, which is written from the real papers.

### Fixed

- Unnumbered hanging-indent author-year bibliographies are segmented: Elsevier's Harvard style,
  which ends the author list with a bare year (`Cao, S., Sun, X., 2024.`), and Springer's plainnat,
  which puts the year in the venue field. Such bibliographies had been read as no style or as
  numeric and lost all or most of their entries. Author-year bibliographies also keep two-author ACM
  entries (`Haipeng Cai and Raul Santelices. 2014.`) and organization entries (`OpenAI (2024)`)
  separate instead of gluing them into the entry before.

  Extraction now reads the hanging indent, and the bibliography ends where the layout does, so the
  author biographies that Elsevier prints after it under no heading are not read as references. An
  ACM footer (`Received 2023-09-29; accepted 2024-01-23`) stays appended to the last reference.

- A bibliography no longer loses whole references unnoticed. Extraction reports the entry numbers
  that a numbered bibliography prints but no reference carries, counting from 1, and the audit
  warns about them. Three causes of lost references in `pdf_references.py` are fixed:

  - A running head that spans both columns no longer costs a short final page its column split.
  - A line that runs into the column gutter no longer loses a letter to the column cut, which had
    glued the next entry onto its predecessor.
  - Entries that differ only in their number, such as five `[N] "CVE-2022-1975," https://...`
    lines, are no longer filtered as running heads.

  The check for a swallowed tail applies only to bracket styles, because a plain-numeric label such
  as `30.` is not distinctive.

- Parser fixes for citation shapes that kept a reference from reaching the backends with the right
  fields:

  - Elsevier's comma between title and venue is read as a field break, so the venue no longer
    becomes part of the title.
  - A hyphenated initial (`K.-W. Chang`) is read as an initial, not as the title `and K.-W`.
  - An accented given name that LaTeX abbreviates and pdftotext renders as `J.a.P.` is read as one
    person, not two.
  - A particle surname written surname-first, such as `d'Amorim`, is read as an author instead of
    leaving the whole byline with no authors.
  - An organization is not split on its own "and" ("Institute of Electrical and Electronics
    Engineers"). A byline with no comma, no initials, a lowercase function word, and eight words or
    fewer is one body's name.
  - A suspended hyphen ("Player- and Data-Driven") keeps the space after it instead of being closed
    as a line break.
  - One inverted author split across two chunks (`Zeller, Andreas.`) no longer counts as two people
    when both chunks pair with the same record author and together are contained in that name. An
    invented name pairs with nobody and is never excused. Merging the chunks in the parser instead
    was measured and rejected, since `Akhavan, Hosseinpour` is two people.
  - A stray mark between two names ("OpenAI, :, Aaron Hurst, et al.") no longer disqualifies the
    whole author list.
  - A period between two digits, as in a version number broken across a line ("Deepseek-v3. 2"), is
    not a sentence end.
  - A parenthesis that an entry appends to its title, such as an ACM conference acronym
    (`(DIS '25)`), an edition, or a year, is removed from the title, and so is a year printed after
    the title without a comma.
  - `URL https://...` is read as the identifier's label, not as a title.
  - A title is not cut at its own `!` or `?` unless what follows reads as a venue.
  - A title that opens with a roman numeral is not cut to the numeral, and the role after IEEE's
    comma-delimited names (`editors`) is not read as the title.
  - An `et al.` followed by a comma marks the next comma field as the venue, and a bare publisher
    field ends the title.
  - `Al` is a name particle, not the tail of "et al.", so a name such as "Fahmid Al Rifat" matches a
    citation of itself.

  Reading a `?` as a subtitle mark in `titles_match` was measured and rejected. A comma-joined field
  that the parser has no name for, such as `, GitHub repository`, stays in the title, and such a
  reference reaches triage as `not_found`.

- A DOI broken across a line is rejoined: at one of its own hyphens, after a period, between
  `10.48550/arXiv` and the identifier, or at an underscore, which pdftotext renders as a space.
  Previously only the part before the break was kept, or nothing when the break fell at the slash.
  The fragment could resolve to nothing, which triage reads as fabrication signal (D), or to
  another work, such as a book's DOI where the citation named a chapter. The rejoin applies only
  where the text continues the identifier, not when a four-digit year follows, and a DOI that is
  wrong as printed now travels whole rather than as a dead front half. An arXiv identifier written
  as a CoRR volume (`arXiv, vol. abs/2410.15631`), as the IEEE styles print it, is read too.

- A citation that appends invented authors to a real paper no longer verifies. Every cited name
  that reads as a person must be matched by an author of the record, which catches signal (A) in
  `SKILL.md`. A citation may still name fewer authors, which is what "et al." means, and the
  requirement of at least two matched names is dropped, so a real work cited as "First Author et
  al." verifies.

  Names are paired rather than compared as subsets. A middle initial that the record lacks, a
  particle on one side only, or a generational suffix no longer refutes ("Mohammed F Kharma" is
  "Mohammed Kharma"), but a contradicted given name still does ("Q. Muñoz Barón" for "Marvin Muñoz
  Barón"). Author lists are paired by augmenting paths rather than first fit, so one cited name
  cannot take the record author that another needs ("Xin Xia" fits both "Xin Xia 0001" and "Xin
  Xiao").

- The author rule has two tiers, as `VERIFICATION-SPEC.md` requires, decided per run and per
  record. `mirror_authors_complete` checks whether this mirror's ingest kept its accented authors,
  and `record_authors_complete` checks whether the byline in hand is a list of people. Against an
  incomplete record, such as an LLM technical report that DBLP credits to `OpenAI` or a record that
  ends in `et al.`, an unmatched cited name does not refute, but a name that the record contradicts
  still does.

  The lenient tier has a floor: a citation must pair with at least one person whom a truncated
  record lists, so a real title under invented names no longer verifies against it. A record
  credited to a group rather than to people still clears on the title alone, so "GPT-4 Technical
  Report" under invented names verifies, and only the arXiv backend, asked by identifier, can say
  otherwise.

- Titles are compared on letters alone, tolerating a subtitle on one side only, as the contract
  requires, so "Model Driven" and "Model-Driven" are the same title. Related retrieval and
  comparison fixes:

  - The mirror query no longer misses a matching record past its first 50 FTS hits, which SQLite
    returns in row order rather than by match quality.
  - A title with `ł`, `ø`, or `ß` matches its own record, since both foldings are queried, and the
    word-wise query offers both readings of every hyphen.
  - An edition suffix on the record is trimmed before the comparison, and a parenthesized alias
    (`Tse-Hsun (Peter) Chen`) no longer keeps a name from pairing.
  - Retrieval finds a title with a word split inside the record's title or in the citation, or with
    an article glued to its neighbor.
  - Apostrophes are folded, so `O’Donoghue` and `O'Donoghue` are one person. A capital B where a
    PDF renders an eszett (`LeBenich` for `Leßenich`) is also read as `ß`. The German
    transliteration of an umlaut ("Buettcher" for "Büttcher") pairs with the letter, taken only from
    the side that carries the umlaut. Contracting `ue` in every name is not done, because it would
    rewrite names such as "Miguel" into spellings that an invented author could hide behind.

- Two-word titles are not looked up in the mirror (`_MIN_TOKENS` stays at 3) and reach triage as
  `skipped`. Lowering it to 2 was measured and rejected, because it confirmed Sommerville's
  textbook "Software engineering" against his 1983 conference paper of that title. A record-side
  title prefix tolerance was also rejected, since it would confirm the Jest documentation page
  "Getting Started" against a 1991 keynote of that name. A DBLP record that lists fewer authors with
  no `et al.` row, such as the CoRR record of a 22-author preprint that lists 19, refutes a correct
  citation that names the missing ones.

- Of several records that share a title, the published record comes first instead of the one with
  the lower row id, and where none matches the authors, the near miss reported is the record that
  accounts for most of them. Among records that all match, the citation's own text decides:
  `title_candidates` orders them by the DOI, page range, and volume read off the raw text and the
  parsed DOI (`cited_dois`, `pages_match`, `volume_match`), then by the year that the citation
  prints (`cited_years`). The published record stays first whatever these say. No status changes,
  only the record shown.

  A page range must equal the record's `pages` at both ends. An IEEE DOI's year segment and an
  arXiv identifier are not counted as cited years, and a page range that looks like a year can be
  misread as one. Ranking books ahead of articles ahead of conference papers, matching the record's
  venue text in the citation, and preferring a book record for an entry that names a publisher
  were turned down.

- A backend answer that cannot be read is reported as a backend failure, not a clean negative. An
  arXiv response that is not a feed, such as an HTML outage page, had read as "arXiv holds none of
  these identifiers", producing fabrication signal (D) for up to a hundred identifiers. The same
  applies to a 404 from the CrossRef or Semantic Scholar search endpoint, a CrossRef 200 without an
  `items` key, and Semantic Scholar's 200 carrying `{"message": "Too Many Requests"}`, which also
  reset its give-up counter. An arXiv identifier missing from a batch response is asked again on
  its own before it is called dead.

- Semantic Scholar's give-up counter now trips under an intermittent block. It counted consecutive
  refusals, which a bursty throttle never reaches, so every refused reference paid the full retry
  ladder. After 25 refusals in total (`_S2_PATIENCE`), the retries are dropped and every remaining
  reference is still asked.

  A rate limit without `Retry-After` now doubles its wait on each attempt instead of retrying after
  a fixed two seconds. doi.org content negotiation and Semantic Scholar search get a 45-second
  timeout instead of 15, so artifact and dataset DOIs that resolve slowly through DataCite, such as
  Zenodo DOIs, are no longer reported unresolvable. A title with a line-break hyphen is also sent
  to the online searches in its joined form when the first query matched nothing, though a title
  that carries both a real compound and a line break is still asked in neither spelling that would
  find it.

- When every name in a parsed author list is a venue fragment, the verdict is `no_match` instead of
  `author_mismatch`, so a triager is no longer shown a near miss where nothing was compared.

- `authors_absent` is filled again. It is derived where it is read, from the record that the
  verdict rests on, so the report line it feeds prints and the signal (A) that `SKILL.md` describes
  is there. `triage.py` decides that a record matched from `match` and `author_mismatch` instead of
  by excluding failure statuses by name, which had let a `timeout` read as a matched record.

- `run.sh` reads `.env.local` the way mise's dotenv reader does. An indented comment or an
  `export FOO=bar` line had ended the run with a bash error and no `HALLUCITE_BOOTSTRAP_FAILED:`
  line, and a CRLF file exported the API key with a trailing carriage return.

### Changed

- `.env.local` in the repo root, gitignored, holds the API keys that the online backends want. mise
  reads it through `[env]` and `run.sh` reads it directly, so a dev clone and a plugin installed
  from it see the same values. A plugin installed from the marketplace runs from its own tree and
  does not read the clone's file. A variable already set in the environment wins, and a missing
  file is fine.

- `characterize.py record` takes `--s2-api-key` or `$S2_API_KEY` and warns when it has neither. It
  never passed a key through, so recordings ran unauthenticated and Semantic Scholar rate-limited
  the residue that a recording exists to capture.

- `characterize.py compare` covers `check` as well as `parse`. It reports the recorded status
  against the implementation's as a matrix and lists every reference that crosses the verified line
  in either direction. `--out` writes the whole divergence list as JSON, `--limit` compares a
  sample, and `--no-check` compares the parse alone without network requests.

## [1.21.0] - 2026-09-09

### Fixed

- A two-column bibliography no longer loses half its references. `_gutter` required four wholly
  blank character columns, but an ACM two-column reference page sets its columns three apart in
  `pdftotext -layout` output, so the page was read as one column and the right column's text was
  appended to the left column's lines. Three blank columns now make a gutter, since two gain
  nothing over three.

### Added

- `characterize.py` records what the current implementation returns for `parse_reference` and
  `Validator.check` on real references, and holds a replacement to that recording. hallucite calls
  `hallucinator` at those two points only, so the recording is the specification and the
  differential test for replacing it.

## [1.20.0] - 2026-09-09

### Added

- `--s2-api-key` (or `$S2_API_KEY`) and `--rate-limit-retries`, and a note when no key is set.
  Without a key, Semantic Scholar mostly answered `rate_limited`, which left references degraded
  and moved the boundary between "verified" and "needs triage" between otherwise identical runs. A
  free key removes this churn.

## [1.19.0] - 2026-09-09

### Added

- The mirror also stores `volume`, `number`, and `pages`, so a citation's "49(3):1152-1170" can be
  checked against the record it claims to be.

- A reference that reaches triage carries DBLP's key, year, venue, volume, number, pages, DOI, and
  record type for its title, in the worklist and the per-paper report.

### Changed

- The year, venue, and DOI checks were measured and not built as automatic demotions, because each
  disagrees too often with verified references: venue 28%, year 10%, and DOI 6.7%, against 0.22%
  for the author-absence check that does demote. The fields are shown as evidence instead.

- The three-argument wrapper of `insert_or_get_publication` is gone, because its `ON CONFLICT`
  cleared `year`, `venue`, `ee`, and `kind` back to NULL for any later caller. Callers pass the
  full record in one signature.

### Fixed

- `record_context` finds a record with a title broken across a line that needs both hyphen readings
  at once ("de-velopers keep up-to-date"). It falls back to an AND over the words without a hyphen
  and compares titles with punctuation removed.

## [1.18.0] - 2026-09-09

### Added

- The offline DBLP mirror stores `year`, `venue`, `ee` (the electronic edition, usually the DOI),
  and `kind` (the DBLP element, such as article, inproceedings, or book), added to
  `dblp-entity-fix.patch`. This makes two fabrication signals checkable in `--offline` runs: a wrong
  or impossible venue and year (V), and a DOI that belongs to another work (D). `kind` and `year`
  also separate same-title records that authors alone could not, such as the six "Experimentation
  in Software Engineering" entries.

- `second_opinion()` carries `year`, `venue`, `ee`, and `kind` on a confirmation, reading whichever
  columns the mirror has. A database built before the ingest stored them reports them as absent,
  and everything else keeps working.

### Fixed

- `dblp_check`'s author folding handles `ł`, `ø`, `đ`, and `ß`, which carry no combining mark for
  NFKD to strip, so `Przybyłek` and `Przybylek` are the same person.

## [1.17.0] - 2026-09-09

### Fixed

- A reference that names authors the matched work does not have is caught again when DBLP cleared
  it. `COMPLETE_AUTHOR_DBS` excluded DBLP because the local mirror had dropped its accented authors,
  which became wrong once the mirror was repaired. Which backends count is now decided per run from
  the mirror in hand (`_complete_author_dbs`): DBLP counts when its accented authors survived the
  ingest.

- Letters with a stroke or bar, such as `ł`, `ø`, `đ`, and `ß`, fold to their ASCII form, so
  `Przybyłek` and `Przybylek` no longer compare as different people and the citation no longer
  reads as inventing an author. DBLP's homonym suffix (`Márcio Ribeiro 0001`) needs no special
  case, since digits are already filtered out.

- `mise run build-dblp` removes the `-wal` and `-shm` files on both sides of the swap, so neither an
  orphaned scratch pair nor a stale destination pair is left.

## [1.16.0] - 2026-09-09

### Added

- `mise run fetch-dblp-dump` downloads `dblp.xml.gz` with a real browser for the `--from-file`
  build, because dblp.org and both its mirrors serve every plain HTTP client an Anubis
  proof-of-work challenge instead of the file. The browser answers the challenge with its own JS
  engine, and nothing forges or replays a token. It runs headed, since Anubis refuses the headless
  browser, so it needs a display. The dump is saved beside `$HALLUCITE_DBLP`.

- A dependency table in the README names Playwright with its own Chromium as the concrete form of
  "a web browser", and the Rust toolchain as needed only for `install-cli-patched`.

- `mise run install-cli-patched` builds `hallucinator-cli` from the pinned upstream source with
  `dblp-entity-fix.patch` applied, and fails if the built binary does not carry the fix.

### Changed

- `mise run install-cli` refuses to overwrite a binary carrying the patch, since the stock upstream
  build drops every author with a diacritic and the loss is invisible downstream. `FORCE=1`
  overrides.

## [1.15.0] - 2026-09-09

### Added

- `update-dblp --from-file <XML_GZ>` builds the mirror from a dump already on disk, added to
  `dblp-entity-fix.patch`. dblp.org and both its mirrors serve every plain HTTP client, including
  the downloader inside `update-dblp`, an Anubis proof-of-work challenge instead of the dump, which
  was then ingested as zero publications.

### Changed

- `mise run build-dblp` forwards `$DBLP_XML_GZ` to `--from-file` when it is set, so a dump
  downloaded in a browser can be ingested. README documents the route.

## [1.14.0] - 2026-09-08

### Added

- `dblp-entity-fix.patch`, against hallucinator 0.2.3, fixes the upstream ingest bug that dropped
  every author whose name DBLP writes with a named entity such as `&aacute;` or `&ouml;`. It enables
  quick-xml's `escape-html` feature and falls back to the raw text instead of discarding the field.
  Apply it, rebuild `hallucinator-cli`, then rebuild the mirror.

- The audit warns when the offline DBLP database holds almost no publications, as happens when
  `update-dblp` ingests a bot-check HTML page instead of the dump and still exits 0.

### Changed

- `mise run build-dblp` builds to a scratch file and swaps it in only after checking that it holds
  over a million publications and that accented author names survived. Writing straight to the
  destination had replaced a working mirror with an empty one after a bot-check download.

### Fixed

- An empty offline mirror is no longer reported as one that dropped its accented authors. The
  entity check requires a mirror-sized author table first.

## [1.13.1] - 2026-09-08

### Added

- The audit warns when the offline DBLP database holds no author name with a non-ASCII character,
  which means that the ingest mangled the dump's character entities and dropped those authors from
  every paper they wrote. DBLP then reports an author mismatch for correctly cited references, and
  its second opinion fails to confirm real work.

### Fixed

- Corrected why `COMPLETE_AUTHOR_DBS` omits DBLP. The missing co-authors are dropped by the local
  mirror's ingest, not truncated in DBLP as 1.13.0 said. The exclusion stands while a build behaves
  this way, and DBLP should be added once a build preserves those names.

## [1.13.0] - 2026-09-08

### Added

- The audit flags a reference that names an author the matched publication does not have.
  Previously a real title with an invented author list verified on the title and never reached
  triage. After verification the audit compares the cited authors with those of the clearing
  backend, demotes the reference to `author_mismatch`, and carries the absent names into the
  worklist (`authors_absent`) and the per-paper report.

  Only the clearing backend's authors count, and only from a backend that returns complete author
  lists. The two lists must be the same length, so an abbreviated citation is never read as a
  fabricated one. Venue fragments, the sentence that the parser bleeds into the last author, and
  single-token remains of a split name are skipped, and diacritics, hyphenation, middle initials,
  compound surnames, and swapped given name and surname order compare equal. A backend's own
  `author_mismatch` verdict is not used, because on correctly cited references it mostly reflects
  truncated author rows or a same-title record of a different work.

## [1.12.1] - 2026-09-08

### Fixed

- A section heading that `pdftotext` letter-spaces, such as `R EFERENCES` from the small caps of
  IEEE journal proofs, now opens the bibliography. Such a paper had reported 0 references with exit
  0. Headings are also compared on their space-stripped spelling, which covers
  `R E F E R E N C E S`, and the Appendix or Acknowledgment heading that ends the section is
  matched the same way, so author biographies cannot land inside the bibliography. The comparison
  still needs a whole short heading line, so a sentence that opens with "References" cannot start
  the section.

### Changed

- The zero-reference warning says that the run is an extraction failure to report and fix, and that
  reading the bibliography by eye yields no verdict, instead of "Verify these by hand or fix the
  extraction". `SKILL.md` gains the matching stop condition, since the audit exits 0 on this path.

## [1.12.0] - 2026-07-20

### Added

- A second-opinion pass over the offline DBLP database (`dblp_check.py`). hallucinator's offline
  backend compares a reference with a single FTS candidate, so a title that several publications
  share is judged against whichever ranks first. After hallucinator's pass, the audit re-asks the
  same SQLite file over all same-title candidates, and exact normalized-title equality plus an
  initials-aware match of every comparable author confirms the reference as `verified` with source
  `DBLP (hallucite)`. The pass only clears references and never flags one, and hallucinator is
  neither vendored nor patched.

## [1.11.0] - 2026-07-20

### Fixed

- A stale verdict is quarantined instead of reattached. Author-year numbers follow extraction
  order, so a re-audit can renumber the bibliography and leave a verdict keyed `paper_id:number` on
  a different reference. `report` warned and then printed the old category anyway, flagging an
  innocent reference as likely-hallucinated. It now shows the verdict as stale and the reference as
  pending, `worklist --pending` resurfaces it, and `status` counts it as pending.
- A hedged verdict can no longer reach the Desk-reject candidates section. `is_fabrication`
  requires the `likely-hallucinated` category alongside `title_match=no`, and `record` rejects
  `unclear` with `title_match=no` as contradictory.
- Running heads are counted over the whole document instead of the References section, so a head
  that appears only once in a two-page bibliography is dropped instead of gluing the citing paper's
  own title and page number into a reference.
- A wrapped page number alone on a line ("...19(3):619–" / "654") is no longer blanked as a
  `lineno` margin number, since only numbers in the margin column are blanked.
- `record` rejects a `paper_id:number` that matches no audited reference instead of storing a
  verdict that could never appear in any report.

### Added

- Verification retries a failed reference with its line-break hyphens removed ("Experimen-tation"),
  and keeps the result only when it verifies.
- The audit warns about suspected merged entries: an author-year reference with two "(year)" author
  blocks, the shape left when a flat layout glues an entry onto its predecessor. The warning is per
  paper and stored in the extraction record.
- A closing warning lists the papers that yielded 0 references, so an unchecked paper cannot scroll
  out of sight in a long batch.

### Changed

- The triage rules bound the partial-match rescue: an independent identifier rescues one or two
  slipped title words, never a wholly different title, so a real record stapled to an invented
  title is `title_match=no`, not a citation error.
- The verify sheets label the triager's text "Triage finding", since the LLM triage step writes it,
  not the database check that the sheet also shows.

## [1.10.2] - 2026-07-20

### Changed

- The repeated-entry guidance states an asymmetry instead of banning a recommendation: wrongly
  merging destroys distinct citations, while separate entries stay fixable, so an unresolved
  conflict defaults to no action. It replaces 1.10.1's "do not advise merging the conflicting one",
  since the in-text usage of each key can show a conflict to be one work.

## [1.10.1] - 2026-07-20

### Changed

- Repeated bibliography entries are classified instead of hedged. Entries that match on authors,
  title, venue, volume, and pages are reported as duplicates and stated as fact. Entries with a
  venue, volume, or pages that disagree are reported as conflicting, and the in-text usage of each
  key decides. A group can produce both findings.

## [1.10.0] - 2026-07-20

### Added

- Unverified references carry `candidates`: the closest records from CrossRef's fuzzy bibliographic
  search, with title similarity, DOI, venue, and year. They catch a citation that abbreviates or
  expands a term, which exact-title lookups miss and a quoted web search can mistake for
  fabrication. Candidates are leads to confirm or reject, never verdicts, and an empty list carries
  information too. `--no-candidates` skips the lookup and `--offline` implies it.
- Worklist entries and reports carry `matched`: the record each backend matched and the authors it
  holds, so a `mismatch` can be judged against what mismatched.
- Reports list indistinguishable entries, that is, different citation keys with the same authors
  and title. The report states the problem without diagnosing it, since only the in-text usage of
  each key settles whether they are one work or several.
- `--retry-degraded N` (default 1) re-checks references that a backend failed to answer for,
  keeping the retried result only when it improves.

### Changed

- References are named by a handle the reader can find. A numbered bibliography keeps its printed
  `[12]`, and an unnumbered author-year one uses the paper's own citation key
  (`de Dieu et al. (2025c)`). The extractor's sequential index, which `triage record` takes, is
  shown as `[#n]` and marked as hallucite's own.

### Fixed

- A `not_found` produced while a backend errored or rate-limited is flagged `degraded` and no
  longer presented as a clean negative. The audit prints a per-backend failure tally, `record` warns
  when a `likely-hallucinated` verdict rests on a degraded check, and the skill tells triage to
  treat such an absence as no evidence. `degraded` is a flag rather than a new status value, so
  `status != "verified"` still defines "needs triage".
- The triage rules treat an abbreviation and its expansion ("LLMs" / "Large Language Models") as the
  same title, not as a wrong content word that leads to `likely-hallucinated`. They also say that a
  narrow search returning the same authors under different titles is the trigger to broaden, not a
  conclusion.

## [1.9.0] - 2026-07-20

### Added

- `run.sh upgrade` upgrades `hallucinator` in the managed venv, and `check-env` warns when PyPI has
  a newer release. Previously an install stayed on whatever version was current when its venv was
  created. `upgrade` refuses when `$HALLUCITE_PYTHON` is set, since `run.sh` does not modify an
  interpreter it did not provision, and `$HALLUCITE_NO_VERSION_CHECK` skips the PyPI lookup for
  offline and CI runs. `mise run upgrade` covers the repo venv and the managed venv together.

### Fixed

- Reference extraction handles a Springer author-year bibliography ("Bacchelli A, D'Ambros M (2009)
  ...") printed under LaTeX `lineno` margin numbers, where each physical line had become its own
  reference. Single-digit margin numbers and numbers alone on a line are detected, and margin
  numbers are overwritten with spaces rather than deleted, which keeps the hanging indent that
  delimits author-year entries. The author-year entry pattern accepts the Springer "Surname AB,"
  form. Running heads and text outside the bibliography's column block are dropped, so a page
  header or an editorial system's "Click here to download" slip no longer ends up in a reference.

## [1.8.4] - 2026-06-24

### Fixed

- The `SKILL.md` `run.sh` resolver scans the Claude Code plugin cache
  (`${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache`) for the highest installed version, ahead of
  the Codex plugin cache. When `CLAUDE_PLUGIN_ROOT` was unset in the tool shell, as it is for an
  ordinary Bash call, a stale Codex-cached copy could run instead of the current Claude install,
  and `/plugin marketplace update` had no effect.

## [1.8.3] - 2026-06-24

### Fixed

- Reference extraction handles a bracket-numeric bibliography ("[1]" ... "[59]") printed under
  LaTeX `lineno` margin numbers that restart on each page. A new bracket-numeric style anchors on
  the `[N]` labels and strips the margin number from entry and continuation lines. Segmentation had
  anchored on the margin numbers, dropped the first entry, and merged the references after each
  page's line-number reset into one segment.

## [1.8.2] - 2026-06-11

### Changed

- Synced the vendored PyMarkdown linter to pymarkdown-skill 0.2.2. The lint wrapper uses
  PyMarkdown's `explicit` return-code scheme, so a scan system error or a file that PyMarkdown
  refuses to scan exits 2 instead of being reported as clean. The pre-pass recognizes tilde and
  indented fences and follows the config's front-matter settings, and the sync tooling carries
  robustness fixes. No change to hallucite's own behavior.

## [1.8.1] - 2026-06-10

### Fixed

- `mise run audit` forwards everything after the target to the audit script, so the documented
  flags, such as `--offline`, `--mailto`, and `--no-verify`, work. The output directory is set with
  `--out` instead of a second positional argument.
- The Codex plugin-cache resolver in `SKILL.md` compares cached versions with `sort -V`, so
  `1.10.0` beats `1.9.0`.
- Docs and plugin manifests no longer claim OpenAlex verification, which never ran because
  hallucinator's OpenAlex backend needs a key that the audit never configures. The database lists
  name the backends that actually run.
- `--offline` is documented as "no network" rather than "DBLP-only" and enforces it. hallucinator's
  local Standards matcher stays live and can set the status of standards references. A missing
  offline DBLP file disables the DBLP backend instead of falling back to dblp.org, and a second
  drift warning flags any backend outside `KNOWN_LOCAL_DBS` in `--offline` results.
- `triage.py` skips a JSON file with a missing or malformed `paper_id`, `pdf_path`, or
  `num_references`, such as null, instead of crashing `status` or `report`, and warns about a
  near-miss record.
- `run.sh check-env` warns when `pdftotext` (poppler) is missing, and README's setup section names
  it. `run.sh` also appends common install directories, such as Homebrew's and `~/.local/bin`, to
  `PATH`, so the extractor finds `pdftotext` the way the preflight does in a plugin shell with a
  minimal `PATH`.

### Changed

- README and PLAN no longer list Markdown lint as part of `run_smoke.py`. It runs as a separate CI
  step and locally through `mise run lint-md`.
- README and `SKILL.md` document the `--disable-dbs` audit flag and the `$HALLUCITE_VENV` override,
  and README drops the stale "GitHub once pushed" hedge.
- README, `SKILL.md`, and `CLAUDE.md` say that stages 1 and 2 use no LLM and that verification
  queries online databases unless `--offline` is set, replacing the "local and deterministic"
  claim. `CLAUDE.md` also states how status strings and backend names are validated.

## [1.8.0] - 2026-06-06

### Changed

- The plugin marketplace is renamed from `se-uhd` to `hallucite` in both the Claude Code
  (`.claude-plugin/marketplace.json`) and Codex (`.agents/plugins/marketplace.json`) manifests, so
  it installs as `hallucite@hallucite` and lists under `--marketplace hallucite`. The Codex plugin
  cache resolver prefers the `hallucite` marketplace's cached copy. The GitHub repo
  (`se-uhd/hallucite`), owning org, and plugin author and developer are unchanged.

## [1.7.1] - 2026-06-01

### Changed

- Renamed the environment readiness command from `run.sh doctor` to the clearer
  `run.sh check-env`.

## [1.7.0] - 2026-06-01

### Added

- Codex CLI packaging alongside the existing Claude Code plugin: `.codex-plugin/plugin.json`,
  `.agents/plugins/marketplace.json`, `plugins/hallucite` as the marketplace compatibility shim,
  `.agents/skills/hallucite` for repo-local Codex skill discovery, and `AGENTS.md` as a pointer to
  the canonical repo guidance in `CLAUDE.md`.
- Smoke tests for the dual manifests, the Codex symlink shims, and the expanded runner resolver,
  with an optional Codex CLI marketplace-list check when `codex` is installed.

### Changed

- The bundled skill resolves `run.sh` across Claude Code installs, repo-local Codex discovery,
  direct repo clones, and Codex plugin caches, with one shared skill and script tree.
- README, PLAN, CLAUDE.md, `run.sh`, and `mise.toml` describe support for both Claude Code and
  Codex CLI.

## [1.6.0] - 2026-05-30

### Added

- `run.sh`, a single bootstrap entry point for the pipeline (`doctor` / `audit` / `triage` /
  `lint` / `python`). It resolves, or on first use provisions at
  `${XDG_CACHE_HOME:-~/.cache}/hallucite/venv`, a Python 3.12 that can `import hallucinator`,
  preferring `uv` and falling back to a stdlib `venv` over a 3.12 found on PATH, in common install
  directories, or through `mise where`. It does not rely on a bare `python`, `uv`, or `mise` on the
  plugin shell's PATH, which had made the pipeline silently unrunnable as a plugin.
  `$HALLUCITE_PYTHON` reuses an existing hallucinator environment and skips provisioning.
- `run.sh doctor` prints `HALLUCITE_OK: <python> (hallucinator <version>)` on success, or a
  `HALLUCITE_BOOTSTRAP_FAILED:` line and a non-zero exit on any setup failure.
- Smoke tier 1b tests the fail-loud `run.sh` contract, and tier 1 checks that `SKILL.md` drives the
  pipeline through `run.sh` and carries the stop conditions.

### Changed

- `SKILL.md` adds a "Stop conditions -- never fabricate a verdict" section and routes every stage
  through `run.sh`. No script output means no verdict, and any non-zero exit or
  `HALLUCITE_BOOTSTRAP_FAILED:` line is a blocking error to report, never to work around by reading
  the bibliography by hand.
- README, CLAUDE.md, and PLAN.md document `run.sh` as the entry point, the mise-free plugin path,
  and the stop conditions.

## [1.5.1] - 2026-05-29

### Fixed

- `triage.py record --signals` accepts `venue_match=partial`, which the documented signal
  vocabulary lists but the validator had omitted.

### Changed

- `PLAN.md` describes the title-first triage design: the triage step, the verdict contract
  (structured fabrication signals and the `fcntl` lock on `triage_verdicts.json`), the
  Desk-reject candidates section, and `worklist --paper` slicing.

## [1.5.0] - 2026-05-29

### Added

- Title-first triage with structured fabrication signals. `triage.py record` takes a `--signals`
  JSON object (`title_match`, `matched_title`, `authors_match`, `venue_match`, `doi_status`) and
  enforces the rule that separates a citation error from a fabrication. A `partial-match` must name
  the real publication it matched (`title_match=yes` plus `matched_title`, or `na` for a
  non-publication resource), and a `likely-hallucinated` must assert that the cited title was not
  found (`title_match=no`).
- `triage.py report` shows each flagged reference's matched title and signal summary, warns on a
  `partial-match` whose signals say the title was not found, and adds a Desk-reject candidates
  section. It lists references with a cited title that matches no real publication, compounded by a
  fabricated author constellation, venue, or DOI.
- `triage.py worklist --paper <id>` writes one paper's slice by exact id and errors on an unknown
  id, so a parallel triage worker no longer risks pulling the wrong paper through a prefix id
  (`paper6` and `paper66`).

### Fixed

- `triage.py record` holds an `fcntl` lock on `triage_verdicts.json` during its read-modify-write,
  so concurrent workers no longer drop each other's verdicts.

## [1.4.1] - 2026-05-29

### Fixed

- Extraction no longer drops references in several edge cases. A numeric bibliography that starts
  above `[1]` is segmented from its first real entry, skipping stray page and DOI numbers. The
  References section is taken from the first heading, so a repeated "References" running header no
  longer truncates it to the last page. A trailing Appendix or Acknowledgments heading still ends
  the section, but a reference that merely begins with one of those words does not. The author-year
  detector looks for the year in the first 300 characters instead of 100, so a reference with a
  long author list is no longer missed.
- `triage.py report` deletes previously generated files first, so no orphan `verify-<pid>.md`
  remains. It shows retracted references that verified, prints a "Not verified" line for
  `--no-verify` references, stores a reference fingerprint to warn about a stale verdict after a
  re-audit, and identifies records by content, so a stray `.json` no longer crashes the run.
- `find_pdfs` matches `.pdf` case-insensitively and errors on an empty directory,
  `dblp_build_info` tolerates a non-string `last_updated`, `install-cli` refuses non-Darwin hosts,
  and the `requirements.txt` comment is corrected.

### Changed

- CI smoke workflow uses Node 24 actions (`actions/checkout@v5`, `actions/setup-python@v6`).

## [1.4.0] - 2026-05-29

### Fixed

- `--offline` now disables the DOI backend. The disable list named it "DOI Resolver", but
  hallucinator emits "DOI", so offline runs still made DOI lookups and could return a
  non-reproducible `verified` that hid a reference from triage. The list uses the real backend
  names and drops SSRN and NeurIPS, which hallucinator never emits, and the audit warns at run time
  when a configured name never appears in any result.
- The audit exits non-zero and prints a summary when a paper fails to process, instead of printing
  "Done" and returning 0 without the paper.
- The audit warns when a paper extracts zero references or has no References section.
- `triage.py record` warns when the given `paper_id:number` matches no audited reference, instead
  of silently storing an orphan verdict.
- The mise `audit` task quotes the DBLP path, so a path that contains spaces works.

### Added

- Smoke-test suite (`skills/hallucite/scripts/tests/run_smoke.py`) and a GitHub Actions workflow
  (`.github/workflows/smoke.yml`): packaging consistency, logic-contract unit tests, Markdown lint,
  and an offline end-to-end audit against a fixture DBLP database and a synthetic fixture PDF.

## [1.3.0] - 2026-05-29

### Fixed

- Triage no longer drops references whose database verdict is `mismatch`, a title match with
  mismatching authors. The worklist, the report, and the audit's `unverified` count filtered on
  `author_mismatch`, which the validator never emits at that level, so such references, including
  likely-hallucinated ones, never reached triage. `needs_triage` and the `unverified` total are
  derived by negation (any checked reference whose status is not `verified`), so an unrecognized
  status can no longer fall through.

### Added

- The offline DBLP database location is configurable through `$HALLUCITE_DBLP` (default
  `~/hallucite/dblp.db`), honored by `audit_references.py`, the `mise` tasks, and the bundled skill.

## [1.2.0] - 2026-05-28

### Changed

- Stage 3 triage searches in escalating breadth. When a title-plus-author query finds nothing, it
  broadens to an unquoted title search and screens the results instead of concluding "not found",
  since obscure and predatory venues are poorly indexed.

## [1.1.0] - 2026-05-28

### Added

- Bundled Markdown linter (PyMarkdown, vendored from se-uhd/pymarkdown-skill, no
  pip install) with a `lint-md` mise task and a `schema_checks.py` rule that
  validates the `SKILL.md` `name`.

### Changed

- `triage.py report` now writes valid GitHub-Flavored Markdown (blank lines around
  headings and lists, a single trailing newline, punctuation-trimmed headings) and
  auto-lints every file it writes, so the reports are well-formed by default.

## [1.0.0] - 2026-05-28

### Added

- Initial release. Extracts references from paper PDF files and verifies each
  against an offline DBLP database plus CrossRef, arXiv, OpenAlex, and Semantic
  Scholar. An LLM then triages the references no database confirms and writes the
  reports. Packaged as a runnable mise project and a Claude Code plugin.

[2.5.4]: https://github.com/se-uhd/hallucite/releases/tag/v2.5.4
[2.5.3]: https://github.com/se-uhd/hallucite/releases/tag/v2.5.3
[2.5.2]: https://github.com/se-uhd/hallucite/releases/tag/v2.5.2
[2.5.1]: https://github.com/se-uhd/hallucite/releases/tag/v2.5.1
[2.5.0]: https://github.com/se-uhd/hallucite/releases/tag/v2.5.0
[2.4.4]: https://github.com/se-uhd/hallucite/releases/tag/v2.4.4
[2.4.3]: https://github.com/se-uhd/hallucite/releases/tag/v2.4.3
[2.4.2]: https://github.com/se-uhd/hallucite/releases/tag/v2.4.2
[2.4.1]: https://github.com/se-uhd/hallucite/releases/tag/v2.4.1
[2.4.0]: https://github.com/se-uhd/hallucite/releases/tag/v2.4.0
[2.3.1]: https://github.com/se-uhd/hallucite/releases/tag/v2.3.1
[2.3.0]: https://github.com/se-uhd/hallucite/releases/tag/v2.3.0
[2.2.2]: https://github.com/se-uhd/hallucite/releases/tag/v2.2.2
[2.2.1]: https://github.com/se-uhd/hallucite/releases/tag/v2.2.1
[2.2.0]: https://github.com/se-uhd/hallucite/releases/tag/v2.2.0
[2.1.0]: https://github.com/se-uhd/hallucite/releases/tag/v2.1.0
[2.0.1]: https://github.com/se-uhd/hallucite/releases/tag/v2.0.1
[2.0.0]: https://github.com/se-uhd/hallucite/releases/tag/v2.0.0
[1.21.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.21.0
[1.20.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.20.0
[1.19.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.19.0
[1.18.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.18.0
[1.17.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.17.0
[1.16.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.16.0
[1.15.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.15.0
[1.14.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.14.0
[1.13.1]: https://github.com/se-uhd/hallucite/releases/tag/v1.13.1
[1.13.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.13.0
[1.12.1]: https://github.com/se-uhd/hallucite/releases/tag/v1.12.1
[1.12.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.12.0
[1.11.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.11.0
[1.10.2]: https://github.com/se-uhd/hallucite/releases/tag/v1.10.2
[1.10.1]: https://github.com/se-uhd/hallucite/releases/tag/v1.10.1
[1.10.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.10.0
[1.9.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.9.0
[1.8.4]: https://github.com/se-uhd/hallucite/releases/tag/v1.8.4
[1.8.3]: https://github.com/se-uhd/hallucite/releases/tag/v1.8.3
[1.8.2]: https://github.com/se-uhd/hallucite/releases/tag/v1.8.2
[1.8.1]: https://github.com/se-uhd/hallucite/releases/tag/v1.8.1
[1.8.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.8.0
[1.7.1]: https://github.com/se-uhd/hallucite/releases/tag/v1.7.1
[1.7.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.7.0
[1.6.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.6.0
[1.5.1]: https://github.com/se-uhd/hallucite/releases/tag/v1.5.1
[1.5.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.5.0
[1.4.1]: https://github.com/se-uhd/hallucite/releases/tag/v1.4.1
[1.4.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.4.0
[1.3.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.3.0
[1.2.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.2.0
[1.1.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.1.0
[1.0.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.0.0
