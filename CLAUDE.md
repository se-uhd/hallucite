# Claude Code guidance for hallucite

## What this is

`hallucite` finds hallucinated (fabricated) references in academic paper PDF files. Stages 1 and 2
(extract, then verify against DBLP, CrossRef, arXiv, and others) use no LLM; verification queries
the online databases unless `--offline` restricts it to the offline DBLP mirror.
Stage 3 (triage the database-unverified residue) is the LLM step, done interactively by you. See
`PLAN.md` for the design and architecture, `README.md` for commands, `CHANGELOG.md` for what was
measured and why.

Extraction, parsing, verification and the DBLP ingest are all hallucite's own and use only the
standard library: `pdf_references.py`, `reference_parser.py`, `verifier.py`, `dblp_check.py`,
`build_dblp.py`. One outside program is required and is not a Python package: `pdf_references.py`
shells out to `pdftotext -layout` (poppler), and without it extraction cannot run at all.
`VERIFICATION-SPEC.md` is the contract the parse and check halves meet. The modules replaced the
external `hallucinator` package, which is AGPL-3.0-or-later where this repo is MIT; nothing imports
it, and no code was copied across -- they were written against a black-box recording of it, kept
as `~/hallucite/verification-results-hallucinator.json`.

One repo, two roles: the runnable project (mise tasks) and an installable plugin for Claude Code
and Codex CLI, sharing one copy of the scripts in `skills/hallucite/scripts/`. The manifests and
symlinks that make that work are listed in `PLAN.md` under Packaging.

`~/hallucite/` holds everything too large or too mutable to commit, and the document below names
its contents constantly:

| path | what it is |
|---|---|
| `dblp.db` | the offline mirror, ~3.8 GB, rebuilt from the dump; `$HALLUCITE_DBLP` overrides |
| `dblp.xml.gz` | the DBLP dump `build-dblp` ingests |
| `corpus/` | the 55 measurement papers, with `MANIFEST.csv` (`file`, `venue_note`, `title`) |
| `fabricated-citations.json` | real citations and fabricated variants of them, three sets: scored, never rebuilt |
| `verification-results-hallucinator.json` | frozen; nothing reads it: what `hallucinator` returned for the 41-paper corpus |
| `verification-results-offline.json` | hallucite's result for every corpus reference, mirror only; `verification_results.py compare` diffs against it |
| `verification-results-online.json` | the same with all six backends, recorded 2026-09-17 |

## Running things

- The bundled skill drives the pipeline through `skills/hallucite/scripts/run.sh`, the single entry
  point (`check-env | audit | triage | lint | python`). `SKILL.md` documents how it is found and
  what it promises: there is nothing to install, it resolves a Python 3.10+ with `sqlite3` itself
  (`$HALLUCITE_PYTHON` pins one), and on any failure it prints a `HALLUCITE_BOOTSTRAP_FAILED:`
  line and exits non-zero rather than running half-configured. Its interpreter probe reads what
  the candidate prints, not its exit status, because `/bin/echo -c '...'` exits 0.
- In a repo clone you can equivalently use mise tasks: `mise run install | fetch-dblp-dump |
  build-dblp | audit | lint-md`. Both paths run the same scripts in `skills/hallucite/scripts/`.
- The offline DBLP database defaults to `~/hallucite/dblp.db`, outside this repo (large, not
  committed); override the location with `$HALLUCITE_DBLP`. The audit warns at run time when it is
  over 30 days old. Do not put it under the repo: an installed plugin is cloned to a managed dir
  the user never sees, so an in-repo (even gitignored) path would not work for marketplace installs.
