# Claude Code guidance for hallucite

## What this is

`hallucite` finds hallucinated (fabricated) references in academic paper PDF files. Stages 1 and 2
(extract, then verify against DBLP, CrossRef, arXiv, and others) use no LLM; verification queries
the online databases unless `--offline` restricts it to the offline DBLP mirror.
Stage 3 (triage the database-unverified residue) is the LLM step, done interactively by you. See
`PLAN.md` for the design and architecture, `README.md` for commands, `TODO.md` for what is in
flight.

Extraction, parsing, verification and the DBLP ingest are all hallucite's own and use only the
standard library: `pdf_references.py`, `reference_parser.py`, `verifier.py`, `dblp_check.py`,
`build_dblp.py`. `VERIFICATION-SPEC.md` is the contract the parse and check halves meet, and
`characterize.py` holds them to a recording of the external `hallucinator` package they replaced.
That package is AGPL-3.0-or-later and this repo is MIT; it is no longer a dependency of anything
the audit runs, and no code was copied across -- the modules were written against a black-box
recording. Nothing imports it any more, `characterize.py record` included: a new recording is made
from hallucite's own modules.

One repo, two roles: it is the runnable project (mise tasks) and an installable plugin for Claude
Code and Codex CLI. Claude Code uses `.claude-plugin/plugin.json` plus
`.claude-plugin/marketplace.json` (name `hallucite`, plugin `source: "./"`). Codex CLI uses
`.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `plugins/hallucite -> ..`, and
`.agents/skills/hallucite -> ../../skills/hallucite`. The pipeline scripts live once in
`skills/hallucite/scripts/`, used by mise and by the bundled skill (`skills/hallucite/SKILL.md`).
No separate plugin repo, no submodule.

## Running things

- The bundled skill drives the pipeline through `skills/hallucite/scripts/run.sh`, the single
  entry point (`check-env | audit | triage | lint | python`). It resolves the wrapper from a Claude
  Code plugin install, a Codex repo-local skill shim, a direct repo clone, the Claude Code plugin
  cache, or the Codex plugin cache. The wrapper resolves a Python 3.10+ with `sqlite3`, never relying on a bare
  `python`/`uv`/`mise` being on the plugin shell's PATH (the failure that made the plugin silently
  un-runnable). There is nothing to install. The wrapper fails loud with a `HALLUCITE_BOOTSTRAP_FAILED:`
  sentinel and a non-zero exit, and its probe reads the interpreter's *output* rather than its exit
  status, because `/bin/echo` accepts `-c` and exits 0. `$HALLUCITE_PYTHON` pins an interpreter.
  `run.sh check-env` is the preflight.
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
  `fetch-dblp-dump` gets the dump with a real browser when the bot check is up.
- Measuring a change: `skills/hallucite/scripts/measure/`. `extraction_census.py` tabulates what
  every corpus paper extracts and what moved against a baseline; `corruptions.py` builds the
  corruption harness once and scores an implementation against it; `head_to_head.py` scores the
  old and new parser and DBLP check over the recorded cases or the corpus, offline by
  construction; `mutations.py` reverts one fix at a time and requires the suite to fail, and does
  so in the working tree, which it owns until it finishes: no other measurement, and no edit to any
  tracked file, Markdown included. The suite reads the CHANGELOG, the manifests and `SKILL.md` as
  well as the modules reverted, so an edit landing inside a run is read half-written and fails a
  check indistinguishable from the revert's -- which reports an unguarded fix as guarded. It
  fingerprints the tracked tree between entries and stops if anything moved; work in a snapshot
  (`git ls-files -z | xargs -0 tar cf -`) instead. The
  built harness sets live with the other anchors in `~/hallucite/` (`corruptions.json`,
  `corruptions-truncated.json`) and are scored, never rebuilt, because a rebuild on a newer dump
  samples different records. `--scripts DIR` on the scorers imports a snapshot of the modules, so
  a before-and-after needs no stash. `residue_evidence.py` reads an `--offline` audit's output and
  prints, per residue reference, the backends never asked, the mirror's nearest title ungated and
  gated, and (its one network step, DOI and arXiv only, a few hundred requests) what each cited
  identifier resolves to.
- Stage 1/2 driver: `skills/hallucite/scripts/audit_references.py` (segments each reference via
  `pdf_references.py`, parses it with `reference_parser.py`, then runs `verifier.check`). The
  target is 0 unparsed references.
- Stage 3: `triage.py worklist | status | record | report`. Verdicts persist in
  `out/triage_verdicts.json` (keyed `paper_id:number`, resumable), so triage can run on finished
  papers while the audit is still going: `worklist --pending` lists only un-recorded references and
  `status` shows per-paper progress. To fan out, give each worker its own `worklist --paper <id>`
  slice (exact id match, errors on an unknown id) so it never self-filters the shared worklist and
  grabs the wrong paper (`paper6` vs `paper66`); `record` takes an `fcntl` lock on the verdicts file
  so concurrent workers don't lose updates. `record --signals '<json>'` carries the structured
  fabrication signals and enforces the title-first rule (`partial-match` needs `title_match=yes`+
  `matched_title` or `na`; `likely-hallucinated` needs `title_match=no`). `report` writes the
  per-paper checks, the `potential-hallucinations.md` rollup (severity table + a **Desk-reject
  candidates** section keyed on `is_fabrication`), and `verify-<paper>.md` sheets, and auto-lints
  every file it writes. A worklist entry, the per-paper check and the sheet all carry what the
  audit knew about the reference: `skipped_dbs` (backends never asked -- a `not_found` with the
  mirror in that list was never put to it), `matched`, `dblp_record`, `dblp_nearest` (the mirror's
  nearest title, offered only with every cited author on it) and `identifiers` (what each cited
  DOI or arXiv id resolves to, and whether that is the cited title).

## Triage conventions (Stage 3)

- Never fabricate a verdict. A verdict may rest only on a Stage 1+2 `db_verification` record the
  audit wrote or Stage 3 web evidence you actually gathered -- never on reading the `.bib`/`.bbl`/PDF
  by eye. If `run.sh` exits non-zero or prints `HALLUCITE_BOOTSTRAP_FAILED:`, or output starts
  coming back empty, stop and report it verbatim; "the tool would not run" is the correct outcome,
  not a hand-written report. This rule lives in full in `SKILL.md` ("Stop conditions"); smoke
  tier 1 asserts SKILL.md carries it, and tier 1b guards the fail-loud `run.sh` contract the rule
  keys on.
- Investigate with parallel web queries; resolve DOIs via `api.crossref.org/works/<doi>`. If a
  narrow query (title + author) finds nothing, broaden to the bare title (unquoted) and screen the
  results before judging; obscure/predatory venues are poorly indexed, so "not found" on a narrow
  query is not fabrication evidence.
- Classify title-first, and keep two questions separate: (1) does a publication bearing the cited
  *title* exist (matching on title, not on a same-authors/same-venue paper with a different title)?
  (2) only if yes, do the metadata fields match? Match the title on meaning: formatting, subtitle,
  hyphen/spacing/spelling/OCR differences are the same title; a wrong content word counts as found
  only when a resolving DOI or an exact author+venue+year match pins it to one real publication.
  `partial-match` requires question 1 to be *yes* -- a real, locatable work with the cited title but
  a slipped field (wrong year/DOI digit/venue/co-author). If no work bears the cited title, the
  cited work does not exist: `likely-hallucinated`
  (thorough search + fabrication signals) or `unclear`. Never rescue a non-existent title to
  `partial-match` just because the authors or venue match some *other* real paper -- that conflation
  is what misfiled a fabricated reference as a citation error and forced a long correction.
- Honest human mistakes do not invent titles; they slip a metadata field on a real, findable work.
  Independent fabrication signals: **(T) no publication has the cited title** (decisive); **(A)** an
  author set/order that never co-published, or initials-only generic authors; **(V)** an impossible
  or non-existent venue/year/volume (e.g. a proceedings entry + page range that do not exist, a
  defunct journal); **(D)** a dead/mismatched DOI or placeholder arXiv id (`2310.XXXX`). A
  non-existent title (T) is itself a fabrication and grounds to desk-reject -- even with real
  authors and a real venue (the hardest case); A/V/D strengthen it but are not required. The non-existent title is
  what `is_fabrication` keys on.
- Categories: `real-published`, `real-grey-literature`, `real-preprint-or-unpublished` (low);
  `partial-match` (citation error, medium); `likely-hallucinated` (high); `unclear`.
- Do not push borderline cases into `real-*` to make a report look clean. `unclear` is a valid,
  useful verdict, and a "hallucinated" call against named authors is serious: flag it for review,
  do not accuse. Equally, do not downgrade a fabricated title to a citation error to avoid the
  accusation -- record what the evidence shows.

## Conventions

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
- Verification `status` and `db_name` strings are `verifier`'s, and `VERIFICATION-SPEC.md` is
  where they are fixed; treat them as a contract that can drift. Define "needs triage" by negation (`status != "verified"`),
  never by an allow-list of failure strings, and keep the invariant that every reference is
  verified, unverified, or pending (none silently dropped). Validate any hard-coded backend name
  against what `verifier` actually emits: `run_smoke.py` covers the status strings, and the
  audit validates backend names at run time -- online runs warn about configured names that never
  appear (`DEFAULT_ONLINE_DBS`); `--offline` runs warn about live backends that are not known-local
  (`KNOWN_LOCAL_DBS`). A silent name mismatch is what caused both the `mismatch` and the
  `DOI Resolver` bugs. `VERIFICATION-SPEC.md` states the vocabulary a verifier has to emit;
  `characterize.py` records the current behaviour on real references and holds a replacement to it.
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
  record each paper in `~/hallucite/corpus/MANIFEST.tsv` (`file`, `venue_note`, `title`) as it is
  pulled; three ICSE papers sat on disk unrecorded for weeks. At this size one bibliography still
  moves a measurement, so re-run whatever a change touches over the whole corpus rather than the
  part that was convenient, and add a synthetic fixture for the new shape
  (`tests/fixtures/make_corpus_fixtures.py`).
- Prefer a check the input already supports over one you have to tune. A numbered bibliography
  numbers itself consecutively, so a printed `[N]` that no extracted reference carries is one that
  never reached verification, and nothing downstream can report a reference that never arrived.
  That invariant surfaced all three of the extraction faults fixed in `_gutter`, `_linearize` and
  `_segment`; `extract_references` reports the gaps and the audit warns about them. The printed
  numbering cost nothing to check and needed no threshold. Look for the same shape elsewhere
  before writing a detector.
- Compare two implementations against an arbiter, not against each other. Holding a new parser to
  an old one's output measures agreement, not correctness, and most of the disagreements are the
  old one's defects. Asking instead which reading a real DBLP record confirms settles each case on
  its merits: it is what showed the new parser at 1480 confirmations against 1399 for the recorded
  one, and what identified the three references where the recording was right.
- Measure precision on corruptions built from real records, not on hand-picked cases. Take a
  sample of DBLP publications, cite them correctly, then cite them again with an author appended,
  an author swapped, a title word changed, a given initial contradicted -- the truth is known by
  construction, so a rule's cost and its benefit come from the same run. That harness is what
  caught the phantom-author hole (250 of 250 padded citations confirmed) and what stopped two
  later loosenings that looked like recall wins.
- Build the harness from the population the change touches, not from the population that is
  convenient. The 250-record corruption harness samples titles of three or more tokens, so it
  could not see `_MIN_TOKENS = 2` at all; a second sample of two-token titles showed three padded
  citations confirmed, every one through a record carrying an `et al.` row, and a third sample of
  such truncated records showed the lenient tier confirming a wholly invented author list 90 times
  in 90. Neither hole was visible from the sample the constraint is stated over. Keep the original
  set byte-identical, add a set, and score both.
- A lenient rule needs a floor. A record that cannot refute must still be able to *confirm*
  something: the people a truncated record lists have to account for at least one cited name, or
  the tier is a wildcard that clears any author list on any title one incomplete record shares.
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
- A threshold expressed as a proportion behaves differently on small inputs. `_gutter` tolerated a
  fraction of lines crossing the column band, so one running head was 1% of a full page and 3% of a
  short final one -- the same head, passing on one page and losing the column split on the other.
  Where a rule has to survive a fixed amount of noise, count the noise.
- Decide from the data in hand, not from a name. Hard-coding DBLP out of the complete-author set
  because the mirror was broken survived the mirror being repaired, and a reference with two
  invented authors verified again. `mirror_authors_complete` and `record_authors_complete` decide
  per run and per record instead.
- Plans and READMEs describe only the current approach. Do not narrate dropped or superseded
  ideas, or "out of scope" history. After a scope change, rewrite the doc as if the final
  approach were always the plan.
- Check prose you write -- docs, README, PLAN, CHANGELOG, commit and PR messages, the triage
  reports -- against the AI-slop tropes in
  <https://gist.github.com/ossa-ma/f3baa9d25154c33095e22272c631f5a1>. The frequent offenders here:
  "it's not X, it's Y" negative parallelism, filler transitions ("it's worth noting",
  "importantly"), grandiose stakes, vague attributions ("experts say") instead of a named source,
  invented concept labels, and inflated verbs (`use`, not `utilize`/`leverage`). Em dashes (`--`)
  and bold-lead bullets already appear in these files; do not pile on more than the surrounding
  text uses. Plain, specific, and varied beats ornate.
- Assert a test through the function the pipeline calls. `_longest_blank_run` and `_page_furniture`
  were both asserted directly while `_gutter` and `_linearize` were free to ignore them, so
  reverting either extraction fix left the suite green.
- Pin a measured constant as a literal. `C.eq(x, MODULE.THE_CONSTANT)` passes whichever value
  the constant holds, which guards the shape and not the finding -- and the value is what somebody
  measured. A mutation run (revert one fix, run the suite) found seven fixes that could be undone
  with the tests still passing, including the one the release had just announced. Re-run it after
  adding a fix: `for each fix: revert it; python .../run_smoke.py` should fail every time.
- Probe an interpreter by what it prints. `/bin/echo -c '...'` exits 0 without running anything,
  and `run.sh` accepted it as a Python.
- Measure a change on the population it changes. Re-running the whole corpus through the network to
  see the effect of one rule exhausted the Semantic Scholar quota in an afternoon and made the run
  that mattered unusable -- 334 refusals against 6 answers, which says nothing about the code.
  Asking the 49 references that actually moved took four minutes and settled it.
- Record an anchor offline. One made across the network bakes in whoever's rate limit was in force
  that afternoon, where `--offline` is reproducible, takes half a minute, and covers the 91.5% of
  confirmations the mirror decides.
- Keep Markdown lint-clean: `mise run lint-md` (`MD_FIX=1` to auto-fix). The vendored PyMarkdown
  in `skills/hallucite/scripts/` is synced from se-uhd/pymarkdown-skill; do not hand-edit
  `_vendor/`, `lint_markdown.py`, or `check_baseline.py` (re-sync instead). The hallucite-owned
  files are `schema_checks.py` and `lint_markdown.yaml`.
