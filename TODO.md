# TODO

## Replace the reference verifier

hallucite calls the external `hallucinator` package at exactly two points, and everything else in
the pipeline is its own. Replacing those two calls removes the dependency, the Rust toolchain, the
`dblp-entity-fix.patch` workaround, and the AGPL component sitting inside an MIT repo.

`VERIFICATION-SPEC.md` is the contract. `skills/hallucite/scripts/characterize.py` is the oracle.

1. **Implement `parse(citation_text, prev_authors)`.** One segmented bibliography entry to
   `{title, authors[], doi?, arxiv_id?}`. Both title conventions (quoted, and the field between
   authors and venue), both author orders, surname particles, hyphenated surnames, DOIs and arXiv
   ids in either form.
2. **Implement `check(references[])`.** DBLP first (`dblp_check.py` already does the offline
   all-candidates title+author match -- promote it from second opinion to primary), then CrossRef,
   then DOI resolution. Those three decide 96.9% of confirmations. Report anything not covered as
   unchecked rather than as `not_found`.
3. **Hold it to the recording.** `characterize.py record ~/hallucite/corpus --out cases.json`, then
   `characterize.py compare cases.json --impl <module>`. Work the divergence list: each entry is
   either a bug or a behaviour to decide on deliberately.
4. **Cut over and delete.** Drop `hallucinator` from `requirements.txt`, delete `install-cli`,
   `install-cli-patched` and `dblp-entity-fix.patch`, and drop the Rust toolchain and the patched
   binary from the README's dependency table.

Keep `dblp-entity-fix.patch` until step 4. It is what makes `mise run build-dblp` produce a mirror
with its accented authors intact, and the audit is wrong in one direction without it.

Do not send anything upstream.

## Rebuild the measurement baseline

`out/` holds 95 papers of verdicts produced against a mirror that was missing 285,000 authors, and
the PDFs it was built from are gone. It is not a usable baseline for judging a detection rule.

`~/hallucite/corpus` (41 papers: ICSE, FSE, ASE, ESEM, TSE, TOSEM, both ACM and IEEE templates, with
`MANIFEST.tsv`) replaces the extraction sample. A verdict baseline still needs an audit run over it:

```sh
S2_API_KEY=... mise run audit -- ~/hallucite/corpus --out out-corpus --mailto <you>
```

Set the key first. Without it Semantic Scholar rate-limits and a chunk of the run comes back
degraded, which is the noise that moved the worklist by one reference between otherwise identical
runs.

## Smaller

- `fetch-dblp-dump` has not been run as the shipped task -- only its scratch equivalent. It needs a
  headed browser and a 1 GB download to prove, or a dry-run mode.
- The DOI, year and venue checks were measured and rejected as automatic demotions (28%, 10% and
  6.7% disagreement against 0.22% for the author-absence check). The fields are surfaced to triage
  instead. Do not revisit without a fresh measurement on a corpus with trustworthy verdicts.

## Last, once the verifier is replaced

Prose pass, in this order:

1. `/ai-slop:review-repo` over the whole repo -- the Markdown, the comments in the scripts and the
   config, and the commit messages. `/ai-slop:revise` applies the report.
2. Then reread `README.md` and `CLAUDE.md` end to end and revise them against what the repo actually
   is by then. Both still describe `hallucinator`, the Rust toolchain, `install-cli-patched`,
   `fetch-dblp-dump` and `dblp-entity-fix.patch`; step 4 above deletes all of it, and the dependency
   table, the setup commands and the whole DBLP-mirror section go with it.

Leave this until last on purpose. Running it earlier reviews prose that the cutover is about to
rewrite.
