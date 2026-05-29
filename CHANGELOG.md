# Changelog

All notable changes to hallucite are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

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

[1.3.0]: https://github.com/se-uhd/hallucite/releases/tag/hallucite--v1.3.0
[1.2.0]: https://github.com/se-uhd/hallucite/releases/tag/hallucite--v1.2.0
[1.1.0]: https://github.com/se-uhd/hallucite/releases/tag/hallucite--v1.1.0
[1.0.0]: https://github.com/se-uhd/hallucite/releases/tag/hallucite--v1.0.0
