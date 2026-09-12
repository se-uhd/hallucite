# Changelog

All notable changes to hallucite are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- **The audit runs on hallucite's own modules.** `audit_references.py` builds a `Verifier` and
  parses through `reference_parser`; nothing on the audit path imports `hallucinator`.
  `DEFAULT_ONLINE_DBS` is the four backends `verifier` emits and `KNOWN_LOCAL_DBS` is `["DBLP"]`,
  or the two drift tripwires would fire on every run. `_second_opinion_pass` and
  `_author_absence_pass` are gone: the DBLP backend *is* the all-candidates check, and the author
  tier is now decided inside the rule rather than by a pass over whatever a lenient backend had
  cleared.

  Two regressions the cutover produced and the tests caught, both of them the new modules being
  stricter than what they replaced. A word a two-column layout splits with no hyphen to mark it
  ("distributed sy stems") went into the FTS query as a token the index does not hold, so a title
  the mirror held was not retrieved at all -- `titles_match` compares on letters and never saw the
  space, so the record was there to be found the whole time. Retrieval now asks one more query per
  short fragment, glued to its neighbour, and only where nothing else matched. And a citation that
  drops an elided particle ("Marcelo Amorim" for "Marcelo d'Amorim") no longer reads as a different
  person; the given name still has to pair, so it widens the surname rather than the rule.

- `measure/`: the measurements this entry cites, as scripts. `extraction_census.py` tabulates
  what every corpus paper extracts and what moved against a baseline; `corruptions.py` builds the
  corruption harness once, from a fixed seed, and scores an implementation against a built set;
  `head_to_head.py` scores the old and new parser and DBLP check over the recorded cases or the
  corpus, and keeps the old verifier off the network by construction; `mutations.py` reverts one
  fix at a time and requires the suite to fail; `residue_evidence.py` reads an offline audit's
  output and prints, per unverified reference, what the three items below found. The built sets
  live beside the other anchors in `~/hallucite/`.

- **The evidence the audit already had reaches the triager.** Three things `verifier` knew about
  an unverified reference that no worklist or report showed. Each was re-measured over the
  55-paper corpus's offline residue -- 788 of 2857 references -- before anything was built
  against it, because the numbers `TODO.md` carried came from a residue whose PDFs are gone. The
  worklist entry, the per-paper report and the verification sheet now carry all three; nothing
  here changes a status.

  - *That the mirror was asked at all.* The DBLP backend reports `skipped` for a title
    `queryable` refuses, and a `not_found` read the same whether the mirror came back empty or was
    never asked. Over the corpus residue that is 123 references, not the seven the head-to-head
    had counted: most are tools and web pages with a one-word title that the mirror would not hold
    anyway, but Breiman's "Random Forests", Cochran's "Sampling Techniques", Hubert and Arabie's
    "Comparing partitions", Seaman's "Qualitative Methods", Dolan's "Algebraic subtyping" and a
    dozen more real two-word publications are among them, and every one read as a clean negative.
    `skipped_dbs` travels with the worklist entry, and the report prints `Not asked: DBLP, ...`
    under the DB status, keyed on the one status string `verifier` emits for it and never on a
    list of names. The same list surfaced parser artifacts, recorded in `TODO.md`: a Springer
    `URL https://...` entry read as the title `URL`, and a title cut at its exclamation mark.

  - *What the cited identifier resolves to.* `verifier` fills `doi_info` and `arxiv_info` with the
    resolved title, and `triage.py` read neither. Resolved for the 169 residue references that
    carry a DOI or an arXiv id -- the DOI and arXiv backends only, nothing else asked, no request
    refused. Of the 127 DOIs, 88 resolve to the cited title, 34 to a different one and 5 are dead;
    of the 54 arXiv ids, six were never reached because the DOI ahead of them had already
    confirmed the reference, 25 resolve to the cited title and 23 to a different one. Reading the
    57 that differ: most are the parser's title carrying venue text (`..., arXiv preprint`,
    `Empirical Software Engineering 30, 1 (2025), 26`) or cut short (`VII`, `Hey!`, a bare `DOI
    10.48550/...`), where the resolved title is exactly what a reviewer needs; about a dozen are a
    preprint renamed between versions; a few are artifact DOIs whose deposit title differs from
    the paper's; and four name another work outright -- a DOI *and* an arXiv id for "Benchmarking
    LLM Test Generation on Complex Control-Flow Structures" that both resolve to "A Systematic
    Approach for Assessing Large Language Models' Test Case Generation Capability", a second DOI
    in the same paper, BashExplainer's DOI resolving to a paper on AutoML tools, and a
    "Syntax-aware Retrieval Augmented Code Generation" arXiv id resolving to a paper on narrative
    XAI. Three of the five dead DOIs are one the layout broke after a period (`doi:10.1109/ICET.2017.
    8281704`) and the parser kept only up to the break; the rejoin that covers an underscore does
    not cover this, and `TODO.md` records it. The worklist entry carries `identifiers` -- kind, id, whether it resolves, the resolved title, and whether
    that is the cited title under `titles_match` -- and the report prints one line per
    identifier: dead, resolves to the cited title, or resolves to a different title, named.

  - *The mirror's nearest title, gated on authorship.* `dblp_check.nearest_title` is a sibling of
    `record_context`: asked only where the DBLP backend answered `no_match`, it offers a record
    whose title is within two word-level edits of the cited one and requires every cited person to
    be on it. Retrieval leaves every pair of the title's selective words out of an AND query, so a
    record that still carries all but two of them comes back whichever two moved. Over the 619
    corpus residue references the mirror answered `no_match` for, 66 have a title within two
    edits ungated, and 33 of the 66 are different works -- Roy and Cordy's clone-detection survey
    against a 2019 paper of nearly the same title, Ford and Fulkerson's "Maximal flow through a
    network" against Strang's "Maximal flow through a domain", Kaplan and Meier against an
    encyclopedia entry, three Technometrics *reviews* of the cited statistics books, six Apache
    Software Foundation pages against one Computer column -- each of which would have argued a
    correct citation of an uncovered work into a "citation error". Gated, 32 remain and all 32 are
    the cited work: the content-word titles the head-to-head refuses on purpose ("in-depth study"
    for "In-depth Empirical Study", "state-aware" for "Context-Aware", "design implementation" for
    "Design and Implementation"), eight arXiv preprints whose citation glued ", arXiv preprint"
    onto the title, an "Elipse" typo, an HTML entity for an ampersand, and two Zenodo deposits
    offered the paper they accompany. The gate costs one real lead: Holmqvist's eye-tracking
    handbook, cited under its six authors where DBLP lists only the first, is refused because the
    record does not mark itself truncated. The lookup takes 47 s over the residue. `dblp_nearest`
    travels with the worklist entry, and the report prints it with the distance and the record's
    metadata.

  Guarded by smoke tier 3j through `attach_mirror_evidence`, `cmd_worklist` and `cmd_report`, and
  by six mutation entries; the mutation run fails for each.

- **The German transliteration of an umlaut pairs with the letter.** "Buettcher" answers to
  "Büttcher" and "Juergens" to "Jürgens". The reading is taken off the side that carries the
  umlaut, so only a name that really has one gains the second spelling; contracting `ue` in every
  name would rewrite "Miguel" and "Rodriguez" into spellings an invented author could hide behind.
  Measured before it was added: the corruption harness is unchanged on every column that decides
  -- 250 / 250 / 250 / 0 / 0 / 0 / 0 over the 250 complete records, 90 / 0 over the 90 truncated
  ones -- and one correct citation now confirms against the published twin of its sampled preprint
  rather than the preprint, because DBLP stores the same author as "Höfler" on one record and
  "Hoefler" on the other. On the recorded cases the head-to-head goes from 1508 to 1509
  confirmations against the old path's 1519; over the whole corpus, verified against the offline
  mirror alone, exactly the two references `TODO.md` named move from `mismatch` to `verified` and
  nothing else moves. The other seven name forms stay refused, for the reason given there.

- `build_dblp.py`: the offline mirror, built by hallucite. It replaces `hallucinator-cli
  update-dblp`, and with it the Rust toolchain, the prebuilt binary, `install-cli`,
  `install-cli-patched` and `dblp-entity-fix.patch` -- which existed because the stock ingest could
  not resolve the dump's character entities and dropped every author whose name carries a diacritic.

  The entities are resolved in the byte stream, as *numeric* character references rather than as
  characters: the dump declares ISO-8859-1, so UTF-8 spliced into it decodes as Latin-1 and
  "Jürgen" arrives as "JÃ¼rgen" -- the same mangled-name failure one layer down, and the first
  version of this script had it. An edited book records its people in `<editor>`, and that is who a
  citation of it names, so those are read where there is no author; a `<www>` person homepage is
  not a publication and would otherwise put three million people's names in the title index.

  Held to the mirror it replaces: 5000 records agree on title, year, type, electronic edition and
  the full author list, with none differing. Built end to end it produces 8,720,206 publications and
  4,295,062 authors, 246,351 of them with a non-ASCII name, and over the 2065-reference corpus the
  two mirrors confirm the same 1502 references with **not one** reference deciding differently. It
  takes 4.8 minutes against the previous ingest's 20 to 30, and needs nothing but the standard
  library.

