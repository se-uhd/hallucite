# TODO

## What the DBLP path still refuses that the verifier it replaced confirmed

Measured head to head over the same 2065 citations of `~/hallucite/cases.json`, the same mirror,
DBLP only and nothing else asked, the new path now confirms 1509 against the old path's 1519; over
the whole 55-paper corpus it confirms 2106 against 2009. The CHANGELOG entry carries the numbers,
the rules that were measured and rejected, and the reading of every reference that moved. What is
left on the losing side is deliberate, and each item is a judgment call rather than a defect:

- **Seven name forms.** A real person written two ways: a nickname ("Rick Schlichting" for "Richard
  D. Schlichting", "Tom Zimmermann", "Mike Van Emmerik"), an eszett a PDF rendered as a lowercase b
  ("Weibgerber"), a spelling ("Mohammad" for "Mohammed", "Hosseinpour" for "Hoseinpour"), a
  diacritic pdftotext dropped ("Mara" for "María", "Beroni" for "Beronić"). Each reaches triage as
  `mismatch` carrying the record, where the difference is the first thing a reader sees. The German
  transliteration of an umlaut ("Buettcher" for "Büttcher") is read now, off the side that carries
  the umlaut; every other widening of name pairing is a name an invented author could hide behind,
  so measure any candidate on both corruption harness sets first.
- **Nine real discrepancies**, which the rule exists to flag: five citations naming people who
  did not write the paper (RepoHyper, RepoFuse, BashExplainer, AgentCoder, RepoFormer), and four
  where the citation and the record disagree on one person (a version difference, a typo, a
  truncated surname). Correct as `mismatch`.
- **A record shorter than the citation with no `et al.` row.** DBLP's CoRR record for one
  22-author preprint lists 19 people; the completeness tier cannot see the gap because the record
  does not mark it, so the three missing names refute. Correct by the contract, and a cost a
  triager pays. There is no data-side signal for it short of counting the authors on arXiv.
- **Cited titles that differ from the record's in a content word** ("in-depth study" for
  "In-depth Empirical Study", "state-aware" for "Context-Aware", a dropped "and"). Refused on
  purpose: the triage rules say a human confirms those, not a matcher. The record now travels with
  the reference as `dblp_nearest`, offered only when every cited author is on it, so the human
  sees what to confirm.

Two limits of the lenient tier are recorded rather than open. A record credited to a group rather
than to people (`OpenAI`, `Qwen Team`) has no person to pair against, so a citation of "GPT-4
Technical Report" under two invented names verifies on the title; the arXiv backend, asked by
identifier, is what can catch that, and DBLP cannot. And a truncated record still clears a citation
that pads the names it does list with one it does not, because an unmatched name against a partial
list is absence of evidence by design; what it no longer clears is a citation that pairs with none
of them.

A `?` is not a subtitle mark in `titles_match`, though a colon and a dash are. Measured over the 35
corpus residue titles that carry one, widening it would match four: three were parser cuts, since
fixed, that verify on the whole title, and the fourth pairs Conway's "How do committees invent?"
with an ACM Queue column of that head by another author, a `mismatch` against an unrelated work.
A citation that prints only the question is what the widening would serve, and the corpus has none.

`_MIN_TOKENS` stays at 3. Measured on the whole corpus at 2 it buys nine confirmations, one of
them wrong (Sommerville's textbook "Software engineering" confirmed against his 1983 conference
paper of the same title), and moves six references from `not_found` to `mismatch` against records
of different works that share a generic two-word title ("Github copilot", "Continuous integration",
"Virtual threads"). A false confirmation is the one outcome the tool must not produce, and the
three real two-word titles it would have recovered ("Reproducible containers", "Random Forests",
"Sampling Techniques") reach triage as `skipped`, which the worklist and the report now say in so
many words: 123 of the corpus residue's 788 references were never put to the mirror.

## The anchors

Three recordings sit in `~/hallucite/`, and each answers a different question.