- The mirror has two ways of being wrong, and `build-dblp` checks both because nothing
  else makes them visible -- publication counts, titles and record keys all look right either way.
  An ingest that cannot resolve the dump's character entities drops every author whose name carries
  a diacritic, and a download that returned dblp.org's bot-check page instead of the dump yields a
  small, valid, useless database. `build_dblp.py` resolves the entities as *numeric* character
  references (the dump declares ISO-8859-1, so UTF-8 bytes spliced in become mojibake) and
  `build-dblp` builds to a scratch file, swapping only after checking the publication count and
  that accented names survived. The audit reads the same property off whatever mirror it is handed
  and drops to the lenient author tier when the mirror cannot support an absence claim.
  `fetch-dblp-dump` takes the newest monthly snapshot, a citable release with a published MD5 that
  downloads with no browser and no package; `-- --daily` takes dblp.org's daily dump instead, which
  is up to a month fresher and needs Playwright and a display to answer the proof-of-work challenge
  fronting it. Prefer the snapshot: a measurement sampled from a mirror says which release built
  it, where "yesterday's dump" names nothing anyone can fetch again.
- Measuring a change. `measure/fabricated_citations.py score` runs the verifier over the fabricated
  set and must come back unchanged from any change to the title or author rules; `--scripts DIR`
  imports a snapshot of the modules, so a before-and-after needs no stash. The built set is scored,
  never rebuilt, because a rebuild on a newer dump samples different records. A change to
  extraction is checked by `tests/fixtures/make_corpus_fixtures.py`, which refuses to write a
  fixture whose extraction differs from the real paper's, and by smoke tier 4j over the committed
  fixtures.

  The three recordings answer different questions. `verification-results-hallucinator.json` is the
  specification the modules were written against and stays frozen.
  `verification-results-offline.json` is what a code change is diffed against:
  `verification_results.py compare ~/hallucite/verification-results-offline.json --impl verifier`
  replays it offline in about a minute and reports a parse difference and any reference crossing the
  verified line, and nothing else -- `paper_url` is recorded but never compared, and the replay
  hands `check` the parsed fields without the raw citation, so nothing that reads the entry's text
  runs. A change to the record shown is therefore confirmed by an `--offline` audit of the corpus
  before and after, diffed per reference, and the file is re-recorded offline after a change meant
  to move a verdict. `verification-results-online.json` was re-recorded on 2026-09-17 in 49 minutes,
  over the same corpus with all six backends: 2359 confirmations, of which the mirror decided 2109,
  CrossRef 181, OpenAlex 32, arXiv 16, the DOI resolver 11 and Semantic Scholar 10. What a recording
  cannot cover is a backend that refused that day. Semantic Scholar failed to answer for 232
  references even with a key, and those are the only degraded references in the file. arXiv's search
  API refused every identifier lookup that day, which is what the OAI-PMH fallback now covers; the
  references it left degraded were re-asked through the same `check` and merged back in, which is
  the repair to make when one backend has a bad day rather than re-recording the corpus.
  Re-recording is a corpus replay of about 50 minutes and most of a day's OpenAlex allowance, on a
  day the quota is fresh, and never twice in an afternoon. Never type a contact address on a
  command line or into a tracked file: `--mailto` defaults to `$CROSSREF_MAILTO`, which belongs in
  `.env.local` beside the API keys, and a run without one asks CrossRef one request at a time.

  `mutations.py` reverts one fix at a time and requires the suite to fail, and does so in the
  working tree, which it owns until it finishes: no other measurement, and no edit to any tracked
  file, Markdown included. The suite reads the CHANGELOG, the manifests and `SKILL.md` as well as
  the modules reverted, so an edit landing inside a run is read half-written and fails a check
  indistinguishable from the revert's, which reports an unguarded fix as guarded. It fingerprints
  the tracked tree between entries and stops if anything moved; work in a snapshot
  (`git ls-files -z | xargs -0 tar cf -`) instead.
- Stage 1/2 driver: `skills/hallucite/scripts/audit_references.py` (segments each reference via
  `pdf_references.py`, parses it with `reference_parser.py`, then runs `verifier.check`). The
  target is 0 unparsed references.
- Stage 3: `triage.py worklist | status | record | report`. Verdicts persist in
  `out/triage_verdicts.json`, keyed `paper_id:number`, under an `fcntl` lock, so triage can run on
  finished papers while the audit continues and workers can share the file; `worklist --paper <id>`
  is an exact-id slice for fanning out. `record --signals` enforces the title-first rule and
  `report` writes the per-paper checks, the rollup and the verification sheets, then lints them.
  What a worklist entry carries, and how to judge it, is in `SKILL.md`.

