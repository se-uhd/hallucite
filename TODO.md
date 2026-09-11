# TODO

## What the DBLP path still refuses that the verifier it replaced confirmed

Measured head to head over the same 2065 citations of `~/hallucite/cases.json`, the same mirror,
DBLP only and nothing else asked, the new path now confirms 1508 against the old path's 1519; over
the whole 55-paper corpus it confirms 2068 against 2009. The CHANGELOG entry carries the numbers,
the rules that were measured and rejected, and the reading of every reference that moved. What is
left on the losing side is deliberate, and each item is a judgment call rather than a defect:

- **Nine name forms.** A real person written two ways: a nickname ("Rick Schlichting" for "Richard
  D. Schlichting", "Tom Zimmermann", "Mike Van Emmerik"), a transliteration ("Buettcher" for
  "Büttcher", "Juergens" for "Jürgens"), an eszett a PDF rendered as a lowercase b ("Weibgerber"),
  a spelling ("Mohammad" for "Mohammed", "Hosseinpour" for "Hoseinpour"), a diacritic pdftotext
  dropped ("Mara" for "María", "Beroni" for "Beronić"). Each reaches triage as `mismatch` carrying
  the record, where the difference is the first thing a reader sees. The one rule that looks safe
  is the German transliteration reading (`ue`, `oe`, `ae` for the umlaut) and it is worth two
  references; measure it on the corruption harness before adding it, because every widening of
  name pairing is a name an invented author could hide behind.
- **Nine real discrepancies**, which the rule exists to flag: five citations naming people who
  did not write the paper (RepoHyper, RepoFuse, BashExplainer, AgentCoder, RepoFormer), and four
  where the citation and the record disagree on one person (a version difference, a typo, a
  truncated surname). Correct as `mismatch`.
- **A record shorter than the citation with no `et al.` row.** DBLP's CoRR record for one
  22-author preprint lists 19 people; the completeness tier cannot see the gap because the record
  does not mark it, so the three missing names refute. Correct by the contract, and a cost a
  triager pays. There is no data-side signal for it short of counting the authors on arXiv.
- **Fifteen cited titles that differ from the record's in a content word** ("in-depth study" for
  "In-depth Empirical Study", "state-aware" for "Context-Aware", a dropped "and"). Refused on
  purpose: the triage rules say a human confirms those, not a matcher.

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
"Sampling Techniques") reach triage as `skipped`, which says truthfully that the mirror was not
asked.

## Record an online anchor when the quota is fresh

`~/hallucite/cases-hallucite.json` is the regression anchor: 2081 references recorded from the
shipped modules, verified against the offline mirror alone. It replays in 30 seconds with no
network, which is most of what an anchor is for -- a recording made across the network bakes in
whoever's rate limit was in force that afternoon, which is not a property of this code.

    characterize.py compare ~/hallucite/cases-hallucite.json --impl verifier

`~/hallucite/cases.json` stays frozen beside it: what `hallucinator` returned for the same corpus,
which is the specification the modules were written against. `compare` reads which recording it has
been handed and says so, and replays an offline one offline.

What is missing is an anchor for the four online backends, which decide about 8% of confirmations
between them. Record one with `--s2-api-key` on a day the Semantic Scholar quota has not been spent
-- three full corpus replays in one afternoon exhausted it, and the recording that came out of that
says more about the throttle than about the code:

    characterize.py record ~/hallucite/corpus --out ~/hallucite/cases-online.json --mailto <you>

## Put the evidence hallucite already has in front of the triager

Three things the audit knows and throws away. **The numbers below came from the 95-paper residue
that the next section declares unusable, and the PDFs behind it are gone, so re-measure each on
`~/hallucite/corpus` before building against it.** They are kept only to say what shape the
evidence took.

- **What the cited identifier resolves to.** A dead identifier and one that resolves to a
  *different* title point at opposite verdicts, and triage cannot tell them apart today.
  `verifier` already fills `doi_info` and `arxiv_info` with the resolved title; `triage.py` reads
  neither. On the old residue, most of the identifiers that resolved resolved to another work.
- **The mirror's nearest title, gated on authorship.** A sibling of `record_context` that runs only
  where `title_candidates` found nothing, offers a record within two word-level edits, and requires
  every cited person to be on it. On the old residue the gate was what made it precise: ungated, a
  third of the extra hits were different works, several of which would have argued a correct
  citation into a "citation error" verdict.
- **That the mirror was asked at all.** A `not_found` reads the same whether the mirror came back
  empty or was never asked -- `queryable()` returns false for a short title, and `_dblp` reports
  `skipped`, which no report surfaces. That is the distinction `SKILL.md`'s first question turns
  on, and what separates `likely-hallucinated` from `unclear`. Seven corpus references sit at
  `skipped` for a two-word title, and no report says so.

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

`~/hallucite/corpus` (41 papers: ICSE, FSE, ASE, ESEM, TSE, TOSEM, both ACM and IEEE templates, with
`MANIFEST.tsv`) replaces the extraction sample. A verdict baseline still needs an audit run over it:

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

## Last, once the verifier is replaced

Prose pass, in this order:

1. `/ai-slop:review-repo` over the whole repo -- the Markdown, the comments in the scripts and the
   config, and the commit messages. `/ai-slop:revise` applies the report.
2. Then reread `README.md` and `CLAUDE.md` end to end. Both were revised with the cutover, and
   `/ai-slop:review` has been run over the two of them (17 findings, all applied), but a paragraph
   at a time -- nobody has read either straight through since.

Step 1 is still outstanding: the repo-wide pass covers the script comments and the commit messages,
which the two-file review did not.
