# Changelog

All notable changes to hallucite are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

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

[1.4.1]: https://github.com/se-uhd/hallucite/releases/tag/v1.4.1
[1.4.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.4.0
[1.3.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.3.0
[1.2.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.2.0
[1.1.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.1.0
[1.0.0]: https://github.com/se-uhd/hallucite/releases/tag/v1.0.0