## Triage (Stage 3)

The protocol is in `skills/hallucite/SKILL.md` and nowhere else: the stop conditions, the
title-first classification, the T/A/V/D fabrication signals, the categories and the rule against
pushing a borderline case either way. Smoke tier 1 asserts `SKILL.md` carries the stop conditions
and tier 1b guards the fail-loud `run.sh` contract they key on, so a change to that protocol is a
change to `SKILL.md` and to those tests together. Do not restate it here.

## Conventions

### Repo, release and lint

- Editing a script under `skills/hallucite/scripts/` updates it for mise, Claude Code, and Codex
  CLI (one copy). On a real release, bump the version in `.claude-plugin/plugin.json`,
  `.codex-plugin/plugin.json`, and `skills/hallucite/SKILL.md` (`metadata.version`), add a
  `CHANGELOG.md` entry, and tag the release commit: `git tag v<version>` (lightweight, matching the
  existing `v*` tags and the CHANGELOG link footers). Run the smoke tests
  (`python skills/hallucite/scripts/tests/run_smoke.py`) and do not consider a release done until
  it is tagged and they pass.

- Commit messages follow Conventional Commits: `type(scope): imperative summary`. Types: `feat`,
  `fix`, `docs`, `test`, `ci`, `chore`, `refactor`; the scope is the pipeline area (`audit`,
  `extract`, `triage`) or tooling, and is omitted for cross-cutting changes. Keep the summary short
  and imperative and put detail in the body. Do not put the release version in the message -- the
  `v*` tag records the release.

- Keep Markdown lint-clean: `mise run lint-md` (`MD_FIX=1` to auto-fix). The vendored PyMarkdown
  in `skills/hallucite/scripts/` is synced from se-uhd/pymarkdown-skill; do not hand-edit
  `_vendor/`, `lint_markdown.py`, `check_baseline.py`, or `refresh_vendor.py` (re-sync instead).
  The hallucite-owned files are `schema_checks.py` and `lint_markdown.yaml`.

### Rules and contracts

- Verification `status` and `db_name` strings are `verifier`'s, and `VERIFICATION-SPEC.md` is where
  they are fixed; treat them as a contract that can drift. Define "needs triage" by negation
  (`status != "verified"`), never by an allow-list of failure strings, and keep the invariant that
  every reference is verified, unverified, or pending (none silently dropped). Validate any
  hard-coded backend name against what `verifier` actually emits: `run_smoke.py` covers the status
  strings, and the audit validates backend names at run time -- online runs warn about configured
  names that never appear (`DEFAULT_ONLINE_DBS`); `--offline` runs warn about live backends that are
  not known-local (`KNOWN_LOCAL_DBS`). A silent name mismatch is what caused both the `mismatch` and
  the `DOI Resolver` bugs. `VERIFICATION-SPEC.md` states the vocabulary a verifier has to emit;
  `verification_results.py` records the current behavior on real references and holds a replacement
  to it.

- Prefer a check the input already supports over one you have to tune. A numbered bibliography
  numbers itself consecutively, so a printed `[N]` that no extracted reference carries is one that
  never reached verification, and nothing downstream can report a reference that never arrived.
  That invariant surfaced all three of the extraction faults fixed in `_gutter`, `_linearize` and
  `_segment`; `extract_references` reports the gaps and the audit warns about them. The printed
  numbering cost nothing to check and needed no threshold. Look for the same shape elsewhere
  before writing a detector.

- A lenient rule needs a floor. A record that cannot refute must still be able to *confirm*
  something: the people a truncated record lists have to account for at least one cited name, or
  the tier is a wildcard that clears any author list on any title one incomplete record shares.

