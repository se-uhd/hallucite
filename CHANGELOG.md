# Changelog

All notable changes to hallucite are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## [2.0.0] - 2026-09-12

hallucite no longer depends on the package it was built around. Stages 1 and 2 are its own
extraction, parsing, verification and DBLP ingest, written against a black-box recording of the
external verifier rather than from its source, which is what lets this MIT repo drop an
AGPL-3.0-or-later dependency. Everything below was measured before it shipped.

### Added

- **The audit runs on hallucite's own modules.** `audit_references.py` builds a `Verifier` and
  parses through `reference_parser`; nothing on the audit path imports `hallucinator`.
  `DEFAULT_ONLINE_DBS` is the four backends `verifier` emits and `KNOWN_LOCAL_DBS` is `["DBLP"]`,
  or the two drift tripwires would fire on every run. `_second_opinion_pass` and
  `_author_absence_pass` are gone: the DBLP backend *is* the all-candidates check, and the author
  tier is decided inside the rule rather than by a pass over whatever a lenient backend cleared.

  `parse_reference` reads one segmented entry, recognising each style by the mark that separates
  the author list from the title -- a standalone year, a parenthesised one, an "et al.", an opening
  quote, a colon after inverted names, a comma after initials-led ones, the surname-and-initials
  run the medical styles print -- and falling back to the leading sentence. Measured over the 2065
  references of the 41-paper corpus with the offline mirror as arbiter, so that a reading is better
  when a real record confirms it, it is confirmed for 1480 references against the recording's 1399.
  Most of the difference is a venue following the title without an "In", which used to be read as
  part of it. Two references the recording confirms and this does not each name a person DBLP
  spells differently ("Rick Schlichting" for "Richard D. Schlichting", "Tom Zimmermann" for
  "Thomas Zimmermann"); the recorded parser stopped at 15 authors, so on the longer of the two
  there were fewer names to match. Both reach triage as `mismatch` carrying DBLP's record, where
  the name difference is the first thing a reader sees.

  `check` asks five backends, cheapest first, each only about what the ones before it missed: the
  offline DBLP mirror, CrossRef's bibliographic search, DOI resolution through CrossRef and then
  doi.org content negotiation, arXiv by identifier a hundred at a time, and Semantic Scholar's
  paper search one reference at a time. Open Library, PubMed and Europe PMC are not covered; over
  the corpus they decide 1.4% of confirmations between them, the statistics classics an empirical
  paper cites and the books it cites without a DOI, and a reference only they would have matched is
  reported `not_found`, which records a weaker search rather than a stronger claim. Retraction
  status rides along wherever CrossRef answered anyway, so it costs no extra request; a reference
  the mirror confirms is not retraction-checked, which would cost a request per confirmation.

  Held to the recorded verdicts of all 2065 references, the new modules confirm 1666 against the
  recording's 1669, losing 44 and gaining 41. Reading the 44: 19 are a `mismatch` the recording
  cleared, five of which name a real paper under an author list mostly not on it; eight are a tool
  or a web page with no author, which the recording confirmed by matching a title against an
  unrelated record; four are citations dropping a word from the real title ("An in-depth study" for
  "An In-depth Empirical Study", "Advanced compiler design implementation" for "Advanced Compiler
  Design and Implementation"), which the triage rules say a human should confirm rather than a
  matcher. Of the recording's verdicts, 266 unverified references carried a backend failure, so not
  one was a clean negative; 53 of the new run's do. Fed the *recorded* parse instead, so the two
  halves stay separable, `check` confirms 266 of the same 295: the gap is the recorded parser's
  output meeting a stricter check, where a venue glued into the title no longer passes a DOI that
  resolves to the real title and a surname-only author list no longer passes the author rule. Both
  gaps close when the new parser feeds the new verifier.

  Semantic Scholar is asked only where `--s2-api-key` or `$S2_API_KEY` supplies one. Anonymous
  callers share one small quota: asked about 106 real residue references, paced three and a half
  seconds apart, it refused 102 and confirmed none of the four it answered, and asking anyway would
  mark an arbitrary handful degraded and a different handful next run -- the churn that moves the
  boundary between `verified` and "needs triage" between identical audits. With a key it answers
  102 of those 106, and over the whole 510-reference set decides two confirmations no other backend
  reaches, both books or technical reports. The recording credits it 24 of its 1669 because it was
  asked about a different residue: this implementation puts CrossRef and the DOI resolver ahead of
  it. It is kept because nothing else covers that material, and both numbers are here so the next
  person can decide from the same measurement.

  Two regressions the cutover produced and the tests caught, both the new modules being stricter
  than what they replaced. A word a two-column layout splits with no hyphen to mark it ("distributed
  sy stems") went into the FTS query as a token the index does not hold, so a title the mirror held
  was never retrieved, though `titles_match` compares on letters and never saw the space; retrieval
  now asks one more query per short fragment, glued to its neighbour, only where nothing else
  matched. And a citation dropping an elided particle ("Marcelo Amorim" for "Marcelo d'Amorim") no
  longer reads as a different person, the given name still having to pair, so it widens the surname
  rather than the rule.

- **The offline mirror is hallucite's own ingest.** `build_dblp.py` replaces `hallucinator-cli
  update-dblp`, and with it the Rust toolchain, the prebuilt binary, `install-cli`,
  `install-cli-patched` and `dblp-entity-fix.patch` -- which existed because the stock ingest could
  not resolve the dump's character entities and dropped every author whose name carries a diacritic.

  The entities are resolved in the byte stream as *numeric* character references rather than as
  characters: the dump declares ISO-8859-1, so UTF-8 spliced into it decodes as Latin-1 and
  "Jürgen" arrives as "JÃ¼rgen" -- the same mangled-name failure one layer down, which the first
  version of this script had. An edited book records its people in `<editor>`, and that is who a
  citation of it names, so those are read where there is no author; a `<www>` person homepage is
  not a publication and would otherwise put three million people's names in the title index.

  Held to the mirror it replaces: 5000 records agree on title, year, type, electronic edition and
  the full author list, with none differing. Built end to end it produces 8,720,206 publications and
  4,295,062 authors, 246,351 of them with a non-ASCII name, and over the 2065-reference corpus the
  two mirrors confirm the same 1502 references with **not one** deciding differently. It takes 4.8
  minutes against the previous ingest's 20 to 30, and needs nothing but the standard library.

- **The evidence the audit already had reaches the triager.** Three things `verifier` knew about an
  unverified reference that no worklist or report showed, each re-measured over the 55-paper
  corpus's offline residue -- 788 of 2857 references -- before anything was built against it,
  because the numbers `TODO.md` carried came from a residue whose PDFs are gone. Nothing here
  changes a status.

  - *That the mirror was asked at all.* The DBLP backend reports `skipped` for a title `queryable`
    refuses, and a `not_found` read the same whether the mirror came back empty or was never asked.
    Over the residue that is 123 references, not the seven the head-to-head had counted: most are
    tools and web pages with a one-word title the mirror would not hold anyway, but Breiman's
    "Random Forests", Cochran's "Sampling Techniques", Hubert and Arabie's "Comparing partitions",
    Seaman's "Qualitative Methods", Dolan's "Algebraic subtyping" and a dozen more real two-word
    publications are among them, and every one read as a clean negative. `skipped_dbs` travels with
    the worklist entry and the report prints `Not asked: DBLP, ...`, keyed on the one status string
    `verifier` emits and never on a list of names.

  - *What the cited identifier resolves to.* `verifier` fills `doi_info` and `arxiv_info` with the
    resolved title and `triage.py` read neither. Resolved for the 169 residue references carrying a
    DOI or an arXiv id, those two backends only, no request refused. Of the 127 DOIs, 88 resolve to
    the cited title, 34 to a different one and 5 are dead; of the 54 arXiv ids, six were never
    reached because the DOI ahead of them had confirmed the reference, 25 resolve to the cited title
    and 23 to a different one. Reading the 57 that differ: most are the parser's title carrying
    venue text or cut short, where the resolved title is exactly what a reviewer needs; about a
    dozen are a preprint renamed between versions; a few are artifact DOIs whose deposit title
    differs from the paper's; and four name another work outright -- a DOI *and* an arXiv id for
    "Benchmarking LLM Test Generation on Complex Control-Flow Structures" both resolving to "A
    Systematic Approach for Assessing Large Language Models' Test Case Generation Capability", a
    second DOI in the same paper, BashExplainer's DOI resolving to a paper on AutoML tools, and a
    "Syntax-aware Retrieval Augmented Code Generation" arXiv id resolving to a paper on narrative
    XAI. The worklist entry carries `identifiers` -- kind, id, whether it resolves, the resolved
    title, and whether that is the cited title under `titles_match` -- and the report prints one
    line per identifier: dead, resolves to the cited title, or resolves to a different title, named.

  - *The mirror's nearest title, gated on authorship.* `dblp_check.nearest_title` is a sibling of
    `record_context`: asked only where the DBLP backend answered `no_match`, it offers a record
    whose title is within two word-level edits of the cited one and requires every cited person to
    be on it. Retrieval leaves every pair of the title's selective words out of an AND query, so a
    record still carrying all but two of them comes back whichever two moved. Over the 619 residue
    references the mirror answered `no_match` for, 66 have a title within two edits ungated, and 33
    of the 66 are different works -- Roy and Cordy's clone-detection survey against a 2019 paper of
    nearly the same title, Ford and Fulkerson's "Maximal flow through a network" against Strang's
    "Maximal flow through a domain", Kaplan and Meier against an encyclopedia entry, three
    Technometrics *reviews* of the cited statistics books, six Apache Software Foundation pages
    against one Computer column -- each of which would have argued a correct citation of an
    uncovered work into a "citation error". Gated, 32 remain and all 32 are the cited work. The gate
    costs one real lead: Holmqvist's eye-tracking handbook, cited under its six authors where DBLP
    lists only the first, is refused because the record does not mark itself truncated. The lookup
    takes 47 s over the residue.

  Guarded by smoke tier 3j through `attach_mirror_evidence`, `cmd_worklist` and `cmd_report`, and
  by six mutation entries; the mutation run fails for each.

- **`measure/`: the measurements this entry cites, as scripts.** `extraction_census.py` tabulates
  what every corpus paper extracts and what moved against a baseline; `corruptions.py` builds the
  corruption harness once, from a fixed seed, and scores an implementation against a built set;
  `head_to_head.py` scores the old and new parser and DBLP check over the recorded cases or the
  corpus, and keeps the old verifier off the network by construction; `mutations.py` reverts one fix
  at a time and requires the suite to fail, and fingerprints the tracked tree between entries so a
  file edited mid-run stops it rather than being read half-written, where the failure it causes is
  indistinguishable from the revert's and reports an unguarded fix as guarded; `residue_evidence.py`
  reads an offline audit's output and prints, per unverified reference, what the three items above
  found. The built sets live beside the other anchors in `~/hallucite/`.

- **Every corpus bibliography shape, as a committed test fixture.** The 55-paper corpus is the
  measurement baseline for extraction and it lives outside the repo, because the papers are other
  people's manuscripts; a clone and CI had no extraction net beyond two hand-written fixtures.
  `tests/fixtures/make_corpus_fixtures.py` derives one synthetic paper per corpus paper: the real
  `pdftotext -layout` output with every author name and title word replaced by an invented word of
  the same length, so column positions, hanging indents, running heads, margin numbers and trailing
  biographies all survive and nobody's authorship does. What has to survive substitution is the
  structure the parser reads -- the connectors, the venue and locator vocabulary, the section
  heading, and the name particles, taken from `pdf_references._PARTICLE` so the two cannot drift.

  The generator refuses to write a fixture whose extraction does not match the real paper's, and
  that check found two ways a cipher silently destroys a bibliography. Ciphering the particle in
  "de Castro-Cabrera" ends the hanging-indent block on the spot, because the particle is what tells
  the entry gate a line opens an entry. And ciphering the "EFERENCES" half of the small-caps
  heading `pdftotext` renders as "R EFERENCES" loses the section for a whole paper -- eight of the
  fifty-five, every one an IEEE template, and invisible on a two-column page where the heading
  shares its text line with the right-hand column.

  All 55 reproduce their paper's style, reference count, unparsed count and missing-number set
  exactly: 2857 references, 0 unparsed, and the one printed entry number no reference carries.
  Checked for leakage too: of 69,200 words of four letters or more across the fixtures, the only
  ones that also occur in the paper they came from are seven of the generator's own invented
  syllables, and no corpus paper's title survives anywhere. Smoke tier 4j drives all 55 through
  `extract_references` against `corpus/EXPECTED.tsv`, which is written from the real papers rather
  than from the fixtures, so the net is anchored to the corpus and not to the thing it checks. It
  adds 1.8 s to the suite.

### Fixed

- **Five corpus papers lost their whole bibliography, and three more were losing entries quietly.**
  Adding EMSE and JSS put the unnumbered hanging-indent author-first bibliography in front of the
  extractor for the first time -- Elsevier's Harvard style, ending the author list with a bare year
  (`Cao, S., Sun, X., 2024.`), and Springer's plainnat, putting the year in the venue field hundreds
  of characters later. `_dominant_style` counted an entry as author-year only on a *parenthesised*
  year, so two papers read as no style at all and were never segmented, and three read as numeric on
  a handful of continuation lines opening with digits and segmented as one entry. The same gate was
  already costing the three author-year papers among the original 41: the ACM author-year paper lost
  every two-author entry (`Haipeng Cai and Raul Santelices. 2014.` does not match `_AUTHORYEAR`) and
  the two Springer papers lost every organisation (`OpenAI (2024)`, `GitHub (2021)`), all glued into
  the entry before them where only a second `(year)` gave them away.

  The hanging indent is the structural signal, and four things had to change for it to carry the
  weight. The right column of a two-column page is shifted to the left column's text edge before
  anything reads the indents, because the gutter cut leaves the right column two characters in under
  an ACM template and seven under Elsevier's, where "entry" in one column meant "continuation" in
  the other; the centred page number the cut lands inside is dropped rather than moved. With a
  hanging indent only a line at the entry column can vote for a style, so a digit-led continuation
  is not a numeric label. At the entry column an entry needs no year, only to open with a name or an
  organisation and go on to more names, an "and", an "et al.", a year in any form, or a lone
  author's period and the title's capital; `_AUTHORYEAR` stays the gate where there is no hanging
  indent. And the block ends where the layout does: Elsevier prints the authors' biographies after
  the bibliography under no heading, as justified paragraphs at the entry column, and one paper
  carried nine "references" of prose about where its authors studied.

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

  Every entry-column line in the eight now opens an entry except one ACM footer (`Received
  2023-09-29; accepted 2024-01-23`), appended to the last reference where it stays visible. The
  other 47 corpus papers extract exactly as before; the corpus goes from 2615 references (2
  unparsed) to 2857 (0 unparsed), and the five recovered bibliographies confirm 19 of 22, 34 of 38,
  37 of 45, 34 of 59 and 37 of 43 against the mirror. Guarded by smoke tier 4i, which drives the column alignment, the
  style vote, the entry gate and the biography stop through `extract_references` on a three-page
  synthetic paper, so no one of them can be reverted without the others noticing.

- **A bibliography could lose whole references and nothing downstream could tell.** Over the
  41-paper corpus, 15 references the bibliographies' own numbering prints never reached
  verification: seven at the tail of one paper, eight swallowed by the entry before them. A
  reference that never arrives cannot be reported as unverified, so the audit had no way to say so.
  Extraction now produces 2081 references against 2066, with no gap left in any of the 41 numbering
  runs, and the offline mirror alone confirms 1503 against 1483. Three causes, all in
  `pdf_references.py`:

  - The running head hides the gutter. It spans both columns, so the column gap is not blank on its
    line, and `_gutter` weighed such lines as a *proportion* of the page -- the same head passing on
    a full page and failing on a short one. A final bibliography page of 33 lines gives one bridging
    line 3% of the vote and loses the column split for the whole page, and with it seven references.
    Page furniture is now removed before the gutter is measured.
  - The cut was placed at the midpoint of a band found at 97% tolerance, so on a page where one line
    runs into the band it landed inside that line's word, leaving a letter behind and gluing the
    next entry onto its predecessor. It now falls in the longest run of columns blank on every line.
  - A reference can trip both running-head filters at once. Five entries in one paper read `[N]
    "CVE-2022-1975," https://nvd.nist.gov/...`: the justification gap is the wide gap a head keeps,
    and `_head_norm` strips the digits that are the only thing telling the five apart. `_segment`
    now asks whether a line opens the next entry in the sequence *before* the noise filters, which
    a head cannot satisfy: it would have to carry the one number the sequence expects next.

  Comparing furniture needed narrowing too. What varies between one page's head and the next is the
  page number, at one end of the line, so only a leading and a trailing number are removed. And
  `_missing_numbers` walked the run from the lowest number that arrived, so a bibliography whose
  extraction begins at `[2]` reported no gap; walking from 1 found a sixteenth lost reference,
  `tse-2607.29422v1.pdf`'s `[1] Aider, "Aider," 2026`, printed in the right column beside a figure.
  The matching check for a swallowed *tail* was measured and cut back to the bracket styles: a
  plain-numeric bibliography prints `30.`, which is not a distinctive label, and over the 41 papers
  the bare-number form found exactly one thing, an access date broken across a line, and no real
  swallowed entry at all. Extraction now reports the entry numbers a numbered bibliography prints
  that no reference carries, and the audit warns about them -- the one invariant such a bibliography
  gives for free, and what caught all three faults above.

- **Nineteen parser gaps, each one a real citation the backends could not be asked about.** Over the
  55-paper corpus verified against the mirror alone, the three the new bibliographies exposed lift
  confirmations from 1981 to 2057: 75 references from `not_found` to `verified`, 2 to `mismatch` on
  a name form the record now retrieves, none the other way. Elsevier joins the venue to the title
  with a comma rather than a period, so no sentence break separated them and the venue was read as
  part of the title -- over the JSS residue that was most of the `not_found`. A hyphenated initial
  (`K.-W. Chang`) was neither an initial in the IEEE comma reading nor an abbreviation in the
  sentence reading, so `..., B. Ray, and K.-W. Chang. Unified pre-training ...` parsed to the title
  `and K.-W`. And LaTeX abbreviates an accented given name to `J.ã.P.`, which pdftotext renders
  `J.a.P.`, so `Fernandes, J.a.P.` read as two people.

  The six the residue evidence surfaced were measured together over the 55-paper corpus against
  the mirror alone: 35 references move from `not_found` to `verified` and two to `mismatch`, and
  751 of 2857 are left for triage where 786 were. Every one of the 35 is the cited work, with the
  cited people on the matched record. The corruption harness is unchanged on every deciding column,
  the head-to-head over the recorded cases is unchanged in all four combinations (1519 / 1509 /
  1462 / 1543, no reference moved), and the extraction census is unchanged. Over the whole corpus,
  DBLP only, the new path confirms 2106 against the old path's 2009, where it confirmed 2070
  before. Individually: Springer's `URL https://...` cost eleven references in two EMSE papers;
  Elsevier's comma-joined venue changed the title of 19 of one JSS paper's 44 references, 13 of
  which then verify, and moved two statistics books to a `mismatch` against the Technometrics
  review of each rather than a `not_found`. Measured and rejected alongside them: reading a `?` as
  a subtitle mark in `titles_match`. Over the 35 corpus residue titles carrying one it gains a
  record for four -- three are the parser cuts fixed here, which now verify on the whole title, and
  the fourth pairs Conway's "How do committees invent?" with an ACM Queue column of that head by
  another author.

  The rest, each reaching triage as an honest `not_found` on a title no database holds:

  - A particle surname written surname-first parsed to no authors at all. `_name_like` wanted a
    capitalised word and `d'Amorim` -- which `VERIFICATION-SPEC.md` names -- has none, so the whole
    Springer-style byline failed to read as an author list. A reference with no authors cannot be
    confirmed by anything. `van den Bergh` and `De Lucia` were already right in both orders.
  - An organisation was split on its own `and`: "Institute of Electrical and Electronics Engineers"
    became two authors, "Barnes & Noble Research" two more, and under the author rule both halves
    then had to be matched by a real person. A byline with no comma, no initials, a lowercase
    function word and eight words or fewer is one body's name. The bounds matter: without them a
    whole entry whose title carries "for" and "and" reads as a single corporate author, which cost
    one corpus reference its title.
  - A suspended hyphen was closed like a line break, making "Joining Player- and Data-Driven
    Analytics" into "Player-and". A hyphen before a conjunction elides the second half of a
    compound and the space after it is the word boundary, not the layout's.
  - One inverted author split across two chunks read as two people. `Zeller, Andreas. 2009.` parsed
    to `['Zeller', 'Andreas']`, and because pairing is one-to-one the two competed for the single
    record author, leaving one unmatched -- which the author rule read as a person the record does
    not have. The record settles it: two cited entries pairing with exactly one record author, the
    same one, whose words together are contained in that author's name, are one person written
    apart. An invented "Mallory Fake" pairs with nobody and is never excused. Merging the two chunks
    in the parser instead was measured and rejected: it is not decidable there -- `Akhavan,
    Hosseinpour` is two people and `Zeller, Andreas` is one -- and over the corpus it changed no
    author list and no confirmation either way.
  - A stray mark between two names disqualified the whole author list: "OpenAI, :, Aaron Hurst, et
    al." parsed to no authors.
  - A version number the layout broke across a line read as two sentences, so "Deepseek-v3. 2:
    Pushing the frontier" was cited as "Deepseek-v3". A period between two digits is not a sentence
    end; a period between a letter and a digit still is, which keeps a venue opening with its year
    out of the title.
  - The parenthesis an entry appends to its own title stayed in it: the conference acronym ACM
    prints ("Phraselette: A Poet's Procedural Palette (DIS '25)"), an edition, a year with no comma.
  - A year printed after the title with no comma to mark the field stayed in it ("Causes and
    canonicalization for unreproducible builds in java (2025)").
  - `URL https://...` is the identifier's label, not a title word; a Springer entry read as the
    title `URL`.
  - A title was cut at its own `!` or `?`; the mark ends the title only when what follows reads as a
    venue, judged on the text up to the next mark.
  - A title opening with its own roman numeral was cut to the numeral (`VII`), and the role after
    IEEE's comma-delimited names was read as the title (`editors`).
  - An `et al.` followed by a comma says the venue is the next comma field, and a bare publisher
    field ends the title.
  - `Al` is a name particle and the tokenizer was deleting it as the tail of "et al." -- 3,999 DBLP
    authors carry it, and "Fahmid Al Rifat" could not match a citation of itself.

- **A DOI broken across a line was emitted as the half before the break.** At one of its own
  hyphens, after a period, between `10.48550/arXiv` and the identifier, or at an underscore.
  Eighteen corpus references carried a DOI that resolves to nothing, which triage reads as
  fabrication signal (D), and thirty more carried none at all, their identifier broken at the slash.
  The underscore case is the sharpest: `_looks_cut` knew a trailing hyphen and a digit-free suffix,
  but a break at `_` leaves a suffix ending in a digit and looking finished, and what survives is
  the *book's* DOI where the citation named a chapter -- `10.1007/978-1-84800-044-5` for `..._2` --
  which resolves, to another work. pdftotext renders the underscore as a space, so the far side is
  still in the text: four corpus references are now rejoined and every one resolves to the title its
  entry names. Over the corpus 60 DOIs break after one of the identifier's own periods and every
  one resumes with digits -- an article number, a year-led segment, an Elsevier `03.006` -- which
  nothing but the entry's own year does, and that is the one shape refused. 42 corpus DOIs change
  across 19 papers; resolved through the DOI backend alone, 38 come back as the cited title, three
  are dead as printed (the paper's own wrong identifier, now whole rather than half) and one named
  a title the parser was still cutting. Withholding a bare ISBN suffix instead was measured and rejected, being also what a
  citation of the *whole book* correctly carries, which two corpus references do, one of them a
  confirmation the DOI resolver made. The rejoin fires only where the text actually continues, and
  not on a four-digit year, which is the entry's own date running on. All 590 DOIs the corpus
  carries still come through. An arXiv identifier written as a CoRR volume is read too (`arXiv, vol.
  abs/2410.15631`, `CoRR, vol. abs/1901.09102`), which is how the IEEE styles print one and how 17
  corpus references carry theirs.

- **A citation could append invented authors to a real paper and still verify.** The rule was that
  greedy pairing had to match `min(cited, stored)` authors, and padding the citation raises only the
  cited side, so the stored side kept fixing the threshold. Measured over 250 real DBLP records,
  appending one, two or three invented names to the true author list was confirmed 250 times out of
  250 -- signal (A) in `SKILL.md` and the pattern `VERIFICATION-SPEC.md` calls the one this tool
  exists to catch: a real title, a real venue, correct pages, and people who did not write the
  paper. `_author_absence_pass` could not catch it either, comparing only lists of equal length.

  Every cited name that reads as a person must now be matched by an author of the record. The
  citation may still name *fewer*, which is what "et al." means.

  | author rule | corpus confirmed | clean | "et al." | first author only | +1 invented | +2 | +3 | one swapped |
  |---|---|---|---|---|---|---|---|---|
  | `min(cited, stored)`, >=2 matched | 1459 | 250 | 250 | 0 | 250 | 250 | 250 | 0 |
  | every cited name, >=2 matched | 1455 | 250 | 250 | 0 | 0 | 0 | 0 | 0 |
  | every cited name | **1478** | 250 | 250 | 250 | 0 | 0 | 0 | 0 |

  The "at least two matched" rule went with it: it refuses 23 corpus references, every one a real
  work cited as "First Author et al.", and refuses no corruption that one matched name lets through.
  What the change buys on the corpus rather than on constructed corruptions: 18 references the
  recording confirmed are now a `mismatch`, five of them naming a real paper under an author list
  mostly not on it. `RepoFuse` and `BashExplainer` pair one cited name in five with the record,
  `RepoHyper` none in three, `RepoFormer` two in four -- a correct title and DOI, and people who did
  not write the paper. The old verifier cleared all five without a human seeing them. Of the other
  13, eight differ by one or two names and five carry a title the mirror does not hold at all.

  Name comparison is a pairing rather than a subset test. A middle initial the record does not carry
  no longer refutes ("Mohammed F Kharma" is "Mohammed Kharma"), nor does a particle on one side only
  ("Emiliano De Cristofaro" is "Cristofaro, E."), nor a generational suffix. What still refutes is a
  contradicted given name: "Q. Muñoz Barón" for "Marvin Muñoz Barón" was confirmed 22 times in 250
  by the first version of this rule and is confirmed none. Author *lists* are paired by augmenting
  paths rather than first-fit, because taking the first partner that fits lets one cited name consume
  the record author another needs -- "Xin Xia" fits both "Xin Xia 0001" and "Xin Xiao" -- and refuses
  a correctly cited paper.

- **The phantom-author rule had one tier where the contract asks for two, and the lenient tier was a
  wildcard.** `verifier` applied "every cited name must be matched" to every backend and every
  record, with no equivalent of `_complete_author_dbs`, so a record that is not a complete author
  list was read as one. Over the 2065-reference corpus that refused 42 references the recording
  confirms: 18 are an LLM technical report DBLP credits to the group rather than the people
  (`OpenAI`, `Qwen Team`, `Llama Team`, `DeepSeek-AI` -- one stored author against a citation that
  correctly names ten), one is StarCoder 2, whose record holds 57 of 66 authors and writes `et al.`
  for the rest, and the remainder are name forms. Five are the citations the rule exists to catch.

  The tier is now read off the data, per run and per record, as `VERIFICATION-SPEC.md` requires:
  `mirror_authors_complete` asks whether this mirror's ingest kept its accented authors, and
  `record_authors_complete` whether the byline in hand is a list of people at all. Against an
  incomplete record an unmatched cited name is absence of evidence and does not refute; a name the
  record *contradicts* still does. Over 250 real records the corruption columns are unchanged --
  none of those 250 is incomplete, which is the point. Over the 2081 references the 41 papers
  produce the mirror now confirms 1521 against 1503; the references the recording confirms and this
  refuses fall from 42 to 24, and the 24 are the five bad citations plus name forms a human should
  read. Against a mirror built by the stock ingest, which drops every author whose name carries a
  diacritic, the 154 correctly cited references it refused fall to 8.

  A lenient tier needs a floor, and this one had none: nothing required any cited name to be
  *present*, so "StarCoder 2" cited under two invented names verified against its 57-person record,
  and any author list at all on "Book Reviews" verified through the one record with an `et al.` row.
  The people a truncated record does list are evidence, and a citation pairing with none of them has
  had every name it offered come back foreign. DBLP keeps the first authors when it truncates and a
  citation names them first, so a correct citation pairs at least one. Measured on a third set of 90
  records carrying an `et al.` row: cited correctly, 90 confirm before and after; cited under two
  invented names, 90 confirmed before and 0 after; one invented name appended to three real ones
  still confirms, which is the tier doing what it is for. Nothing moves on the recorded cases or the
  corpus. A record credited to a group rather than to people still has no person to pair against and
  clears on the title -- "GPT-4 Technical Report" under two invented names verifies, and only the
  arXiv backend, asked by identifier, can say otherwise. `VERIFICATION-SPEC.md` states the bar.

- **Title comparison and retrieval.** Titles are compared on letters alone, tolerating a subtitle on
  one side only, as the contract requires: removing a hyphen without leaving a space had made "Model
  Driven" and "Model-Driven" different titles, and a suspended hyphen different from itself.
  Measured over 250 real records: exact 250, respaced and rehyphenated 250, subtitles dropped 41 of
  the 71 that carry one; one content word changed 0, word order reversed 0, a wholly invented title
  0. Around that:

  - The query took the 50 lowest row ids rather than the 50 best matches, SQLite returning FTS hits
    in row order, and 3 of the corpus's 1,478 confirmations come from a record past row 50, one at
    row 2,507. Raising the ceiling costs no measurable time.
  - A title carrying a letter with a stroke or bar did not match its own record: the query folded
    `ł`, `ø` and `ß` to plain letters, which an author comparison must do, but the FTS index holds
    them as they are. Both foldings are asked now, and the word-wise AND query offers both readings
    of every hyphen at once, which a phrase query cannot.
  - An edition suffix on the record, in both shapes DBLP writes it, is trimmed before the
    comparison; the parser already trimmed the citation's. An alias DBLP writes in parentheses
    (`Tse-Hsun (Peter) Chen`) kept `Peter` from pairing.
  - Retrieval missed titles the decision would have accepted: a word split inside the *record's* own
    title, a word split in the citation with both halves too long for `_glued_query`, and an article
    the layout glued to its neighbour. AND queries over the title's words with one adjacent pair
    left out cover all three, asked last and only where nothing else matched. It also confirms the
    one record of the 250-record harness the clean citation had been missing, a title carrying
    `ℒ2-gain`.
  - An apostrophe was compared rather than folded, so `O’Donoghue` and `O'Donoghue` were two people;
    that alone cost seven corpus confirmations. An eszett a PDF renders as a capital B is read as
    one -- `Leßenich` comes out of pdftotext as `LeBenich` -- offered alongside the literal reading,
    and measured by disabling it over the corpus it is worth three confirmations, not the five first
    counted. The German transliteration of an umlaut pairs with the letter, "Buettcher" answering to
    "Büttcher", taken off the side that carries the umlaut so that only a name that really has one
    gains the second spelling; contracting `ue` in every name would rewrite "Miguel" and "Rodriguez"
    into spellings an invented author could hide behind. The corruption harness is unchanged on
    every column that decides, the head-to-head goes from 1508 to 1509 confirmations, and exactly
    the two corpus references `TODO.md` named move from `mismatch` to `verified`.

- **The DBLP path against the verifier it replaced.** Reproduced head to head over the 2065 recorded
  citations, DBLP only and offline: the old parser and old DBLP check confirm 1519, the new ones
  1502, gaining 34 and losing 51. The 51 read one at a time against the record the old path matched:
  23 are `mismatch` -- five citations naming people who did not write the paper, nine real
  discrepancies the rule exists to flag, nine name forms -- and 28 are `not_found`, of which fifteen
  cite a title differing from the record's in a content word and are refused on purpose, seven are
  two-word titles the mirror is not asked about, and six are the retrieval and comparison defects
  fixed above. Those six move, ending the recorded head-to-head at 1508 against 1519. Two of the
  eleven `TODO.md` called defects are not: the old path had confirmed the Jest documentation page
  "Getting Started" against a 1991 keynote of that name, and a standards body's "Security Framework
  1.1" against a 1988 paper called "A Security Framework"; a record-side prefix tolerance would
  reproduce both, and they stay unverified. Over the whole 55-paper corpus, where the recovered
  bibliographies count, the new path confirms 2068 against 2009.

  `_MIN_TOKENS` was measured at 2 and stays at 3, scored on corruptions built once and handed to
  both settings -- the same 250 real records, plus a second set of 250 with two-token titles, which
  is the population the constant changes and the one the first set cannot see:

  | `_MIN_TOKENS` | cases | corpus | 3+ tokens: clean / et al. / first / +1 / +2 / +3 / swapped | 2 tokens: clean / +1 / +2 / +3 / swapped |
  |---|---|---|---|---|
  | 3 | 1508 | 2068 | 250 / 250 / 250 / 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 |
  | 2 | 1513 | 2077 | 250 / 250 / 250 / 0 / 0 / 0 / 0 | 250 / 1 / 1 / 1 / 0 |

  The padded two-token citation that confirms is `Book Reviews`, a title 922 records share, one
  carrying an `et al.` row and listing a name the padded citation also lists. On the corpus the nine
  confirmations include one that is wrong -- Sommerville's textbook "Software engineering", tenth
  edition, confirmed against his 1983 conference paper of that title -- and six references move from
  `not_found` to `mismatch` against records of different works ("Github copilot", Fowler's
  "Continuous integration" page, "Virtual threads", "Logistic regression"). A false confirmation is
  the outcome the tool must not produce, and the three real two-word titles it would recover reach
  triage as `skipped`, which is true.

- **Which record a triager is pointed at, of several sharing a title.** 17% of corpus references
  carry a shared title. The published record now comes first instead of whichever has the lower row
  id, and where none matches the authors the near miss reported is the record accounting for most of
  them. Among records that all match, the citation's own text decides, in two steps measured
  separately over an `--offline` audit of the 55-paper corpus. 2106 references verify through the
  mirror, 679 on a title more than one record matches; for 631 the others are all CoRR preprints,
  which the published-first order settles, and 48 share their title with another published record.

  The year the citation prints, read off the raw text (`cited_years`: an IEEE DOI's year segment and
  an arXiv identifier are not years the citation prints; a page range that looks like one is the
  documented cost), names one record for 32 of the 48 and moves 21 -- five journal-first papers
  shown as their re-presentation at the SE conference, Fagan's 1976 and Brooks's 1977 articles shown
  as their 1999 reprints, Zimmermann's TSE 2010 article as the FSE 2008 paper, Fowler's *Refactoring*
  at the XP 2002 talk rather than the 1999 book, Tokuda and Batory's 2001 journal article at their
  1999 conference paper, Wohlin's 2012 book at its 2024 edition -- and the cited year names the right
  record in all 21. A rule preferring the cited year outright would also have moved 51 references
  from the published record to the CoRR one -- 39 that cite the arXiv version with its year, and 12
  whose journal issue DBLP dates a year after the online-first year the citation prints -- and the
  published record is the one a triager needs.

  For the other 16 the year names none: ten are two records of one year, five are Fowler's
  *Refactoring* cited as a 2018 edition DBLP does not hold, one is Murphy-Hill's TSE article cited
  with an online-first year no record carries. Ten of the sixteen name the record they mean outright
  in a field the mirror holds too, so `title_candidates` now reads the DOI, the page range and the
  volume off the raw text and the parsed DOI (`cited_dois`, `pages_match`, `volume_match`) and orders
  by those before the year. The DOI fires on 200 of the 679, the page range on 345, the volume on
  105; with the cited DOI as arbiter the page range names the same record 126 times and a different
  one once, on a DBLP duplicate carrying the same range twice, and the volume 36 times and never a
  different one. The locator names one record for 42 of the 48 and leaves 6. The published record
  stays first whatever either says, which keeps the 8 citations printing an arXiv DOI off the CoRR
  record that carries it as its `ee`.

  Diffed reference by reference against the audit before each step: no status moves, and the record
  shown changes for the 21 the year moves plus three `mismatch` near misses that tie on matched
  authors, then for exactly six more -- Goodenough and Gerhart's 1975 TSE article shown as their
  Reliable Software paper of the same year (in two papers), "Why Should I Trust You?" cited from
  SIGKDD and shown as the NAACL demo, Kim's TSE 44(11) 1024-1038 shown as the ICSE journal-first
  entry, Murphy-Hill's TSE 38(1) 5-18, and Thorup's JCSS 69 330-353 shown as the STOC paper. Every
  one lands on the record its own citation names. Both corruption harness sets come back identical
  and cannot see either rule: their stand-ins carry no raw citation and no DOI.

  A page range must equal the record's `pages` at both ends. The single-page and ACM article-number
  forms were measured and left out, settling one further reference that row order already shows
  right. The locator goes ahead of the year because a DOI or a page range identifies one record
  where a year identifies a set; on this corpus the two orders make the same six changes, so the
  order is the design choice and not the finding. Measured on top of the shipped key and turned
  down: ranking a book ahead of an article ahead of a conference paper where no matching record
  carries a cited year moves 5, every one right, but all five are one work and the restriction is
  fitted to it, and unrestricted the same ranking is wrong once in six; the record's venue text
  appearing in the citation moves the same five and nothing else, but only because the locator now
  settles ahead of it the reference that made it wrong under 1.19.0, where "Software Engineering"
  matched inside "European Software Engineering Conference"; author count and non-DOI `ee` URLs
  change nothing at all. Also turned down: preferring a book record for an entry that names a
  publisher, whose list of publisher names fired on a co-author surnamed Pearson.

  Guarded by smoke tier 5c through `Verifier.check` -- one citation per key over a same-year pair
  that nothing else separates, one printing its DOI only through the parsed field, one printing none
  of the three, one printing one record's locator beside the other's year, and one printing the
  arXiv DOI the pair's preprint carries as its `ee`. Without that last, no fixture preprint carried a
  locator field and the published-first key could be moved below the locator with the suite still
  green. Ten mutation entries cover the two rules; the run fails for every one.

- **A backend that answered 200 with a body it could not read was reported as a clean negative.**
  `_arxiv_entries` returned an empty dict both for "arXiv holds none of these identifiers" and for
  "that was not a feed", and an HTML outage page is well-formed XML with no entries. The result was
  `no_match`, an empty `failed_dbs`, `degraded: false` -- and `arxiv_info.valid=False`, the shape of
  fabrication signal (D). One bad batch response covers up to a hundred identifiers. The root tag
  now separates the two, which is what `_fetch_json` already did for the JSON backends. Three
  siblings went with it: a 404 from the CrossRef or Semantic Scholar *search* endpoint said the
  endpoint moved, not that the work does not exist; a CrossRef 200 carrying no `items` key is an
  error envelope, not an empty result set; and Semantic Scholar's soft refusal is a 200 carrying
  `{"message": "Too Many Requests"}`, which was read as an empty result and also reset the give-up
  counter. A backend that did not answer must never be equivalent to `no_match`, because triage is
  told to weigh a `not_found` from an incomplete run less, and an empty `failed_dbs` is what tells
  it the run was complete. An arXiv identifier a batch request omits is asked for again on its own
  before it is called dead: arXiv answers 200 and drops what it will not serve, such as an old-form
  id written with its subject class, as citations write it.

- **Semantic Scholar's give-up counter never tripped under an intermittent block.** It counted
  *consecutive* refusals and this backend throttles in bursts -- one answer in twenty resets it --
  so on a real corpus it never reached 25 and every refused reference still paid the full retry
  ladder: four attempts at 2, 4, 8 and 16 seconds on top of a 45-second ceiling each. A
  2065-reference replay spent most of three hours there for the 1.4% of confirmations this backend
  decides. The ladder is the expense, not the question, so the fix is to stop retrying rather than
  to stop asking: a refusal costs 31 s with the ladder and about a second without it, while an
  answer takes 3 to 18 s either way, and after 25 refusals however they fall (`_S2_PATIENCE`) the
  extra attempts are dropped and every remaining reference is still asked. Capping the *asking* was
  tried first and measured against the same corpus: it cut the run from three hours to 57 minutes
  and the references carrying a backend failure from 177 to 60, and it cost five confirmations no
  other backend reaches. Asked again with the ladder dropped instead, Semantic Scholar matches 8 of
  the 49 references that replay lost.

  Three more network rules went with it. A rate limit naming no `Retry-After` was retried after a
  fixed two seconds, which walks straight back into the same limit; each attempt now doubles its
  wait, as the API asks. doi.org's content negotiation timed out on the records only it can resolve,
  redirecting to whichever registry holds the DOI, and DataCite took 8 to 32 seconds for real Zenodo
  DOIs against a 15-second ceiling -- so the artifact and dataset references with no other identifier
  were the ones reported unresolvable; that path gets 45 seconds, and so does Semantic Scholar's
  search, whose ordinary answers the 15-second ceiling was turning into timeouts. And a line-break
  hyphen went out to the online searches verbatim, which no index holds: the joined reading is asked
  too, though only when the first matched nothing, which is weaker than what the mirror does for its
  own queries -- the 16 corpus titles carrying a real compound and a line break at once are asked in
  neither of the two spellings that would find them.

- **A verdict of `author_mismatch` where nothing had been compared.** When every name in a parsed
  author list is a venue fragment the parser bled in, `matched_authors` reports nothing comparable,
  and the reference was reported as a record whose authors disagree -- a near miss a triager is shown
  and asked to weigh. It is `no_match`, which is what `_verdict`'s own docstring said all along.

- **`authors_absent` was read and never written.** The audit pass that filled it went with the
  cutover, so every worklist entry carried an empty list, the report line it fed never printed, and
  `SKILL.md` went on telling the triager the audit had found signal (A). It is derived where it is
  read, from the record the verdict rests on, and it names at least one person for every one of the
  46 `mismatch` references the mirror decides. And `triage.py`'s matched-record test is named
  positively: it excluded the failure statuses by name, which is how a `timeout` came to read as a
  matched record, and adding `timeout` to the list would have left the next new status to do the
  same. `match` and `author_mismatch` are the two that mean a candidate came back.

- **`run.sh` died on an ordinary `.env.local` line without its sentinel.** An indented comment or an
  `export FOO=bar` produced `export: not a valid identifier`, and under `set -e` that ended the run
  with a bash error and no `HALLUCITE_BOOTSTRAP_FAILED:` line -- the one thing the wrapper promises
  never to do, and the sentinel `SKILL.md`'s stop conditions key on. A CRLF file exported the API key
  with a trailing carriage return. mise's dotenv reader accepts all three, so the two did not in fact
  see the same values; they do now. Separately, `record_context` compared titles through a copy of
  `_letters` whose comment called it looser than the confirmation path: it is the same reduction and
  stricter, carrying none of `titles_match`'s tolerance for a subtitle on one side only, which it
  needs to be. The duplicate is gone.

- **Seven of the fixes in this release could be reverted with the smoke suite still green.** A
  mutation run -- revert one fix, run the tests -- found the `timeout` fix, the Semantic Scholar
  threshold, the FTS row ceiling, the apostrophe fold, doi.org's ceiling and both extraction fixes
  unguarded. The pattern was guards written as `C.eq(x, MODULE.THE_CONSTANT)`, which pass whichever
  value the constant holds, and helpers asserted directly while the caller that ignores them is not.
  Tiers 6, 6b, 6c and 6d pin the measured numbers as literals and exercise the callers; every
  mutation above is now caught.

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
