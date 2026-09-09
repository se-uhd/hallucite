# Changelog

All notable changes to hallucite are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

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