- A threshold expressed as a proportion behaves differently on small inputs. `_gutter` tolerated a
  fraction of lines crossing the column band, so one running head was 1% of a full page and 3% of a
  short final one -- the same head, passing on one page and losing the column split on the other.
  Where a rule has to survive a fixed amount of noise, count the noise.

- Decide from the data in hand, not from a name. Hard-coding DBLP out of the complete-author set
  because the mirror was broken survived the mirror being repaired, and a reference with two
  invented authors verified again. `mirror_authors_complete` and `record_authors_complete` decide
  per run and per record instead.

- Several widenings of name and title matching were measured and rejected -- name forms beyond the
  umlaut transliteration, `_MIN_TOKENS` at 2, a `?` as a subtitle mark, a book-before-article
  record key -- and the 2.0.0 entry lists each with its numbers. Read that list before widening
  either, and measure the widening on every fabricated-citation set before it ships.

### Measuring a change, and guarding it

- Measure a detection rule against a corpus before shipping it, and read the flags rather than the
  count. A rule that looks right on the case that motivated it can be almost entirely false
  positives at scale: demoting a verified reference on a backend's own `author_mismatch` flagged 22
  of 1016 corpus references, essentially all of them a mirror's own dropped authors rather than bad
  citations. Comparing the cited authors against the *clearing* backend's list instead flagged one,
  and still caught the real case. Every false demotion asks a human to judge named authors, so
  precision is the constraint. Expect the noise to come from data quality -- truncated author rows,
  venue text parsed as an author, name-form differences -- not from bad citations. Record the
  measurement in the CHANGELOG entry, including the rules that were measured and rejected. The DOI,
  year and venue checks were each measured and rejected as automatic demotions and the table is in
  CHANGELOG under 1.19.0; do not revisit one without a fresh measurement on a corpus whose verdicts
  you trust. Choosing among records that have already matched is a different use of those same
  fields, and is what the locator key does.

- Widen the corpus by adding a template nobody has tried, not by adding more of what is there.
  Every extraction fault this repo has found came that way: EMSE and JSS broke five papers on their
  first run because the unnumbered hanging-indent bibliography both journals use had never been
  seen. Two things to get right when it grows. Check for a duplicate arXiv id across venue labels
  before adding -- `2608.27125` arrived twice, as `fse-` and `emse-`, because its comments name
  both, and one paper under two labels double-counts its references in every measurement. And
  record each paper in `~/hallucite/corpus/MANIFEST.csv` (`file`, `venue_note`, `title`) as it is
  pulled; three ICSE papers sat on disk unrecorded for weeks. At this size one bibliography still
  moves a measurement, so re-run whatever a change touches over the whole corpus rather than the
  part that was convenient, and add a synthetic fixture for the new shape
  (`tests/fixtures/make_corpus_fixtures.py`).

- Compare two implementations against an arbiter, not against each other. Holding a new parser to
  an old one's output measures agreement, not correctness, and most of the disagreements are the
  old one's defects. Asking instead which reading a real DBLP record confirms settles each case on
  its merits: it is what showed the new parser at 1480 confirmations against 1399 for the recorded
  one, and what identified the three references where the recording was right.

- Measure precision on fabricated citations built from real records, not on hand-picked cases. Take
  a sample of DBLP publications, cite them correctly, then cite them again with an author appended,
  an author swapped, a title word changed, a given initial contradicted -- the truth is known by
  construction, so a rule's cost and its benefit come from the same run. That harness is what caught
  the phantom-author hole (250 of 250 padded citations confirmed) and what stopped two later
  loosenings that looked like recall wins.

- Build the harness from the population the change touches, not from the population that is
  convenient. The 250-record fabricated-citation set samples titles of three or more tokens, so it could
  not see a `_MIN_TOKENS` of 2 at all (it stayed at 3; the measurement is under 2.0.0); a second
  sample of two-token titles showed three padded citations confirmed, every one through a record
  carrying an `et al.` row, and a third sample of such truncated records showed the lenient tier
  confirming a wholly invented author list 90 times in 90. Neither hole was visible from the sample
  the constraint is stated over. Keep the original set byte-identical, add a set, and score both.