- `reference_parser.py` and `verifier.py`: hallucite's own implementations of the two operations
  `VERIFICATION-SPEC.md` describes, written against `characterize.py`'s recording of the external
  package they replace.

  `parse_reference` reads one segmented bibliography entry. It recognizes each style by the mark
  that separates the author list from the title -- a standalone year, a parenthesized one, an
  "et al.", an opening quote, a colon after inverted names, a comma after initials-led ones, the
  run of surname-and-initials the medical styles print -- and falls back to the leading sentence.
  Measured over the 2065 references of the 41-paper corpus, with the offline DBLP mirror as arbiter
  (a reading is better when a real record confirms it), it is confirmed for 1480 references against
  1399 for the recording. Most of the difference is a venue that follows the title without an "In"
  and used to be read as part of it.

  Two references the recording confirms and this does not, each naming a person DBLP spells
  differently ("Rick Schlichting" for "Richard D. Schlichting", "Tom Zimmermann" for "Thomas
  Zimmermann"); the recorded parser stopped at 15 authors, so on the longer of the two there were
  fewer names to match. They reach triage as `mismatch` carrying DBLP's record, where the name
  difference is the first thing a reader sees. A third, StarCoder 2, was lost for a different
  reason and is fixed below: DBLP holds 57 of its 66 authors and writes `et al.` for the rest, so
  the ten it does not carry were being read as ten people the paper does not have.

  `check` asks five backends, cheapest first, and asks each only about the references the ones
  before it did not match: the offline DBLP mirror, CrossRef's bibliographic search, DOI resolution
  through CrossRef and then doi.org content negotiation, arXiv by identifier a hundred at a time,
  and Semantic Scholar's paper search one reference at a time. Open Library, PubMed and Europe PMC
  are not covered; over the corpus they decide 1.4% of confirmations between them, the statistics
  classics an empirical paper cites and the books it cites without a DOI, and a reference only they
  would have matched is now reported as `not_found`, which records a weaker search rather than a
  stronger claim about the reference.

  Semantic Scholar is asked only where `--s2-api-key` or `$S2_API_KEY` supplies one. Anonymous
  callers share one small quota: asked about 106 real residue references, paced three and a half
  seconds apart, it refused 102 and confirmed none of the four it answered. Asking anyway would
  mark an arbitrary handful of references degraded and a different handful next run, which is the
  churn that moves the boundary between `verified` and "needs triage" between identical audits.

  With a key it answers 102 of those 106, and over the whole 510-reference set it decides two
  confirmations no other backend reaches, both of them books or technical reports. The recording
  credits it more than that -- 24 of its 1669 confirmations, the 1.4% `VERIFICATION-SPEC.md`
  records -- because it was asked about a different residue: this implementation puts CrossRef and
  the DOI resolver ahead of it, and they take most of what it would otherwise have answered. It is
  kept because nothing else covers that material, and both numbers are here so the next person can
  decide whether to drop it from the same measurement.

  Held to the recorded verdicts of all 2065 references: run end to end, the new modules confirm
  1666 against the recording's 1669, losing 44 and gaining 41. Reading the 44: 19 are a `mismatch` the recording cleared, five of which name a real
  paper under an author list mostly not on it; eight are a tool or a web page with no author, which
  the recording confirmed by matching a title against some unrelated record; and four are citations
  that drop a word from the real title -- "An in-depth study" for "An In-depth Empirical Study",
  "Advanced compiler design implementation" for "Advanced Compiler Design and Implementation" --
  which the triage rules say a human should confirm rather than a matcher.

  Of the recording's verdicts, 266 unverified references carried a backend failure, so not one of
  those was a clean negative; 53 of the new run's do.

  Fed the *recorded* parse instead, so that the two halves stay separable, `check` confirms 266 of
  the same 295. The gap is the recorded parser's output meeting a stricter check: a venue glued
  into the title ("Pixy: a static analysis tool ... 2006 IEEE Symposium on Security and Privacy")
  no longer passes a DOI that resolves to the real title, and a surname-only author list
  ("Akhavan", "Hosseinpour") no longer passes the author rule. Both requirements are deliberate,
  and both gaps close when the new parser feeds the new verifier.

- Retraction status, where CrossRef answered about the reference anyway. It carries the relation in
  the record it was going to return, so this costs no extra request; a reference the offline mirror
  confirms is not retraction-checked, because asking would cost a request per confirmed reference.
  Publishers deposit the relation in both directions and write the marker into the title as well,
  so all three are read.

### Fixed

- **Five corpus papers lost their whole bibliography, and three more were losing entries quietly.**
  Adding EMSE and JSS to the corpus put the unnumbered hanging-indent author-first bibliography in
  front of the extractor for the first time -- Elsevier's Harvard style, which ends the author list
  with a bare year (`Cao, S., Sun, X., 2024.`), and Springer's plainnat, which puts the year in the
  venue field hundreds of characters later. `_dominant_style` counted an entry as author-year only
  on a *parenthesised* year, so two papers read as no style at all and were never segmented, and
  three read as numeric on a handful of continuation lines that open with digits (`1142. URL:
  https://doi.org/...`, a wrapped page range) and segmented as one entry. The same gate was already
  costing the three author-year papers among the original 41: the ACM author-year paper lost every
  two-author entry (`Haipeng Cai and Raul Santelices. 2014.` does not match `_AUTHORYEAR`), and
  the two Springer papers lost every organisation (`OpenAI (2024)`, `GitHub (2021)`), all glued
  into the entry before them where only a second `(year)` gave them away.

  The hanging indent is the structural signal -- an entry starts at the left edge, its continuations
  are indented -- and `_entry_indent` already found it for the author-year path. Four things had to
  change for it to carry the weight. The right column of a two-column page is shifted to the left
  column's text edge before anything reads the indents, because the gutter cut leaves the right
  column's text two characters in under an ACM template and seven under Elsevier's, where "entry"
  in one column meant "continuation" in the other; the centred page number the cut lands inside the
  right column is dropped rather than moved to the entry column. With a hanging indent, only a line
  at the entry column can vote for a style, so a digit-led continuation is not a numeric label. At
  the entry column an entry needs no year to count, only to open with a name (or an organisation)
  and go on to more names, an "and", an "et al.", a year in any form, or a lone author's period
  and the title's capital (`Tom Mens. A state-of-the-art survey ...`); `_AUTHORYEAR` stays the
  gate where there is no hanging indent. And the block ends where the layout does: Elsevier prints
  the authors' biographies after the bibliography under no heading, as justified paragraphs at the
  entry column, and one paper carried nine "references" of prose about where its authors studied
  before a lowercase line at the entry column was read as the end of the hanging-indent block.

  | paper | before | after |
  |---|---|---|
  | `emse-2605.16646v1` (Springer, plainnat) | none, 0 | 22 |
  | `jss-2606.08553v1` (Elsevier, two-column) | none, 0 | 38 |
  | `jss-2601.12148v3` (Elsevier, abbrvnat) | numeric, 1 | 45 |
  | `jss-2605.26609v1` (Elsevier) | numeric, 1 | 59 |
  | `jss-2609.08953v1` (Elsevier, two-column, biographies) | numeric, 1 | 43 |
  | `fse-2607.23355v1` (ACM author-year) | 52 | 67 |
  | `emse-2607.13820v1` (Springer) | 22 | 25 |
  | `emse-2608.11965v1` (Springer) | 59 | 79 |

  Every entry-column line in the eight papers now opens an entry except one ACM footer
  (`Received 2023-09-29; accepted 2024-01-23`), which is appended to the last reference where it
  stays visible. The other 47 corpus papers extract exactly as before; the corpus goes from 2615
  references (2 unparsed) to 2857 (0 unparsed). Guarded by smoke tier 4i, which drives the column
  alignment, the style vote, the entry gate and the biography stop through `extract_references`
  on a three-page synthetic paper, so no one of them can be reverted without the others noticing.

- **Three parser gaps the new bibliographies exposed.** Elsevier joins the venue to the title
  with a comma rather than a period (`Coca: Improving and explaining ... detection systems, in:
  Proceedings of the IEEE/ACM 46th ...`), so no sentence break separated them and the venue was
  read as part of the title: over the JSS residue that was most of the `not_found`. A hyphenated
  initial (`K.-W. Chang`) was neither an initial in the IEEE comma reading nor an abbreviation in
  the sentence reading, and `..., B. Ray, and K.-W. Chang. Unified pre-training ...` parsed to the
  title `and K.-W`. And LaTeX abbreviates an accented given name to `J.ã.P.`, which pdftotext
  renders `J.a.P.`, so `Fernandes, J.a.P.` read as two people. Over the 55-paper corpus, verified
  against the offline mirror alone, the three lift confirmations from 1981 to 2057: 75 references
  from `not_found` to `verified`, 2 from `not_found` to `mismatch` on a name form the record now
  retrieves, none the other way. The five recovered papers confirm 19 of 22, 34 of 38, 37 of 45,
  34 of 59 and 37 of 43.

- **The DBLP path against the verifier it replaced.** Reproduced head to head over the 2065
  recorded citations, DBLP only and offline: the old parser and old DBLP check confirm 1519, the
  new ones 1502, gaining 34 and losing 51. The 51 read one at a time, against the record the old
  path matched: 23 are `mismatch` -- the five citations naming people who did not write the paper,
  nine real discrepancies the rule exists to flag, and nine name forms (`Rick` for `Richard D.`,
  `Buettcher` for `Büttcher`, `Weibgerber` for `Weißgerber`) -- and 28 are `not_found`, of which
  fifteen cite a title that differs from the record's in a content word and are refused on purpose,
  seven are two-word titles the mirror is not asked about, and six are defects, fixed here:

  - Retrieval missed a title the decision would have accepted, on three shapes: a word split
    inside the *record's* own title (`Code Clone Detection U sing Functionally Equivalent
    Methods`), a word split in the citation with both halves too long for `_glued_query` to treat
    as a fragment (`chal lenges`), and an article the layout glued to its neighbour (`Ac/c++
    code`). One fallback covers all three: AND queries over the title's words with one adjacent
    pair left out, asked last and only where nothing else matched, since `titles_match` compares
    on letters and never saw the split. It also confirms the one record of the 250-record
    harness the clean citation had been missing, a title carrying `ℒ2-gain`.
  - An edition suffix on the record, in both shapes DBLP writes it (`(2. ed.)`, `, 3rd
    Edition`), is trimmed before the comparison; the parser already trimmed the citation's.
  - An alias DBLP writes in parentheses (`Tse-Hsun (Peter) Chen`) kept `Peter` from pairing.

  Those six move; the recorded head-to-head ends at 1508 against 1519. Two of the eleven the
  reading in `TODO.md` called defects are not: the old path had confirmed the Jest documentation
  page "Getting Started" against a 1991 keynote of that name, and a standards body's "Security
  Framework 1.1" against a 1988 paper called "A Security Framework". A record-side prefix
  tolerance would reproduce both, and they stay unverified. Over the whole 55-paper corpus, where
  the recovered bibliographies count, the new path confirms 2068 against the old path's 2009.

  `_MIN_TOKENS` was measured at 2 and stays at 3. Scored on corruptions built once and handed to
  both settings -- the same 250 real records as before, plus a second set of 250 records with
  two-token titles, which is the population the constant changes and the one the first set cannot
  see:

  | `_MIN_TOKENS` | cases | corpus | 3+ tokens: clean / et al. / first / +1 / +2 / +3 / swapped | 2 tokens: clean / +1 / +2 / +3 / swapped |
  |---|---|---|---|---|
  | 3 | 1508 | 2068 | 250 / 250 / 250 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 |
  | 2 | 1513 | 2077 | 250 / 250 / 250 / 0 / 0 / 0 / 0 | 250 / 1 / 1 / 1 / 0 |

  The padded two-token citation that confirms is `Book Reviews`, a title 922 records share, one
  of which carries an `et al.` row and lists a name the padded citation also lists. On the corpus
  the nine confirmations include one that is wrong -- Sommerville's textbook "Software
  engineering", tenth edition, confirmed against his 1983 conference paper of that title -- and
  six references move from `not_found` to `mismatch` against records of different works
  ("Github copilot" against a 2024 paper about it, Fowler's "Continuous integration" page against
  an XP 2009 paper, "Virtual threads" against a DIS paper, "Logistic regression" against an
  encyclopedia entry). A false confirmation is the outcome the tool must not produce, and the
  three real two-word titles it would recover ("Reproducible containers", "Random Forests",
  "Sampling Techniques") reach triage as `skipped`, which is true. The rule that would have
  rescued the name forms was not added either: each is a real person written two ways, and every
  reading that pairs them pairs something else.

- **The lenient tier was a wildcard.** Against a record that is not a complete author list, an
  unmatched cited name is absence of evidence and does not refute -- and nothing required any
  cited name to be *present*, so "StarCoder 2" cited under two invented names verified against
  its 57-person record, and any author list at all on "Book Reviews" verified through the one
  record with an `et al.` row. The people a truncated record does list are evidence: a citation
  that pairs with none of them has had every name it offered come back foreign, and is refused.
  DBLP keeps the first authors when it truncates and a citation names them first, so a correct
  citation pairs at least one. Measured on a third set of 90 records that carry an `et al.` row,
  cited correctly (first three names and `et al.`) 90 confirm before and after; cited under two
  invented names 90 confirmed before and 0 after; one invented name appended to three real ones
  still confirms, which is the tier doing what it is for. Nothing moves on the recorded cases or
  the corpus. A record credited to a group rather than to people (`OpenAI`, `Qwen Team`) has no
  person to pair against and still clears on the title; "GPT-4 Technical Report" under two
  invented names verifies, and only the arXiv backend, asked by identifier, can say otherwise.
  `VERIFICATION-SPEC.md` now states the bar.

  The 250-record harness the strictness is measured on is unchanged by any of this: correct
  citations 250, `et al.` 250, first author only 250, one, two or three invented names appended
  0, one swapped 0, a content word changed 0, word order reversed 0, an invented title 0, a
  subtitle dropped 29 of 29, respaced 250. Every fix above carries a smoke guard asserted through
  the function the pipeline calls, and a mutation run -- revert one fix, run the suite -- fails
  for each.

- **The phantom-author rule had one tier where the contract asks for two.** `verifier` applied
  "every cited name must be matched" to every backend and every record, with no equivalent of
  `_complete_author_dbs`, so a record that is not a complete author list was read as one. Over the
  2065-reference corpus that refused 42 references the recording confirms, and reading the flags
  rather than the count says why: 18 are an LLM technical report DBLP credits to the group rather
  than the people (`OpenAI`, `Qwen Team`, `Llama Team`, `DeepSeek-AI` -- one stored author against
  a citation that correctly names ten), one is StarCoder 2, whose record holds 57 of 66 authors and
  writes `et al.` for the rest, and the remainder are name forms (`Mike` for `Michael Van
  Emmerik`, a parenthesised nickname in `Tse-Hsun (Peter) Chen`, `Buettcher` for `Büttcher`).
  Five are the citations the rule exists to catch.

  The tier is now read off the data, per run and per record, as `VERIFICATION-SPEC.md` requires:
  `mirror_authors_complete` asks whether this mirror's ingest kept its accented authors, and
  `record_authors_complete` whether the byline in hand is a list of people at all. Against an
  incomplete record an unmatched cited name is absence of evidence and does not refute; a name the
  record *contradicts* -- it carries that surname under a different person -- still does.

  What it costs, measured the way the rule that motivated it was measured. Over 250 real DBLP
  records: correct citations 250, `et al.` 250, first author only 250, and one, two or three
  invented names appended confirmed **0** times, unchanged -- none of those 250 records is
  incomplete, which is the point. Over the 2081 references extraction produces from the 41 papers,
  the offline mirror now confirms 1521 against 1503; over the 2065 the recording holds, the
  references it confirms and this refuses fall from 42 to 24, and the 24 are the five bad citations
  plus name forms a human should read. Against a mirror built by the stock `hallucinator-cli`,
  whose ingest drops every author whose name carries a diacritic, the 154 correctly cited
  references it refused fall to 8.

- **A backend that answered 200 with a body it could not read was reported as a clean negative.**
  `_arxiv_entries` returned an empty dict both for "arXiv holds none of these identifiers" and for
  "that was not a feed", and an HTML outage page is well-formed XML with no entries. The result was
  `no_match`, an empty `failed_dbs`, `degraded: false` -- and `arxiv_info.valid=False`, which is
  the shape of fabrication signal (D). One bad batch response covers up to a hundred identifiers.
  The root tag now separates the two, which is what `_fetch_json` already did for the JSON backends
  ("a JSON endpoint answering with HTML has not answered").

  Three siblings went with it: a 404 from the CrossRef or Semantic Scholar *search* endpoint said
  the endpoint moved, not that the work does not exist; a CrossRef 200 carrying no `items` key is
  an error envelope, not an empty result set; and Semantic Scholar's soft refusal is a 200 carrying
  `{"message": "Too Many Requests"}`, which was read as an empty result and also reset the
  give-up counter. The contract's rule is that a backend which did not answer must never be
  equivalent to `no_match`, because triage is told to weigh a `not_found` from an incomplete run
  less -- and an empty `failed_dbs` is what tells it the run was complete.

- **Semantic Scholar's give-up counter never tripped under an intermittent block.** It counted
  *consecutive* refusals, and this backend throttles in bursts -- one answer in twenty resets it --
  so on a real corpus it never reached 25 and every refused reference still paid the full retry
  ladder: four attempts at 2, 4, 8 and 16 seconds on top of a 45-second ceiling each. A
  2065-reference replay spent most of three hours there for the 1.4% of confirmations this backend
  decides.

  The ladder is the expense, not the question, and the fix is to stop retrying rather than to stop
  asking. Measured on the residue: a refusal costs 31 s with the ladder and about a second without
  it, while an answer takes 3 to 18 s either way. After 25 refusals however they fall
  (`_S2_PATIENCE`) the extra attempts are dropped and every remaining reference is still asked. The
  consecutive counter stays as it was, because 25 refusals in an unbroken run is a block rather than
  a throttle, and there is nothing to be gained by asking through one.

  Capping the *asking* was tried first and measured against the same corpus: it cut the run from
  three hours to 57 minutes and the references carrying a backend failure from 177 to 60, and it
  cost five confirmations no other backend reaches. Asked again with the ladder dropped instead,
  Semantic Scholar matches 8 of the 49 references that replay lost -- the five it had stopped
  asking about, and three the ladder had already exhausted its patience on.

- **A verdict of `author_mismatch` where nothing had been compared.** When every name in a parsed
  author list is a venue fragment the parser bled in, `matched_authors` reports nothing comparable,
  and the reference was reported as a record whose authors disagree -- a near miss a triager is
  shown and asked to weigh. It is `no_match`, which is what `_verdict`'s own docstring said all
  along.

- **A particle surname written surname-first parsed to no authors at all.** `_name_like` wanted a
  capitalised word, and `d'Amorim` -- which `VERIFICATION-SPEC.md` names -- has none, so the whole
  Springer-style byline failed to read as an author list and the entry fell through to its
  no-author reading. A reference with no authors cannot be confirmed by anything. `van den Bergh`
  and `De Lucia`, the other two names the contract gives, were already right in both orders.

- **An organisation was split on its own `and`.** "Institute of Electrical and Electronics
  Engineers" became two authors, "Barnes & Noble Research" two more, and under the author rule both
  halves then had to be matched by a real person. A byline with no comma, no initials, a lowercase
  function word and eight words or fewer is one body's name. The bounds matter: without them a
  whole entry whose title carries "for" and "and" reads as a single corporate author, which cost
  one corpus reference its title before the bound was added.

- **A suspended hyphen was closed like a line break.** "Joining Player- and Data-Driven Analytics"
  became "Player-and". A hyphen before a conjunction elides the second half of a compound and the
  space after it is the word boundary, not the layout's.

- **A DOI broken at an underscore was emitted as its first half.** `_looks_cut` knew a trailing
  hyphen and a digit-free suffix; a break at `_` leaves a suffix that ends in a digit and looks
  finished. What survives is the *book's* DOI where the citation named a chapter --
  `10.1007/978-1-84800-044-5` for `..._2` -- and it resolves, to another work, which is the
  mismatched-DOI shape triage weighs as signal (D). pdftotext renders the underscore as a space, so
  the far side is still in the text: four corpus references are now rejoined and every one resolves
  to the title its entry names (`..._8` to "Reporting Experiments in Software Engineering",
  `..._2` to "Qualitative Methods", `10.1007/978-3-030-16145-3_25` to "DeepReview", and ACL's
  `10.1162/tacl_a_00335`, which loses two underscores rather than one).

  Withholding a bare ISBN suffix instead was measured and rejected: it is also what a citation of
  the *whole book* correctly carries, and two corpus references carry one -- one of them a
  confirmation the DOI resolver made. The rejoin fires only where the text actually continues, and
  not on a four-digit year, which is the entry's own date running on. All 590 DOIs the corpus
  carries still come through.

- **One inverted author split across two chunks read as two people.** `Zeller, Andreas. 2009. Why
  Programs Fail.` parsed to `['Zeller', 'Andreas']`, and because pairing is one-to-one the two
  competed for the single record author "Andreas Zeller" -- leaving one of them unmatched, which
  the author rule then read as a person the record does not have. The record settles it: two cited
  entries that pair with exactly one record author, the same one, and whose words together are
  contained in that author's name, are one person written apart. An invented "Mallory Fake" pairs
  with nobody and is never excused.

  Merging the two chunks in the parser instead was measured and rejected. It is not decidable
  there -- `Akhavan, Hosseinpour` is two people and `Zeller, Andreas` is one, and nothing in the
  string says which -- and over the corpus it changed no reference's author list and no
  confirmation either way.

- **An entry lost from the front of a bibliography was invisible.** `_missing_numbers` walked the
  run from the lowest number that arrived, so a bibliography whose extraction begins at `[2]`
  reported no gap. It walks from 1 now, and that alone found a sixteenth lost reference:
  `tse-2607.29422v1.pdf` prints `[1] Aider, "Aider," 2026` in the right column beside a figure, and
  it never reached verification.

  The matching check for a swallowed *tail* was measured and cut back to the bracket styles. A
  plain-numeric bibliography prints `30.`, which is not a distinctive label: over the 41-paper
  corpus the bare-number form found exactly one thing, an access date broken across a line
  ("2026-05- 30. Shamse Tasnim Cynthia..."), and no real swallowed entry at all.

- **`triage.py`'s matched-record test is named positively.** It excluded the failure statuses by
  name, which is how a `timeout` came to read as a matched record in the first place; adding
  `timeout` to the list left the next new status to do the same. `match` and `author_mismatch` are
  the two that mean a candidate came back, and they are what it now asks for -- the rule CLAUDE.md
  states for the per-reference status, applied to the per-backend one.

- **`run.sh` died on an ordinary `.env.local` line without its sentinel.** An indented comment or
  an `export FOO=bar` produced `export: not a valid identifier`, and under `set -e` that ended the
  run with a bash error and no `HALLUCITE_BOOTSTRAP_FAILED:` line -- the one thing the wrapper
  promises never to do, and the sentinel SKILL.md's stop conditions key on. A CRLF file exported
  the API key with a trailing carriage return. mise's dotenv reader accepts all three, so the two
  did not in fact see the same values; they do now.

- **`record_context` compared titles through a copy of `_letters`** whose comment called it looser
  than the confirmation path. It is the same reduction, and stricter -- it carries none of
  `titles_match`'s tolerance for a subtitle on one side only, which it needs to be, because this
  has to name exactly one record to be evidence at all. The duplicate is gone and the comment says
  what the code does.

- **Seven of the fixes in this release could be reverted with the smoke suite still green.** A
  mutation run over `run_smoke.py` -- revert one fix, run the tests -- found that the `timeout`
  fix above, the Semantic Scholar threshold, the FTS row ceiling, the apostrophe fold, doi.org's
  ceiling and both extraction fixes were unguarded. The pattern was guards written as
  `C.eq(x, MODULE.THE_CONSTANT)`, which pass whichever value the constant holds, and helpers
  asserted directly while the caller that ignores them is not. Tiers 6, 6b, 6c and 6d pin the
  measured numbers as literals and exercise the callers; every mutation above is now caught.

- **A bibliography could lose whole references and nothing downstream could tell.** Over the
  41-paper corpus, 15 references the bibliographies' own numbering prints never reached
  verification: seven at the tail of one paper, eight swallowed by the entry before them. A
  reference that never arrives cannot be reported as unverified, so the audit had no way to say so
  and the reader had no way to ask. Extraction now produces 2081 references against 2066, with no
  gap left in any of the 41 numbering runs, and the offline mirror alone confirms 1503 of them
  against 1483.

  Three causes, all in `pdf_references.py`:

  - The running head hides the gutter. It spans both columns, so the column gap is not blank on its
    line, and `_gutter` weighs such lines as a *proportion* of the page -- which means the same
    head passes on a full page and fails on a short one. A final bibliography page of 33 lines
    gives one bridging line 3% of the vote and loses the column split for the whole page, and with
    it seven references. Page furniture is now removed before the gutter is measured.
  - The cut was placed at the midpoint of a band found at 97% tolerance, so on a page where one
    line runs into the band it landed inside that line's word, leaving a letter behind and gluing
    the next entry onto its predecessor. It now falls in the longest run of columns blank on every
    line.
  - A reference can trip both of the running-head filters at once. Five entries in one paper read
    `[N] "CVE-2022-1975,"   https://nvd.nist.gov/...`: the justification gap is the wide gap a head
    keeps, and `_head_norm` strips the digits that are the only thing telling the five apart, so
    they counted as repetitions of one another. `_segment` now asks whether a line opens the next
    entry in the sequence *before* the noise filters, which a head cannot satisfy: it would have
    to carry the one number the sequence expects next.

  Comparing furniture also needed narrowing. What varies between one page's head and the next is
  the page number, which sits at one end of the line, so only a leading and a trailing number are
  removed; stripping every digit, as `_head_norm` does, collapses two different references onto
  each other and reads the pair as a repetition.

- Extraction reports the entry numbers a numbered bibliography prints that no reference carries,
  and the audit warns about them. It is the one invariant such a bibliography gives for free, it is
  what caught all three faults above, and it is the only way a swallowed entry is visible at all.

- **A citation could append invented authors to a real paper and still verify.** The rule was that
  greedy pairing had to match `min(cited, stored)` authors, and padding the citation raises only
  the cited side, so the stored side kept fixing the threshold. Measured over 250 real DBLP records,
  appending one, two or three invented names to the true author list was confirmed 250 times out of
  250. That is signal (A) in `SKILL.md` and the pattern `VERIFICATION-SPEC.md` calls the one this
  tool exists to catch -- a real title, a real venue, correct pages, and people who did not write
  the paper. `_author_absence_pass` could not catch it either: it compares only lists of equal
  length, which a padded citation is not.

  Every cited name that reads as a person must now be matched by an author of the record. The
  citation may still name *fewer* authors than the record, which is what "et al." means. Measured
  against the same mirror and the same parser:

  | author rule | corpus confirmed | clean | "et al." | first author only | +1 invented | +2 | +3 | one swapped |
  |---|---|---|---|---|---|---|---|---|
  | `min(cited, stored)`, >=2 matched | 1459 | 250 | 250 | 0 | 250 | 250 | 250 | 0 |
  | every cited name, >=2 matched | 1455 | 250 | 250 | 0 | 0 | 0 | 0 | 0 |
  | every cited name | **1478** | 250 | 250 | 250 | 0 | 0 | 0 | 0 |

  The "at least two matched" rule went with it. It refuses 23 corpus references, every one of them
  a real work cited as "First Author et al.", and it refuses no corruption that one matched name
  lets through.

  What that buys, on the corpus rather than on constructed corruptions: 18 references the recording
  confirmed are now a `mismatch`, and five of them name a real paper under an author list mostly
  not on it. `RepoFuse` and `BashExplainer` pair one cited name in five with the record, `RepoHyper`
  none in three, `RepoFormer` two in four -- a correct title and DOI, and people who did not write
  the paper. The old verifier cleared all five without a human seeing them. Of the other 13, eight
  differ by one or two names and five carry a title the mirror does not hold at all.

- Name comparison is now a pairing rather than a subset test, which is what the contract asked for
  and what the corruption corpus shows the difference between. A middle initial the record does not
  carry no longer refutes ("Mohammed F Kharma" is "Mohammed Kharma", "C. E. Jimenez" is "Carlos
  Jimenez"), a particle on one side only no longer refutes ("Emiliano De Cristofaro" is
  "Cristofaro, E."), and a generational suffix is not a name word. What still refutes is a
  contradicted given name: a citation naming "Q. Muñoz Barón" for "Marvin Muñoz Barón" was
  confirmed 22 times in 250 by the first version of this rule and is confirmed none.

  Author *lists* are paired the same way, by augmenting paths rather than first-fit. Taking the
  first partner that fits lets one cited name consume the record author another needs -- "Xin Xia"
  fits both "Xin Xia 0001" and "Xin Xiao" -- and refuses a correctly cited paper.

- Title comparison now reads letters alone and tolerates a subtitle on one side only, as the
  contract requires. Removing a hyphen without leaving a space made "Model Driven" and
  "Model-Driven" different titles, and a suspended hyphen ("Player- and Data-Driven") different
  from itself. Measured over 250 real DBLP records: exact titles 250, respaced and rehyphenated
  titles 250, subtitles dropped 41 of the 71 that carry one; one content word changed 0, word order
  reversed 0, a wholly invented title 0.

- The offline DBLP query took the 50 lowest row ids rather than the 50 best matches -- SQLite
  returns FTS hits in row order, and 3 of the corpus's 1,478 confirmations come from a record its
  query returns past row 50, one of them at row 2,507. Raising the ceiling costs no measurable
  time.

- A title carrying a letter with a stroke or a bar did not match its own record. The query folded `ł`, `ø`
  and `ß` to plain letters, which an author comparison must do, but the FTS index holds them as
  they are; both foldings are now asked. And the word-wise AND query offers both readings of every
  hyphen at once, which a phrase query cannot: "Sample-based non-uniform random variate
  gener-ation" needs the compound reading for two of its words and the line-break reading for the
  third.

- A version number the layout broke across a line read as two sentences, so "Deepseek-v3. 2:
  Pushing the frontier" was cited as "Deepseek-v3" and matched nothing. A period between two digits
  is not a sentence end; a period between a letter and a digit still is, which is what keeps a venue
  opening with its year out of the title ("... vulnerabilities. 2006 IEEE Symposium on ...").

- The parenthesis an entry appends to its own title stayed in it: the conference acronym ACM prints
  ("Phraselette: A Poet's Procedural Palette (DIS '25)"), an edition ("... for the Behavioral
  Sciences (2 ed.)"), a year with no comma before it.

- A stray mark between two names disqualified the whole author list. "OpenAI, :, Aaron Hurst, et
  al." parsed to no authors at all, and a reference with no authors cannot be confirmed by anything.

- A rate limit that named no `Retry-After` was retried after a fixed two seconds, which walks
  straight back into the same limit. Each attempt now doubles its wait, which is what Semantic
  Scholar's API asks callers to do, and that backend gets extra attempts of its own.

- doi.org's content negotiation timed out on the records only it can resolve. It redirects to
  whichever registry holds the DOI, and DataCite took 8 to 32 seconds to answer for real Zenodo
  DOIs against a 15-second ceiling -- so the artifact and dataset references that have no other
  identifier to check were the ones being reported as unresolvable. That path gets 45 seconds.

- A line-break hyphen went out to the online searches verbatim, and no index holds that spelling.
  "Modeling library popu-larity within a software ecosystem" found nothing at CrossRef or Semantic
  Scholar until the joined reading was asked for as well. The second form is only asked when the
  first matched nothing. It is weaker than what the mirror does for its own queries: `_and_query`
  offers both readings of each hyphen independently, and the online form is all-or-nothing, so the
  16 corpus titles carrying a real compound and a line break at once are asked in neither of the
  two spellings that would find them.

- Semantic Scholar's search is slow enough that the ordinary 15-second ceiling turned ordinary
  answers into timeouts, and a timeout claims nothing about the reference. It gets 45.

- An eszett a PDF renders as a capital B is read as one. `Leßenich` comes out of pdftotext as
  `LeBenich`, and the same file renders it correctly in its own body text, so this is a font
  encoding rather than a flag. Five corpus confirmations, and no cost: the reading is offered
  alongside the literal one, so a name that really carries a B keeps it. Measured by disabling the
  reading over the corpus it is worth three confirmations, not the five first counted; it fires
  only on a capital B, and one corpus reference renders the eszett as a lowercase b
  ("P. Weibgerber" for "Peter Weißgerber") where nothing can distinguish it from a real name.

- An apostrophe was compared rather than folded, so `O’Donoghue` and `O'Donoghue` were two
  people. Citations, PDF extraction and DBLP each write it their own way, and the surnames it
  appears in are common enough that this cost seven corpus confirmations on its own.

- `Al` is a name particle, and the author tokenizer was deleting it as the tail of "et al." --
  3,999 DBLP authors carry it, and "Fahmid Al Rifat" could not match a citation of itself.

- A year the entry printed after its title, with no comma to mark the field, stayed in the title
  ("Causes and canonicalization for unreproducible builds in java (2025)").

- A DOI broken across a line was emitted as the half before the break -- at one of its own hyphens,
  after a period, or between `10.48550/arXiv` and the identifier, where both halves carry digits
  and only a real arXiv id tells them apart. Eighteen corpus references carried a DOI that resolves
  to nothing, which triage reads as a fabrication signal. Thirty more carried none at all, their
  identifier broken at the slash.

- An arXiv identifier written as a CoRR volume is read: `arXiv, vol. abs/2410.15631` and `CoRR,
  vol. abs/1901.09102` are how the IEEE styles print one, and 17 corpus references carry an
  identifier only in that form.

- An arXiv identifier a batch request omits is now asked for again on its own before it is called
  dead. arXiv answers 200 and drops what it will not serve -- an old-form id written with its
  subject class, as citations write it -- so the omission was being reported as an identifier that
  does not exist, which is the same signal a placeholder id gives.

- Where several DBLP records share a title, the published one now comes first instead of whichever
  has the lower row id, and where none of them matches the authors, the near miss reported is the
  record accounting for most of them. 17% of corpus references carry a shared title, and the record
  chosen is the one a triager is shown.

- **Among records that all match, the year the citation prints picks the one shown.** Where
  several records share a title and every one carries the cited authors, `paper_url` pointed at
  whichever row order put first, CoRR last: Fowler's *Refactoring* at the XP 2002 talk rather than
  the 1999 book, Tokuda and Batory's 2001 journal article at their 1999 conference paper, Wohlin's
  2012 book at its 2024 edition. Measured first, over an `--offline` audit of the 55-paper corpus:
  2106 references verify through the mirror, 679 of them on a title more than one record matches,
  and for 631 the other records are all CoRR preprints, which the published-first order already
  settles. 48 share their title with another published record. For 21 of those the record shown
  carries a year the citation does not print while another matching record does -- five
  journal-first papers shown as their re-presentation at the SE conference, Fagan's 1976 and
  Brooks's 1977 articles shown as their 1999 reprints, Zimmermann's TSE 2010 article as the FSE
  2008 paper, the three examples above -- and in all 21 the cited year names the right record.
  `title_candidates` now orders records of the same standing by whether the citation prints their
  year, read off the entry's raw text (`dblp_check.cited_years`: an IEEE DOI's year segment and an
  arXiv identifier are not years the citation prints; a page range that looks like one is the
  documented cost). The published record stays ahead of the preprint whatever the years say. A
  rule that preferred the cited year outright would also have moved 51 references from the
  published record to the CoRR one -- 39 that cite the arXiv version with its year, and 12 whose
  journal issue DBLP dates a year after the online-first year the citation prints -- and the
  published record is the one a triager needs to see. Diffed reference by reference against the
  audit before it: no status moves, and the record shown changes for exactly the 21 verified
  references and three `mismatch` near misses (Wohlin's book, Fowler's, and an encyclopedia entry
  on support vector machines) that tie on matched authors and now break the tie the same way. The
  harness stand-ins carry no raw text, so the corruption harness and the head-to-head cannot see
  the rule and come back identical by construction.

  Measured and turned down: preferring a book record for an entry that names a publisher. Of the
  27 shared-title references the year leaves to row order, ten are two records that both carry a
  cited year -- a conference paper and its journal version from one year, an ICSE tutorial and the
  book it presents, a DBLP duplicate -- where only the venue could decide, and venue comparison was
  measured and rejected under 1.19.0; eleven the row order already shows right; five are Fowler's
  *Refactoring* cited as the 2018 second edition, which DBLP does not hold, so no record carries
  the cited year and the 1999 book loses to the 2002 talk; one is a TSE article cited with its
  online-first year. The publisher rule would move the five, and the list of publisher names it
  needs fired, in the same measurement, on a co-author surnamed Pearson. Every record among the 27
  is the cited work under the cited authors; what differs is the edition or venue the URL lands
  on. Guarded by smoke tier 5c through `Verifier.check`, with three mutation entries; the mutation
  run fails for each.

- **`authors_absent` was read and never written.** The audit pass that filled it went with the
  cutover, so every worklist entry carried an empty list, the report line it fed never printed,
  and `SKILL.md` went on telling the triager the audit had found signal (A) for them. It is now
  derived where it is read, from the record the verdict rests on: `dblp_check.absent_authors`
  lists the cited people that the pairing behind `authors_match` puts on no author of the matched
  record, so a middle initial, a particle, a diacritic or a homonym suffix never lands a real
  author there, and `triage.authors_absent` reads it off `found_authors` for any unverified
  reference a backend found a record for. The worklist entry carries it, and the per-paper report
  and the verification sheet print it beside the other evidence. Over the corpus's offline residue
  it names at least one person for every one of the 46 `mismatch` references the mirror decides:
  the name forms and the real discrepancies `TODO.md` reads, the reviewer's name where a
  statistics book reached triage against the Technometrics review of it, and the four
  contributing authors DBLP does not list on Fowler's *Refactoring*. Guarded by smoke tier 3k
  through `cmd_worklist` and `cmd_report`, with a mutation entry; the mutation run fails for it.

- `triage.py` read a backend `timeout` as a matched record. The exclusion list named the other four
  non-answers; the replacement emits `timeout`, so it would have reported a backend that never
  answered as one that found something.

- **Six parser gaps the residue evidence surfaced.** Each reached triage as an honest `not_found`
  and cost a human a lookup the tool could have made. Measured over the 55-paper corpus, verified
  against the offline mirror alone: 35 references move from `not_found` to `verified`, two to
  `mismatch`, and 751 of 2857 are left for triage where 786 were. Every one of the 35 is the cited
  work, with the cited people on the matched record. The corruption harness is unchanged on every
  deciding column (250 / 250 / 250 / 0 / 0 / 0 / 0 over the complete records, 90 / 0 over the
  truncated ones), the head-to-head over the recorded cases is unchanged in all four combinations
  (1519 / 1509 / 1462 / 1543, no reference moved), and the extraction census is unchanged. Over
  the whole corpus, DBLP only, the new path confirms 2106 against the old path's 2009, where it
  confirmed 2070 before.

  - *A DOI the layout broke on one of its own periods* (`doi:10.1109/ICET.2017. 8281704`,
    `doi:10.1145/3395363. 3397366`) kept only its front half: an IEEE front half is dead, and an
    ACM one is the proceedings volume, another work. Over the corpus 60 DOIs break after a period,
    and every one resumes with digits -- an article number, a year-led segment (`CoG47356.
    2020.9231762`), an Elsevier `03.006`. Nothing else follows a DOI's period with a run of digits
    except the entry's own year, which is the one shape refused. The same pass rejoins a Springer
    DOI broken after a two-character suffix (`10.1007/s1 1219-009-9075-x`) and an Elsevier book
    DOI broken before a hyphen (`10.1016/B978 -0-12-396535-6.00001-6`). 42 corpus DOIs change, in
    19 papers. Resolved through the DOI backend alone, 42 requests and nothing else asked: 38
    resolve to the cited title, three are dead as printed -- the paper's own wrong identifier, now
    whole rather than half -- and one resolved to a title the parser was still cutting, fixed
    below.
  - *Springer's `URL https://...`* read as the title `URL`, with the real title as the author:
    eleven references in two EMSE papers. The label goes with the address.
  - *A `?` or `!` cut the title to its first clause* whenever the sentence after the mark ran on
    into a comma-joined venue ("Hey! are you committing tangled changes? In Proceedings of ...,
    2014"; "Twins or false friends? a study on ..., in: 2023 IEEE/ACM ..."), and a title that
    opens with a quoted phrase was cut at the closing quote for the same reason (`"safety
    automata" - A new specification language ..., in: Proceedings ...`). The venue test now reads
    the text up to the next mark and short of `, in:`, and a journal named without a venue word
    ("Empirical Software Engineering 30, 1 (2025)", "Psychological Bulletin 128 (4) (2002)") is
    recognised by its volume, issue and year.
  - *Elsevier's numeric style joins the venue to the title with a comma and no `in:`*
    (`..., et al., A prompt pattern catalog ..., arXiv preprint arXiv:2302.11382`;
    `Experimentation in Software Engineering, Springer, Berlin, Heidelberg, 2012`). An `et al.`
    followed by a comma now says the fields are comma-delimited and the IEEE comma reading's cut
    applies, and a comma field that is a publisher or preprint server and nothing else
    ("Springer", "SSRN", "Addison-Wesley Professional", "Tech. rep.", the names the corpus prints
    there) ends the title. 19 of the JSS paper's 44 references change title and 13 of them verify;
    two statistics books ("Practical Nonparametric Statistics", "Statistics for Experimenters")
    now reach triage as `mismatch` against the Technometrics review of each rather than as
    `not_found`, with the reviewer's name where the record's authors are shown.
  - *`VII. Note on regression and inheritance ...`* parsed to `VII`, and `..., and T. Zimmermann,
    editors. Recommendation Systems ...` to `editors`. A bare roman numeral is a numbered heading,
    not a sentence, and the role after IEEE's initials-led names belongs to the author list. The
    first version of that rule also read `Compilers:` as the role *compilers* and took the Dragon
    Book's first word; it now reads editors only, with the period or comma the role is written
    with.

  Measured and rejected: a `?` as a subtitle mark in `titles_match`, so that "Does the whole exceed
  its parts?" would match "Does the Whole Exceed its Parts? The Effect of AI Explanations ...".
  Over the 35 corpus residue titles that carry a `?`, the widening gains a record for four. Three
  are the parser cuts fixed above, which now verify on the whole title, and the fourth pairs
  Conway's "How do committees invent?" with an ACM Queue column of that head by another author,
  which would have reached triage as `mismatch` against an unrelated work. The matcher stays as
  it is.

  Guarded in smoke tier 5 through `parse_reference`, with ten mutation entries; the mutation run
  fails for each.

### Changed

- `.env.local` in the repo root, gitignored, holds the API keys the online backends want. mise
  reads it through `[env]` and `run.sh` reads it directly, so a dev clone and an installed plugin
  see the same values, and a variable already set in the environment still wins. Both tolerate the
  file being absent.

- `characterize.py record` takes `--s2-api-key`, or `$S2_API_KEY`, and warns when it has neither.
  It never passed one through, so the recording ran unauthenticated whatever the environment held,
  and Semantic Scholar rate-limited exactly the residue the recording exists to capture. A
  41-paper recording had not finished after three and a half hours.

- `characterize.py compare` now covers `check` as well as `parse`. Field-by-field equality is the
  wrong question for the verdicts -- a replacement consults different backends, so `source`,
  `failed_dbs` and `db_results` differ by construction -- so it reports the recorded status against
  the implementation's as a matrix, and lists every reference that crosses the verified line in
  either direction. `--out` writes the whole divergence list as JSON, `--limit` compares a sample,
  and `--no-check` compares the parse alone and makes no network request.

## [1.21.0] - 2026-09-09

### Fixed

- A two-column bibliography no longer loses half its references. `_gutter` required four wholly
  blank character columns, and an ACM two-column reference page sets its columns three apart in
  `pdftotext -layout` output -- tighter than the body text above it. No gutter was found on exactly
  the pages that matter, the page was read as one column, the right column's text was appended to
  the left column's lines, and roughly half of each bibliography silently disappeared: 8 references
  of 16, 21 of 52, 24 of 62, 10 of 26. Four of the first seventeen papers tested extracted nothing
  at all.

  Measured over 37 arXiv papers spanning ICSE, FSE, ASE, ESEM in both templates, TSE and TOSEM: a
  four-column minimum recovers 1752 of 1864 references (94.0%) and leaves four papers below 80%
  recall; three recovers 1848 (99.1%) with none below 80%. Two gains nothing over three, so the
  looser setting buys no recall and only risks reading a coincidental gap as a column break.

### Added

- `characterize.py`, which records what the current implementation returns for `parse_reference`
  and `Validator.check` on real references and holds a replacement to that recording. hallucite
  reaches into `hallucinator` at those two points only; replacing the dependency needs an oracle,
  and observing the current behaviour from the outside is both the specification and the
  differential test.

## [1.20.0] - 2026-09-09

### Added

- `--s2-api-key` (or `$S2_API_KEY`) and `--rate-limit-retries`, and a note when no key is set.
  Semantic Scholar answered on one of twelve audit runs; on the other eleven it returned
  `rate_limited` in about 2.4 s for three to five references each. Those references carry a
  degraded verification -- not a clean negative -- and the boundary between "verified" and "needs
  triage" moved by one reference between otherwise identical runs. That was the entire source of
  churn observed across the session; a free key removes it. `ValidatorConfig` had `s2_api_key` and
  `max_rate_limit_retries` all along and the audit set neither.

## [1.19.0] - 2026-09-09

### Added

- The mirror also stores `volume`, `number` and `pages` (4,478,005 / 2,666,380 / 7,144,917 records
  on the rebuilt file), so a citation's "49(3):1152-1170" can be checked against the record it
  claims to be.

- A reference that reaches triage now carries DBLP's own metadata for its title -- key, year,
  venue, volume/number/pages, DOI and record type -- in the worklist and the per-paper report.
  Evidence for the person reviewing it, beside the citation.

### Changed

- The three field checks (year, venue, DOI) were measured against the corpus and **not** built as
  automatic demotions; the fields are surfaced as evidence instead. Over the 579 verified
  references a repaired mirror can be compared against:

  | Candidate check | Disagreement rate | Why it is not a check |
  |---|---|---|
  | Venue | 157/561 (28%) | DBLP stores abbreviations (`CoRR`, `ESEC/SIGSOFT FSE`, `ICCSA (5)`) that a citation has no reason to contain |
  | Year | 60/575 (10%) | hallucinator parses no year, so this mostly measures which four-digit number a regex found in the raw citation; off-by-one is usually preprint vs issue year |
  | DOI | 12/179 (6.7%) after excluding truncated citations, arXiv DOIs and IEEE duplicates | a work legitimately carries several DOIs (preprint and published, ACM Queue and CACM), and DBLP's `ee` is sometimes a publisher URL or points at a review |

  For comparison the author-absence check that does demote flags 0.22%. Shipping any of these at
  6.7% or worse would bury the signal that works.

- `insert_or_get_publication` takes the full record in one signature; the three-argument wrapper is
  gone. It existed only to keep the upstream diff off the crate's twenty test call sites, and its
  `ON CONFLICT` cleared `year`/`venue`/`ee`/`kind` back to NULL -- a metadata-stripping footgun for
  any later caller. The call sites are updated instead.

### Fixed

- `record_context` finds a record whose title was broken across a line. `_phrase_queries` asks both
  hyphen readings of the whole title, which fails when one title needs both at once ("Refactoring
  ... de-velopers keep up-to-date" matches neither `uptodate` nor `de velopers`); it now falls back
  to an AND over the words carrying no hyphen, and compares titles with punctuation removed. The
  reference this was built for is exactly the kind that hits it.

## [1.18.0] - 2026-09-09

### Added

- The offline DBLP mirror now stores the record metadata the dump carries: `year`, `venue`, `ee`
  (the electronic edition, usually the DOI) and `kind` (the DBLP element -- article,
  inproceedings, book). Added to `dblp-entity-fix.patch`. The ingest parsed `<ee>` and discarded
  it, and never looked at `<year>` or the venue at all, so the mirror could answer only "does a
  work with this title by these authors exist". Two of the four fabrication signals were therefore
  uncheckable in `--offline` runs: a wrong or impossible venue and year (V), and a DOI belonging
  to another work (D). On the rebuilt mirror 8,720,203 of 8,720,206 records carry a year, 8,542,357
  a venue and 8,541,662 an electronic edition.

  `kind` and `year` also separate same-title records that authors alone could not. The six
  "Experimentation in Software Engineering" entries now resolve as Wohlin's books (2000, 2012,
  2024), Basili's 1986 TSE article, Pfleeger's 1997 Adv. Comput. note and a 2008 FECS paper --
  the ambiguity `dblp_check.py`'s all-candidates pass exists to work around.

- `second_opinion()` carries that metadata on a confirmation (`year`, `venue`, `ee`, `kind`),
  reading whichever columns the mirror actually has. A database built before the ingest stored
  them reports them as absent and everything else keeps working.

### Fixed

- `dblp_check`'s author folding handles letters carrying a stroke or bar. It shared the NFKD gap
  fixed in the audit: `ł`, `ø`, `đ` and `ß` carry no combining mark to strip, so `Przybyłek` and
  `Przybylek` compared as different people. Now that the mirror actually holds accented names,
  this decides whether a real reference is confirmed or sent to triage.

## [1.17.0] - 2026-09-09

### Fixed

- A reference naming authors the matched work does not have is caught again when DBLP is what
  cleared it. `COMPLETE_AUTHOR_DBS` excluded DBLP because the local mirror dropped its accented
  authors; repairing the mirror made that exclusion wrong, and the TSE reference carrying two
  invented authors verified again -- DBLP now holds all five real authors, hallucinator sees three
  of them in the citation and reports a match, and the absence check skipped it. Which backends
  count is now decided per run from the mirror in hand (`_complete_author_dbs`): DBLP counts when
  its accented authors survived the ingest, and does not when they did not. Measured over the 459
  corpus references a repaired mirror can be compared against, including DBLP flags one (0.22%),
  a genuine discrepancy.

- Letters carrying a stroke or bar now fold to their ASCII form. NFKD leaves `ł`, `ø`, `đ` and `ß`
  alone -- they carry no combining mark to strip -- so `Przybyłek` and `Przybylek` compared as
  different people and the citation read as inventing an author. Two of the three flags in the
  corpus measurement were this, not a citation error. DBLP's homonym suffix (`Márcio Ribeiro
  0001`) needs no special case: digits already fall to the letters-only filter.

- `mise run build-dblp` removes the `-wal`/`-shm` files on both sides of the swap. Moving only the
  database left the scratch pair orphaned and the destination's stale pair in place.

## [1.16.0] - 2026-09-09

### Added

- `mise run fetch-dblp-dump` downloads `dblp.xml.gz` with a real browser, for the `--from-file`
  build. dblp.org and both its mirrors front the dump with an Anubis proof-of-work challenge, so
  every plain HTTP client gets the challenge page instead of the file. A browser answers it with
  its own JS engine, the way it does for a person clicking the link; nothing forges or replays a
  token, and Playwright's `--enable-automation` marker is left in place. It has to run headed --
  Anubis refuses the headless browser outright ("Access Denied") while the headed one completes
  the proof-of-work normally -- so it needs a display, and the script says so when refused. The
  dump lands beside `$HALLUCITE_DBLP`, so relocating the database relocates the dump.

- A dependency table in the README. "A web browser" was doing too much work as a dependency
  specification: Playwright with its own Chromium is the concrete, installable form of it, and
  the Rust toolchain is likewise needed only for `install-cli-patched`.

- `mise run install-cli-patched` builds `hallucinator-cli` from the pinned upstream source with
  `dblp-entity-fix.patch` applied, and fails if the built binary does not carry the fix. The
  patched binary was previously something you had to produce by hand, which is no basis for a
  dependency the audit's correctness rests on.

### Changed

- `mise run install-cli` refuses to overwrite a binary carrying the patch. It fetches the stock
  upstream build, which drops every author whose name has a diacritic, and the loss is invisible
  downstream -- publication counts, titles and record keys all look right -- so a routine
  reinstall would silently reintroduce it. `FORCE=1` overrides.

## [1.15.0] - 2026-09-09

### Added

- `update-dblp --from-file <XML_GZ>` builds the mirror from a dump already on disk, added to
  `dblp-entity-fix.patch`. dblp.org and both its mirrors front `dblp.xml.gz` with an Anubis
  proof-of-work bot check, so every plain HTTP client -- `curl`, and the downloader inside
  `update-dblp` -- receives the challenge page instead of the dump and ingests it as zero
  publications. `hallucinator-dblp` could already build from a local file; the CLI exposed no way
  to ask for it. Verified end to end on a dump whose author names are entity-encoded: all five
  authors of `journals/tse/SoaresRGAS23` and all six of `books/sp/WohlinRHOR00` land with their
  accents intact.

### Changed

- `mise run build-dblp` forwards `$DBLP_XML_GZ` to `--from-file` when it is set, so a dump
  downloaded in a browser can be ingested without touching the download path. README documents
  the route.

## [1.14.0] - 2026-09-08

### Added

- A patch for the upstream ingest bug, `dblp-entity-fix.patch`, against hallucinator 0.2.3. DBLP
  writes Latin-1 letters as the named entities its DTD declares (`&aacute;`, `&ouml;`), and
  `hallucinator-dblp`'s XML parser calls quick-xml's `unescape()`, which without the crate's
  `escape-html` feature knows only the five predefined XML entities. On failure the parser dropped
  the whole text chunk, so the author name came out empty and the author was never recorded. The
  patch enables `escape-html` and falls back to the raw text instead of discarding the field.
  Verified against the real records: `journals/tse/SoaresRGAS23` and `books/sp/WohlinRHOR00`
  recover Márcio Ribeiro, André Santos, Martin Höst, Björn Regnell and Anders Wesslén, and the
  crate's 50 tests still pass. Apply it, rebuild `hallucinator-cli`, then rebuild the mirror.

- The audit warns when the offline DBLP database holds almost no publications. `update-dblp`
  writes a database and exits 0 even when the download returned a bot-check HTML page instead of
  the dump, which is exactly what dblp.org serves at the moment. Nothing downstream separates that
  empty mirror from a paper whose references DBLP genuinely does not hold.

### Changed

- `mise run build-dblp` builds to a scratch file and swaps it in only after checking that the
  result holds over a million publications and that accented author names survived. Writing
  straight to the destination replaced a working 2.6 GB mirror with an empty one, silently, on a
  download that returned a bot-check page.

### Fixed

- An empty offline mirror is no longer reported as one that dropped its accented authors. Zero
  authors trivially means zero accented authors, so the entity check now requires a
  mirror-sized author table before making that claim.

## [1.13.1] - 2026-09-08

### Added

- The audit warns when the offline DBLP database holds no author name with a non-ASCII character.
  DBLP is carefully curated and full of accented names, so a mirror containing none of them was
  built by an ingest that mangles the dump's character entities. On a 4.0M-author build every such
  author was absent outright -- Márcio Ribeiro, Martin Höst, Björn Regnell, Petr Tuma and Jácome
  Cunha appeared in no record, folded or otherwise -- which strips them from the author list of
  every paper they wrote. DBLP then reports an author mismatch for references that are cited
  correctly, and its all-candidates second opinion fails to confirm real work. Nothing else made
  this visible: publication counts, titles and keys all look right.

### Fixed

- Corrected why `COMPLETE_AUTHOR_DBS` omits DBLP. 1.13.0 attributed the missing co-authors to
  truncated DBLP rows. They are not DBLP's: the local mirror's ingest drops them, and the Wohlin
  book keeps 3 of its 6 authors because Höst, Regnell and Wesslén are absent from the whole
  database. The exclusion stands while a build behaves this way; once one preserves those names,
  DBLP should be measured against the corpus again and added.

## [1.13.0] - 2026-09-08

### Added

- The audit flags a reference that names an author the matched publication does not have. A
  backend confirms on the title, so a real title carrying an invented author list was cleared as
  `verified` and never reached triage: a TSE proof cited "Refactoring Test Smells With JUnit 5"
  with the right venue, volume and pages but two authors who are not on the paper, CrossRef
  matched the title, and no human ever saw it. After verification the audit compares the cited
  authors with the ones the clearing backend holds and demotes the reference to `author_mismatch`,
  carrying the absent names into the worklist (`authors_absent`) and the per-paper report.

  Precision is the design, because every demotion asks a human to judge named authors. Only the
  clearing backend's own authors count, and only from a backend that returns complete author lists;
  the two lists must be the same length, so an abbreviated citation is never read as a fabricated
  one; venue fragments, the sentence the parser bleeds into the last author, and single-token
  remains of a split name are skipped; and diacritics, hyphenation, middle initials, compound
  surnames and swapped given/surname order all compare equal. Measured over 1016 database-verified
  references from a 95-paper corpus it flags one.

  Demoting on a backend's own `author_mismatch` verdict was measured on the same corpus and is
  deliberately not used: it flags 22, almost all of them DBLP's truncated author rows
  (`Experimentation in Software Engineering` stores 3 of 6 authors) or a same-title record for a
  different work, against references that are cited correctly.

## [1.12.1] - 2026-09-08

### Fixed

- A section heading letter-spaced by `pdftotext` now opens the bibliography. IEEE-style journal
  proofs set headings in small caps with a full-size initial, and `pdftotext` renders the size
  change as a space, so `REFERENCES` arrives as `R EFERENCES`. `_references_section` matched the
  heading text exactly, found nothing, and the audit reported 0 references for a TSE proof whose
  bibliography holds 32 entries -- exit 0, one warning line, and a paper that contributed nothing
  to triage. Headings are now compared on their space-stripped spelling as well, which covers the
  fully spaced `R E F E R E N C E S` too, and the Appendix/Acknowledgment heading that ends the
  section is matched the same way so author biographies cannot land inside the bibliography. The
  comparison still runs against a whole short heading line, so a sentence opening with
  "References" cannot start the section.

### Changed

- The zero-reference warning names the right next step. It used to end "Verify these by hand or
  fix the extraction", which reads as license to do the one thing the stop conditions forbid; it
  now says the run is an extraction failure to report and fix, and that reading the bibliography
  by eye yields no verdict. `SKILL.md` gains the matching stop condition, because the audit exits
  0 on this path and nothing else marks it as a failed run.

## [1.12.0] - 2026-07-20

### Added

- A second-opinion pass over the offline DBLP database (`dblp_check.py`). hallucinator's
  offline backend compares a reference with a single FTS candidate, so a cited title that
  several publications share is judged against whichever ranks first -- "Experimentation in
  Software Engineering" hit Basili's 1986 TSE article and reported the Wohlin book `not_found`
  -- and the database's own author rows can be truncated (the Wohlin book stores 3 of its 6
  authors; `conf/sigsoft/MeyerFMZ14` lacks Meyer). After hallucinator's pass, the audit re-asks
  the same SQLite file over all same-title candidates: exact normalized-title equality plus an
  initials-aware match of every comparable author confirms the reference as `verified` with
  source `DBLP (hallucite)`. The pass only ever clears references, never flags one, and it is
  hallucite's own code written against the database schema -- hallucinator (AGPL, compiled
  extension) is neither vendored nor patched. On the line-numbered author-year test paper it
  clears 6 of the 13 offline-unverified references, every one to the correct DBLP record, while
  wrong, padded, and invented citations stay unverified.

## [1.11.0] - 2026-07-20

### Fixed

- A stale verdict is quarantined instead of reattached. A verdict is keyed by
  `paper_id:number`, but author-year numbers are extraction-order, so a re-audit can renumber the
  bibliography and leave a verdict pointing at a different reference. `report` used to detect
  exactly this (via the stored reference fingerprint), warn on stderr, and then print the old
  category anyway -- flagging an innocent reference as likely-hallucinated, with the desk-reject
  banner, in every written artifact, while the actually-suspect reference reverted silently to
  pending. `report` now shows the verdict as stale and the reference as pending, `worklist
  --pending` resurfaces it, and `status` counts it as pending.
- A hedged verdict can no longer reach **Desk-reject candidates**. `is_fabrication` now requires
  the `likely-hallucinated` category alongside `title_match=no`, and `record` rejects `unclear`
  with `title_match=no` as contradictory (that signal asserts the likely-hallucinated finding).
  Previously an `unclear` verdict carrying `title_match=no` was escalated into the report's most
  severe section, which does not display the category.
- A running head that appears only once inside the References section is now dropped.
  Repetition is counted over the whole document instead of the section, so a two-page
  bibliography (which contains its head exactly once) no longer glues the citing paper's own
  title and page number into a reference -- the corruption that sent a real paper to triage as
  `not_found` with zero candidate leads.
- A wrapped page number alone on a line ("...19(3):619–" / "654") is no longer blanked as a
  `lineno` margin number: blanking is gated on the margin column, so short numbers at a
  continuation indent survive as citation content.
- `record` rejects a `paper_id:number` that matches no audited reference instead of storing a
  verdict that could never appear in any report.

### Added

- Verification retries failed references with their line-break hyphens removed. The extractor
  keeps the hyphen when joining a wrapped line ("Experimen-tation"), which is right for a real
  compound and wrong for a soft-hyphenated word -- and FTS backends miss the wrong form, sending
  real, DBLP-indexed works into triage as `not_found`. Each segmented reference now carries the
  dehyphenated variant, and the audit re-verifies with it when the original fails, keeping the
  result only when it verifies.
- The audit warns about suspected merged entries: an author-year reference carrying two
  "(year)" author-block labels is the shape left behind when a flat layout glues an entry whose
  year wrapped onto the next line into its predecessor -- the second entry is then never verified
  on its own. Flagged per paper and stored in the extraction record.
- A closing warning aggregates papers that yielded 0 references (unsupported bibliography
  layout, or no References section found), so an unchecked paper cannot scroll out of sight in a
  long batch.

### Changed

- The triage rules bound the partial-match rescue: an independent identifier rescues one or two
  slipped title words, never a wholly different title -- a real record stapled to an invented
  title is `title_match=no`, not a citation error.
- The verify sheets label the triager's text "Triage finding" (it is written by the LLM triage
  step, not by the database check the sheet also shows).

## [1.10.2] - 2026-07-20

### Changed

- The repeated-entry guidance recommends what the evidence carries rather than banning an action.
  1.10.1 ended with "do not advise merging the conflicting one", which restated the bullet above it
  and forbade a conclusion that further evidence can legitimately reach: a conflict resolved by
  checking the in-text usage of each key may well be one work, and consolidating it is then the
  right advice. The rule now states the asymmetry instead -- wrongly merging destroys distinct
  citations while leaving entries separate stays fixable, so an unresolved conflict defaults to no
  action.

## [1.10.1] - 2026-07-20

### Changed

- Repeated bibliography entries are classified instead of hedged. 1.10.0 reported every group of
  same-author, same-title entries as "indistinguishable" and referred the whole question to the
  author, which threw away the cases where the evidence is conclusive. Entries matching on *every*
  field -- authors, title, venue, volume, pages -- are now reported as **duplicates** and stated as
  fact, since two distinct articles cannot share a venue, volume, and article number. Only entries
  whose venue, volume, or pages disagree are reported as **conflicting**, where an extended version
  or a preprint sharing a title is a real possibility and the in-text usage of each key decides. A
  group can produce both findings: of two groups in the paper that prompted this, one is a plain
  duplicate, and the other holds a duplicate pair plus a third entry that conflicts with it.

## [1.10.0] - 2026-07-20

### Added

- Unverified references carry `candidates`: the closest real records from CrossRef's fuzzy
  bibliographic search, with title similarity, DOI, venue, and year. The validator's exact-title
  lookups miss a citation that abbreviates or expands a term, and a quoted web search for such a
  title returns only the authors' *other* papers -- which reads exactly like the fabrication
  signature, and nearly produced a false accusation. A reference cited as "Llms as assistants in
  software architecture design" now resolves at 0.855 similarity to "Large Language Models as
  Assistants in Software Architecture Design" (IEEE Software, doi 10.1109/ms.2026.3663353) before
  any searching. Candidates are leads to confirm or reject, never verdicts; an invented title
  matches nothing, so an empty list carries information too. `--no-candidates` skips the lookup and
  `--offline` implies it.
- Worklist entries and reports carry `matched`: the record each backend matched and the authors it
  holds. A `mismatch` is only judgeable against the thing that mismatched -- and the matched record
  is sometimes not the same work at all (for one reference, CrossRef matched a thesis sharing its
  paper's title while DBLP matched the right paper under an incomplete author list).
- Reports list **indistinguishable entries**: different citation keys whose entries carry the same
  authors and title, so the bibliography asserts distinct works while giving no way to tell them
  apart. Database verification cannot surface this, since every such entry verifies on its own.
  The report states the problem without diagnosing it: these are as likely to be one duplicated
  work as several works with wrong metadata, and only the in-text usage of each key settles which.
- `--retry-degraded N` (default 1) re-checks references a backend failed to answer for, keeping the
  retried result only when it improves.

### Changed

- References are named by the handle a reader can find. A numbered bibliography keeps its printed
  `[12]`; an unnumbered author-year one is named by the citation key the paper itself uses
  (`de Dieu et al. (2025c)`). Reports previously printed the extractor's sequential index as though
  it were a reference number, sending a reviewer hunting a `[22]` that appears nowhere in the
  paper. Where that index is still needed -- it is what `triage record` takes -- it is shown as
  `[#n]` and the report says it is hallucite's own.

### Fixed

- A `not_found` produced while a backend errored or rate-limited is flagged `degraded` and is no
  longer presented as a clean negative. Verification stops at the first backend that matches, so
  later backends are only ever asked about the residue -- the same references that reach triage --
  and that is where rate limiting lands: on the run that prompted this, every one of the 9 triaged
  references had a backend that never answered, one of them three, with nothing to indicate it. The
  audit now prints a per-backend failure tally, `record` warns when a `likely-hallucinated` verdict
  rests on a degraded check, and the skill instructs triage to treat such an absence as no evidence
  at all. `degraded` is a separate flag rather than a new status value, so `status != "verified"`
  remains the single definition of "needs triage".
- The triage rules no longer point at a false accusation for an abbreviated title. An abbreviation
  and its expansion of the same term ("LLMs" / "Large Language Models") are now stated to be the
  same title, where the previous wording made them a wrong *content word* -- which demands an
  identifier to rescue the citation and otherwise lands on `likely-hallucinated`. The rules also
  name the escalation trap explicitly: a narrow search returning the same authors under different
  titles is the trigger to broaden, not a conclusion.

## [1.9.0] - 2026-07-20

### Added

- `run.sh upgrade` upgrades `hallucinator` in the managed venv, and `check-env` warns when PyPI has
  a newer release. `resolve_python` reuses that venv as soon as it can import hallucinator, so the
  unpinned `pip install hallucinator` ran only when the venv was first created: an install stayed on
  whatever version was current the day it was built, for as long as it lived, with nothing to
  indicate it. `upgrade` refuses when `$HALLUCITE_PYTHON` is set, since run.sh does not modify an
  interpreter it did not provision, and `$HALLUCITE_NO_VERSION_CHECK` skips the PyPI lookup for
  offline and CI runs. `mise run upgrade` covers the repo venv and the managed venv together.

### Fixed

- Reference extraction handles a Springer author-year bibliography ("Bacchelli A, D'Ambros M (2009)
  ...") printed under LaTeX `lineno` margin numbers. Three faults compounded. `lineno` detection
  required two or more digits followed by text, so single-digit numbers and numbers rendered alone
  on a line went uncounted, and every margin digit survived into the text as data. The numbered
  lines then read as a plain-numeric bibliography, so each physical line became its own reference,
  splitting entries mid-title and truncating them. The author-year entry pattern matched only
  "Surname, I.", never the Springer "Surname AB," convention, leaving the correct style unreachable.
  Margin numbers are now overwritten with spaces rather than deleted, preserving the column
  positions that carry the bibliography's hanging indent -- the only delimiter an author-year entry
  has, given that it carries no label and its `(year)` may wrap onto the following line. Running
  heads and text outside the bibliography's column block are dropped, so a page header no longer
  becomes a reference and an editorial system's "Click here to download" slip no longer lands inside
  the last one. On the paper that surfaced this, extraction goes from 32 mangled references (17
  unparsed, entries split mid-sentence) to 93 cleanly segmented references, none unparsed, and
  database verification from 7 to 85. Smoke tier 4c drives a generated fixture PDF that reproduces
  the layout with invented references.

## [1.8.4] - 2026-06-24

### Fixed

- The `SKILL.md` `run.sh` resolver scans the Claude Code plugin cache
  (`${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/cache`) for the highest installed version before
  falling back to the Codex plugin cache. Branch 1 (the `CLAUDE_PLUGIN_ROOT` path) is skipped when
  that variable is unset in the tool shell, as it is for an ordinary Bash call, which left the Codex
  cache as the only version-scanning branch; a `/plugin marketplace update` on the Claude side then
  had no effect, and a stale Codex-cached copy (e.g. an older `se-uhd/hallucite`) ran instead of the
  current install. The new branch resolves to the newest Claude-cached version regardless of
  `CLAUDE_PLUGIN_ROOT`, and is ordered ahead of the Codex fallback so a current Claude install
  always wins.

## [1.8.3] - 2026-06-24

### Fixed

- Reference extraction handles a bracket-numeric bibliography ("[1]" ... "[59]") printed under
  LaTeX `lineno` margin numbers that `pdftotext -layout` renders inconsistently and that restart on
  each page. The bibliography was read as plain numeric, so segmentation anchored on the margin
  numbers rather than the "[N]" labels: it dropped the first entry and, at every per-page
  line-number reset, merged the remaining references into a single segment. A new bracket-numeric
  style anchors on the bracketed label and strips the gutter margin number from both entry and
  continuation lines, so margin numbers no longer masquerade as entries. On the paper that surfaced
  this, extraction goes from 45 mangled references (6 unparsed; references 22-59 merged into one) to
  59 cleanly segmented references, none unparsed. Smoke tier 4b reproduces the layout with invented
  references and guards the fix.

## [1.8.2] - 2026-06-11

### Changed

- Synced the vendored PyMarkdown linter to pymarkdown-skill 0.2.2. The lint wrapper now
  invokes PyMarkdown under the `explicit` return-code scheme (a scan system error or a
  file PyMarkdown refuses to scan now exits 2 instead of being reported as clean), the
  pre-pass recognizes tilde and indented fences and follows the config's front-matter
  settings, and `check_baseline.py`/`refresh_vendor.py`/the sync tooling carry the
  accompanying robustness fixes. No change to hallucite's own behavior.

## [1.8.1] - 2026-06-10

### Fixed

- `mise run audit` forwards everything after the target to the audit script, so the documented
  flags (`--offline`, `--mailto`, `--no-verify`, ...) work; the task previously hard-coded
  `--dblp`/`--out` and errored on any flag. The output directory is now set with `--out` instead
  of a second positional argument (the script's own defaults already cover `--dblp` and `--out`).
- The Codex plugin-cache resolver in `SKILL.md` compares cached versions with `sort -V`, so
  `1.10.0` beats `1.9.0`; plain `sort` picked the lexicographically highest and would have run a
  stale cached plugin once the version reached two digits.
- Docs and plugin manifests no longer claim OpenAlex verification: hallucinator's OpenAlex backend
  is key-gated and the audit never configures a key, so it never ran. The database lists now name
  Semantic Scholar and the other backends that actually run.
- `--offline` is documented as "no network" rather than "DBLP-only", and now enforces it:
  hallucinator's built-in Standards matcher (local, pattern-based) stays live and can set the
  verification status for standards references, and a missing offline DBLP file disables the DBLP
  backend for the run (hallucinator would otherwise silently fall back to querying dblp.org). A
  second drift tripwire warns when a backend outside `KNOWN_LOCAL_DBS` appears in `--offline`
  results -- the inverse direction of the `DEFAULT_ONLINE_DBS` warning, which only catches
  configured names that never appear.
- `triage.py` skips a stray JSON file whose `paper_id`/`pdf_path`/`num_references` are missing or
  malformed (e.g. null) instead of crashing `status`/`report`, matching `load_papers`' documented
  skip-don't-crash contract; a near-miss record is skipped with a warning, and a smoke check
  feeds the audit's real output through `load_papers` so an audit schema drift cannot silently
  empty Stage 3.
- `run.sh check-env` warns (non-fatally) when `pdftotext` (poppler) is missing, and README's setup
  section names the prerequisite; previously only `SKILL.md` and the extractor's error mentioned
  it. `run.sh` also appends the common install dirs (Homebrew, `~/.local/bin`, ...) to `PATH`
  before running the scripts, so the extractor resolves `pdftotext` the same way the preflight
  probe does even in a plugin shell with a minimal `PATH`.

### Changed

- README and PLAN no longer list Markdown lint as part of the `run_smoke.py` suite; it runs as a
  separate CI step and locally via `mise run lint-md`. The smoke suite's docstring now also lists
  tiers 3b (triage concurrency) and 3c (title-first gate), which `main()` already ran.
- Documented the existing `--disable-dbs` audit flag and the `$HALLUCITE_VENV` override in README
  and `SKILL.md`; removed the stale "GitHub once pushed" hedge from README's install section.
- Reworded the stage summary in README, `SKILL.md`, and `CLAUDE.md`: stages 1+2 use no LLM, and
  verification queries online databases unless `--offline`; the old "local and deterministic"
  claim only held for offline runs. `CLAUDE.md` also states which smoke tier guards the
  stop-conditions rule (tier 1 for the SKILL.md text, tier 1b for the fail-loud `run.sh` contract)
  and how status strings vs backend names are validated.

## [1.8.0] - 2026-06-06

### Changed

- Renamed the plugin marketplace from `se-uhd` to `hallucite` in both the Claude Code
  (`.claude-plugin/marketplace.json`) and Codex (`.agents/plugins/marketplace.json`) manifests, so
  it installs as `hallucite@hallucite` and lists under `--marketplace hallucite`. The Codex plugin
  cache resolver now prefers the `hallucite` marketplace's cached copy. The GitHub repo location
  (`se-uhd/hallucite`), owning org, and plugin author/developer are unchanged.

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
- Smoke coverage for dual manifests, Claude-vs-Codex marketplace shapes, Codex symlink shims,
  `AGENTS.md`, the expanded runner resolver, and an optional isolated Codex CLI marketplace-list
  check when `codex` is installed.

### Changed

- The bundled skill now resolves `run.sh` across Claude Code installs, repo-local Codex discovery,
  direct repo clones, and Codex plugin caches, while keeping one shared skill and script tree.
- README, PLAN, CLAUDE.md, `run.sh`, and `mise.toml` now describe support for both Claude Code and
  Codex CLI.

## [1.6.0] - 2026-05-30

### Added

- `run.sh`, a single bootstrap entry point for the pipeline (`doctor` / `audit` / `triage` /
  `lint` / `python`). It resolves -- or, on first use, provisions at
  `${XDG_CACHE_HOME:-~/.cache}/hallucite/venv` -- a Python 3.12 that can `import hallucinator`,
  preferring `uv` and falling back to a stdlib `venv` over a discovered 3.12 (PATH, common install
  dirs, or `mise where`). It never relies on a bare `python`/`uv`/`mise` being on the plugin
  shell's PATH, which is what made the pipeline silently un-runnable when installed as a plugin.
  Set `$HALLUCITE_PYTHON` to reuse an existing hallucinator environment and skip provisioning.
- `run.sh doctor` preflight: prints `HALLUCITE_OK: <python> (hallucinator <version>)` on success,
  or a `HALLUCITE_BOOTSTRAP_FAILED:` sentinel line and a non-zero exit on any setup failure.
- Smoke tier 1b exercises the `run.sh` contract (syntax check, unknown-command rejection, fail-loud
  on a Python without hallucinator), and tier 1 now asserts SKILL.md drives the pipeline through
  `run.sh` and carries the stop conditions.

### Changed

- SKILL.md adds a **Stop conditions -- never fabricate a verdict** section and routes every stage
  through `run.sh`: no script output means no verdict, and any non-zero exit or
  `HALLUCITE_BOOTSTRAP_FAILED:` line is a blocking error to surface, never to work around by reading
  the bibliography by hand.
- README, CLAUDE.md, and PLAN.md document `run.sh` as the entry point (and the mise-free plugin
  path), the stop conditions, and smoke tier 1b, so the downstream docs match the pipeline.

## [1.5.1] - 2026-05-29

### Fixed

- `triage.py record --signals` accepts `venue_match=partial`, which the documented signal
  vocabulary lists but the validator's enum had omitted (a worker following the docs would have hit
  a spurious rejection).

### Changed

- `PLAN.md` is brought in sync with the title-first triage design: the triage step, the verdict
  contract (structured fabrication signals plus the `fcntl` lock on `triage_verdicts.json`), the
  reports (the Desk-reject candidates section), per-paper `worklist --paper` slicing, and the
  smoke-test inventory.

## [1.5.0] - 2026-05-29

### Added

- Title-first triage with structured fabrication signals. `triage.py record` takes a `--signals`
  JSON object (`title_match`, `matched_title`, `authors_match`, `venue_match`, `doi_status`) and
  enforces the rule that separates a citation error from a fabrication: a `partial-match` must name
  the real publication it matched (`title_match=yes` plus `matched_title`, or `na` for a
  non-publication resource), and a `likely-hallucinated` must assert the cited title was not found
  (`title_match=no`). A title that matches no real publication can no longer be filed as a citation
  error because a different paper by the same authors happens to exist.
- `triage.py report` shows each flagged reference's matched title and signal summary, warns on a
  `partial-match` whose signals say the title was not found, and adds a **Desk-reject candidates**
  section listing references whose cited title matches no real publication, compounded by a
  fabricated author constellation, venue, or DOI.
- `triage.py worklist --paper <id>` writes one paper's slice (exact id match, errors on an unknown
  id), so a parallel Stage 3 worker reads only its own references instead of self-filtering the
  shared worklist -- closing a fan-out hazard where a prefix id (`paper6` vs `paper66`) could pull
  the wrong paper.

### Fixed

- `triage.py record` serializes its read-modify-write of `triage_verdicts.json` under an `fcntl`
  lock, so concurrent workers no longer drop each other's verdicts (a lost update the atomic write
  alone did not prevent).

## [1.4.1] - 2026-05-29

### Fixed

- Extraction no longer drops references in several edge cases (validated against the prior corpus
  with no count regressions; one real reference that had been silently dropped was recovered):
  a numeric bibliography that starts above `[1]` is segmented from its true first entry instead of
  being dropped (anchored on the first real ascending run, skipping stray page/DOI numbers); the
  References section is taken from the first heading, so a repeated "References" running page header
  no longer truncates it to the last page; a trailing Appendix/Acknowledgments heading still ends
  the section but a reference whose text merely begins with one of those words does not; and the
  author-year detector finds the year within the first 300 (was 100) characters, so a reference
  with a long author list is no longer missed.
- `triage.py report` deletes previously generated files first (no orphan `verify-<pid>.md`),
  surfaces retracted-but-"verified" references, shows a "Not verified" line for `--no-verify`
  references, stores a reference fingerprint and warns on a stale verdict after a re-audit, and
  identifies records by content so a stray `.json` no longer crashes the run.
- `find_pdfs` matches `.pdf` case-insensitively and errors on an empty directory;
  `dblp_build_info` tolerates a non-string `last_updated`; `install-cli` refuses non-Darwin hosts;
  the `requirements.txt` comment was corrected.

### Changed

- CI smoke workflow uses Node 24 actions (`actions/checkout@v5`, `actions/setup-python@v6`).

## [1.4.0] - 2026-05-29

### Fixed

- `--offline` now actually disables the DOI backend. The disable list named it "DOI Resolver",
  but hallucinator emits the backend as "DOI", so the name matched nothing and DOI lookups kept
  hitting the network in offline mode, sometimes returning a non-reproducible `verified` that
  hides a reference from triage. The list now uses the real backend names, drops two that
  hallucinator never emits (SSRN, NeurIPS), and the audit warns at run time if a configured name
  never appears in any result.
- The audit exits non-zero and prints a summary when a paper fails to process, instead of printing
  "Done" and returning 0 while the failed paper is silently absent from Stage 3.
- The audit warns when a paper extracts zero references or no References section is found, which
  previously looked identical to a clean paper.
- `triage.py record` warns when the given `paper_id:number` matches no audited reference, instead
  of storing an orphan verdict that never reaches a report.
- The mise `audit` task quotes the DBLP path so a path containing spaces no longer word-splits.

### Added

- Smoke-test suite (`skills/hallucite/scripts/tests/run_smoke.py`) and a GitHub Actions workflow
  (`.github/workflows/smoke.yml`): version/packaging consistency, logic-contract unit tests
  (including a guard that a `mismatch` reference still reaches triage), Markdown lint, and an
  offline end-to-end audit against a generated fixture DBLP database and a synthetic fixture PDF.

## [1.3.0] - 2026-05-29

### Fixed

- Triage no longer silently drops references whose database verdict is `mismatch` (a title match
  with mismatching authors). hallucinator reports these with the top-level status `mismatch`, but
  the worklist, the report, and the audit's `unverified` count filtered on a hard-coded
  `author_mismatch` that the validator never emits at that level. Matching references -- including
  likely-hallucinated ones -- were therefore counted as neither verified nor unverified and never
  reached triage. `needs_triage` and the `unverified` total are now derived by negation (any
  checked reference whose status is not `verified`), so an unrecognised status can no longer fall
  through.

### Added

- The offline DBLP database location is configurable via the `$HALLUCITE_DBLP` environment
  variable (default unchanged: `~/hallucite/dblp.db`), honored by `audit_references.py`, the
  `mise` tasks, and the bundled skill.

## [1.2.0] - 2026-05-28

### Changed

- Stage 3 triage searches in escalating breadth: when a title-plus-author query finds nothing, it
  broadens to an unquoted title search and screens the results instead of concluding "not found".
  Obscure and predatory venues are poorly indexed, so a narrow miss is no longer treated as
  evidence of fabrication.

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
  Scholar; an LLM then triages the references no database confirms and writes the
  reports. Packaged as a runnable mise project and a Claude Code plugin.

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
