# TODO

## What the DBLP path still refuses that the verifier it replaced confirmed

Measured head to head over the same 2065 citations of `~/hallucite/cases.json`, the same mirror,
DBLP only and nothing else asked, the new path now confirms 1509 against the old path's 1519; over
the whole 55-paper corpus it confirms 2070 against 2009. The CHANGELOG entry carries the numbers,
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

`_MIN_TOKENS` stays at 3. Measured on the whole corpus at 2 it buys nine confirmations, one of
them wrong (Sommerville's textbook "Software engineering" confirmed against his 1983 conference
paper of the same title), and moves six references from `not_found` to `mismatch` against records
of different works that share a generic two-word title ("Github copilot", "Continuous integration",
"Virtual threads"). A false confirmation is the one outcome the tool must not produce, and the
three real two-word titles it would have recovered ("Reproducible containers", "Random Forests",
"Sampling Techniques") reach triage as `skipped`, which the worklist and the report now say in so
many words: 123 of the corpus residue's 788 references were never put to the mirror.

## Finish the online anchor

`~/hallucite/cases-hallucite.json` is the regression anchor: 2081 references recorded from the
shipped modules, verified against the offline mirror alone. It replays in 30 seconds with no
network, which is most of what an anchor is for -- a recording made across the network bakes in
whoever's rate limit was in force that afternoon, which is not a property of this code.

    characterize.py compare ~/hallucite/cases-hallucite.json --impl verifier

`~/hallucite/cases.json` stays frozen beside it: what `hallucinator` returned for the same corpus,
which is the specification the modules were written against. `compare` reads which recording it has
been handed and says so, and replays an offline one offline.

The anchor for the four online backends, which decide about 8% of confirmations between them, was
started on 2026-09-11, the first day the Semantic Scholar quota was fresh:

    characterize.py record ~/hallucite/corpus --out ~/hallucite/cases-online.json

with its log at `~/hallucite/cases-online.log`. It is one corpus replay -- about 1500 CrossRef and
700 Semantic Scholar requests, sequential, an hour or more -- and three of those in one afternoon
are what exhausted the quota last time, so do not start a second while one is running. What is
left: if the log does not end in `recorded 2857 cases`, start it once more, with `--mailto <you>`
for CrossRef's polite pool; when it does, replay it and read the movement report before treating it
as an anchor, because a reference whose only backend failure is Semantic Scholar's says something
about that afternoon's throttle and nothing about the code:

    characterize.py compare ~/hallucite/cases-online.json --impl verifier

## Parser gaps the residue evidence surfaced

Reading the corpus residue's `skipped` list and what its identifiers resolve to
(`measure/residue_evidence.py`) turned up entries the parser reads wrongly. None of them is a
verification defect -- each reaches triage as an honest `not_found` -- but every one costs a
human a lookup the tool could have made:

- A Springer entry of the shape `Podman. URL https://podman.io/` parses to the title `URL`
  (eleven references in `emse-2605.21238v1` and `emse-2608.11513v1`). The word before `URL` is
  the title, or the author is.
- A title is cut at an exclamation mark inside it (`Hey! are you committing tangled changes?`
  becomes `Hey!`) and at a closing quote (`"safety automata" - A new specification language ...`
  becomes `safety automata`).
- One JSS paper (`jss-2605.26146v1`) joins the venue to the title with a comma and no `in:`
  (`..., arXiv preprint`, `..., SSRN`, `..., Springer, Berlin, Heidelberg`); about twenty of its
  references carry the venue in the title, and `_TRAILING_IN_VENUE` covers only `, in:`. The
  nearest-title lead and the arXiv resolution both recover the real title, which is how it was
  noticed.
- `VII. Note on regression and inheritance ...` parses to the title `VII`, and
  `M. P. Robillard, ..., and T. Zimmermann, editors. Recommendation Systems ...` to `editors`.
- A DOI the layout broke after a period keeps only its first half (`doi:10.1109/ICET.2017.
  8281704` yields `10.1109/ICET.2017`, which resolves as dead). The rejoin that covers an
  underscore break does not cover a period, and three of the corpus residue's five dead DOIs are
  this shape. Check the far side continues the DOI, as the underscore rejoin does; a four-digit
  year is the entry's own date running on.
- `titles_match` treats a colon or a dash as the subtitle mark but not a question mark, so
  `Does the whole exceed its parts?` reads as a different title from `Does the Whole Exceed its
  Parts? The Effect of AI Explanations ...`. Measure on both corruption harness sets before
  widening it.

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

`out/` holds 95 papers of verdicts produced against a mirror that was missing 285,000 authors, and
the PDFs it was built from are gone. It is not a usable baseline for judging a detection rule.

`~/hallucite/corpus` (55 papers: ICSE, FSE, ASE, ESEM, TSE, TOSEM, EMSE and JSS, ACM, IEEE,
Springer and Elsevier templates, with `MANIFEST.tsv`) replaces the extraction sample. A verdict
baseline still needs an audit run over it:

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
- `authors_absent` is read by `triage.py` and written by nothing since the cutover: the
  `_author_absence_pass` that filled it is gone, and a `mismatch` now carries the matched record's
  authors under `matched` instead. Either derive the absent names from `matched` or drop the field
  and the `SKILL.md` sentence that describes it.

## Last, once the verifier is replaced

Prose pass, in this order:

1. `/ai-slop:review-repo` over the whole repo -- the Markdown, the comments in the scripts and the
   config, and the commit messages. `/ai-slop:revise` applies the report.
2. Then reread `README.md` and `CLAUDE.md` end to end. Both were revised with the cutover, and
   `/ai-slop:review` has been run over the two of them (17 findings, all applied), but a paragraph
   at a time -- nobody has read either straight through since.

Step 1 is still outstanding: the repo-wide pass covers the script comments and the commit messages,
which the two-file review did not.