- A throttled backend tells you about the throttle rather than about its own coverage. Semantic
  Scholar looked worth 2 confirmations in 510 when asked without a key, and was worth 24 in 1669
  with one. Never size a backend, or drop it, from a sample where it was refusing. The same mistake
  is possible in the other direction in code: a circuit breaker that gave up after three
  consecutive refusals stopped asking for most of a corpus and cost 27 confirmations, invisibly,
  because `skipped` is not a failure. Raising it to 25 fixed that and left the opposite hole -- an
  *intermittent* throttle never produces 25 refusals in a row, so the breaker never trips and every
  refused reference runs the whole retry ladder. A corpus replay spent three hours in one backend.
  To bound a slow backend, cap the retrying rather than the asking: a refusal costs 31 s with the
  ladder and about a second without it, and capping the asking instead cost five confirmations no
  other backend reaches.

- A backend metered by the day is a wall, not a throttle, and gets the opposite treatment.
  OpenAlex charges a search against a daily budget (a hundred anonymous, a thousand under a free
  key, reset at midnight UTC), so a refusal is the budget gone: `_openalex` does not retry it and
  stops asking after three in a row, where Semantic Scholar's breaker has to survive a burst and
  waits on 25. Size a run to the budget before starting it -- the 567-reference residue was 813
  requests -- and read what a record says it is: OpenAlex holds a journal's review of a book under
  the book's title with the book's author in the byline, so a citation of the book confirms
  through the review, and only the reviews it types `book-review` can be dropped.

- Keep a measurement off the network. It is the same rule for a run and for a results file.
  Re-running the whole corpus online to see the effect of one rule exhausted the Semantic Scholar
  quota in an afternoon and made the run that mattered unusable -- 334 refusals against 6 answers,
  which says nothing about the code -- where asking the 49 references that actually moved took four
  minutes and settled it. A results file recorded across the network likewise bakes in whoever's
  rate limit was in force that afternoon, where `--offline` is reproducible, takes half a minute,
  and covers the 89.4% of confirmations the mirror decides.

- A guard has to be able to fail. Two ways one cannot: asserting a helper the pipeline is free to
  ignore, and pinning a constant by reading it back from the module. `_longest_blank_run` and
  `_page_furniture` were asserted directly while `_gutter` and `_linearize` could ignore them, so
  reverting either extraction fix left the suite green; and `C.eq(x, MODULE.THE_CONSTANT)` passes
  whichever value the constant holds, guarding the shape and not the finding, when the value is what
  was measured. A mutation run found seven fixes revertible with the tests still
  passing, one of them the fix that release had just announced. Assert through the function the
  pipeline calls, pin the number as a literal, and re-run `measure/mutations.py` after adding a
  fix: every entry must fail.

### Prose

- Plans and READMEs describe only the current approach. Do not narrate dropped or superseded
  ideas, or "out of scope" history. After a scope change, rewrite the doc as if the final
  approach were always the plan.

- Check prose you write -- docs, README, PLAN, CHANGELOG, commit and PR messages, the triage
  reports -- against the AI-slop tropes in
  <https://gist.github.com/ossa-ma/f3baa9d25154c33095e22272c631f5a1>. The frequent offenders here:
  "it's not X, it's Y" negative parallelism, filler transitions ("it's worth noting",
  "importantly"), grandiose stakes, vague attributions ("experts say") instead of a named source,
  invented concept labels, and inflated verbs (`use`, not `utilize`/`leverage`). The house dash is
  `--`, two ASCII hyphens, and a literal em dash is not house style: since the 2.0.0 prose pass no
  hallucite-owned file carries one, and the only em dashes left are in the synced vendor tooling
  and in citations quoted as data. Spelling is American throughout (`behavior`, `normalized`,
  `recognized`), which a repo-wide pass fixed on 2026-09-18 after the two forms had drifted to
  roughly even. Those and bold-lead bullets already appear throughout, so do not pile on more than
  the surrounding text uses. Plain, specific, and
  varied beats ornate.