`cases.json` stays frozen: what `hallucinator` returned for the 41-paper corpus, the specification
the modules were written against.

`cases-hallucite.json` is the offline regression anchor: 2857 references from the 55-paper corpus,
recorded from the shipped modules at `3efa4e5` on 2026-09-11, verified against the mirror alone,
replayed in about a minute with no network:

    characterize.py compare ~/hallucite/cases-hallucite.json --impl verifier

It replays with no parse difference and no reference crossing the verified line. The recording it
replaced covered the 41-paper corpus (2081 references) and had been overtaken by the parser fixes
committed after it; re-record this one the same way, offline, after the next change that is meant
to move a verdict, so that a replay reports only what is new.

What it does not answer is which record a verdict points at. `paper_url` is recorded but not
compared -- a replacement consults other backends, so where a reference *lands* is the only
question that survives the substitution -- and the replay hands `check` the parsed fields without
the raw citation, so nothing that reads the entry's text is exercised. A change to the record
shown is confirmed by an `--offline` audit of `~/hallucite/corpus` before and after, diffed per
reference, which is how the cited year and the locator were each measured.

`cases-online.json` is the recording of the four online backends: 2857 references, all backends,
recorded on 2026-09-11 from 17:40 to 19:22 with the parser as of `9f8fd8f`, log in
`cases-online.log`. 2290 verified (DBLP 2070, CrossRef 175, arXiv 16, Semantic Scholar 16, the DOI
resolver 13), 536 not found, 31 mismatch. Semantic Scholar refused 458 of the 583 references it
was asked about, 252 rate-limited and 206 errors, with the key, so every one of the 458 unverified
references that carries a backend failure carries that one and no other.

Replayed with the key unset, 2841 of the 2857 land where they were recorded, and the 16 that move
are exactly the 16 Semantic Scholar confirmed: 14 to `not_found`, two to `mismatch` on the CrossRef
author complaint it had overruled ("Ultra-large-scale systems", "Constructing Grounded Theory"). A
verifier without a key does not ask it, so the replay reports no failures at all. The 16 say what
the backend is worth when it answers: the grounded-theory books, "Building microservices", the EMF
book, the SEI ultra-large-scale-systems report and the GPT-2 report, Holm's 1979 test procedure and
Plotkin's 1970 note, Apache Maven, and six papers the mirror answered `no_match` for, one of them
cited as "Elipse IDE". So the file is an anchor for CrossRef, the DOI resolver and arXiv, whose
statuses replay identically, and a record of one afternoon's Semantic Scholar rather than an anchor
for it: its coverage was not measured, because it mostly refused. The parse half is the parser
before the fixes, so a replay lists the 113 parse differences the CHANGELOG entry describes until
the file is re-recorded; the check half replays the recorded parse and is unaffected. Re-recording
is one corpus replay, an hour and forty minutes without `--mailto`. Do it with `--mailto`, on a
day the quota is fresh, and never two in one afternoon.

## Parser gaps the residue evidence still shows

The six that reading the corpus residue's `skipped` list and its identifier resolutions first
surfaced -- the `URL https://...` title, the `!` and closing-quote cuts, the comma-joined venue,
`VII` and `editors`, the DOI broken after a period -- are fixed and measured in the CHANGELOG
entry. The same reading of the residue still shows:

- Five references in `jss-2605.26146v1` keep a comma-joined field the parser has no name for:
  `, GitHub repository` on three tool citations, `, Working Paper v3.1, Capitol Technology
  Uni-versity`, and a NIST special publication whose corporate author is read as the title. All
  five are grey literature no database holds, so each reaches triage as `not_found` with a title a
  human can read, and nothing verifiable is lost.
- Three DOIs are wrong as printed and now travel whole rather than as a dead front half: a TVCG
  identifier for Wall et al.'s Podium, a TPAMI one for Viering and Loog's learning-curve review, and
  an ACM `10.5555` pseudo-DOI, which doi.org has never resolved. Each is a verified reference, so
  the identifier evidence that would show a reader the dead DOI is not printed for it.

## The corpus is 55 papers and still thin

| venue | papers |
|---|---|
| ICSE | 9 |
| ESEM | 8 |
| EMSE | 7 |
| JSS | 7 |
| FSE | 6 |
| ASE | 6 |
| TSE | 6 |
| TOSEM | 6 |

EMSE and JSS were added on 2026-09-11 and broke five papers on their first run: the unnumbered
hanging-indent author-first bibliography both journals use had never been seen, because the ACM and
IEEE templates of the original 41 papers number their entries, and the one ACM author-year paper
among them passed on the parenthesised years its journal entries carry while silently losing every
two-author entry. That is the argument for widening it again: the faults this repo has found were
all found by adding a template nobody had tried, not by looking harder at the ones already there.

Two things to keep doing when it grows. Check for duplicate arXiv ids across venue labels before
adding -- `2608.27125` arrived twice, as `fse-` and `emse-`, because its comments name both, and
the same paper under two labels double-counts its references in every measurement. And record each
paper in `MANIFEST.tsv` (`file`, `venue_note`, `title`) as it is pulled; three ICSE papers sat on
disk unrecorded for weeks.

The differences a change makes are a handful of references. At 55 papers a single bibliography
still moves them, so re-run whatever a change touches -- the head-to-head against the old DBLP
path, the corruption harness, the author-rule table in CHANGELOG -- against the whole corpus rather
than the part that was convenient.

## Rebuild the measurement baseline

`~/hallucite/corpus` (55 papers: ICSE, FSE, ASE, ESEM, TSE, TOSEM, EMSE and JSS, ACM, IEEE,
Springer and Elsevier templates, with `MANIFEST.tsv`) is the sample. Its *extraction* baseline now
lives in the repo as well, as the synthetic fixtures smoke tier 4j drives, so a clone and CI hold
it too; the old `out/` tree of verdicts, built against a mirror missing 285,000 authors and from
PDFs that are gone, has been deleted rather than left to look like a baseline. A verdict baseline
still needs an audit run over the corpus:

    S2_API_KEY=... mise run audit -- ~/hallucite/corpus --out out-corpus --mailto <you>

Set the key first. Without it Semantic Scholar rate-limits and a chunk of the run comes back
degraded, which is the noise that moved the worklist by one reference between otherwise identical
runs.

## Smaller

- `fetch-dblp-dump` has not been run as the shipped task -- only its scratch equivalent. It needs a
  headed browser and a 1 GB download to prove, or a dry-run mode.
- The DOI, year and venue checks were measured and rejected as automatic demotions; the table is
  in CHANGELOG under 1.19.0. Do not revisit without a fresh measurement on a corpus with
  trustworthy verdicts.
- `titles_match` strips an edition suffix from a record's title (`(2. ed.)`, `, 3rd Edition`) but
  not a `(Reprint)` one. Boehm's *Software Engineering Economics*, cited as the Springer 2002
  reprint, therefore cannot match `books/sp/02/Boehm02a` ("Software Engineering Economics
  (Reprint).") and matches an ICSE 2002 tutorial of the same title instead, which carries Boehm
  among five authors. One corpus reference. It is a title-matching question rather than a
  record-choice one, and any widening gets measured on both corruption sets first.

## Last, once the verifier is replaced

Prose pass, in this order:

1. `/ai-slop:review-repo` over the whole repo -- the Markdown, the comments in the scripts and the
   config, and the commit messages. `/ai-slop:revise` applies the report.
2. Then reread `README.md` and `CLAUDE.md` end to end. Both were revised with the cutover, and
   `/ai-slop:review` has been run over the two of them (17 findings, all applied), but a paragraph
   at a time -- nobody has read either straight through since.

Step 1 is still outstanding: the repo-wide pass covers the script comments and the commit messages,
which the two-file review did not.
