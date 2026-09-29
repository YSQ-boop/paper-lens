# Changelog

Notable changes are documented here. The project follows Semantic Versioning.

## [Unreleased]

### Added

- Deterministic validation and a public schema for reviewed online evaluation summaries.

## [0.3.0] - 2026-09-29

> Release gate: the `v0.3.0` tag remains pending until the complete online suite is run and manually reviewed; no model-quality score is claimed yet.

### Added

- Formula/table grounding checks with actionable line and block diagnostics, including English and Chinese regression fixtures.
- Safe multi-file arXiv source resolution for relative `\input` and `\include` references, with missing/cycle warnings.

### Changed

- Source figure matching now prefers normalized archive-relative paths and only uses a unique basename as a fallback.
- Evaluation summaries record selected cases, evaluation dates, and aggregated token usage under a validated public contract.

## [0.2.0] - 2026-08-24

### Added

- Optional end-to-end Codex evaluation harness and local negative fixtures.
- Cross-platform CI, release packaging, and manual maintainer review workflow.
- Public governance, security, roadmap, impact, and application-readiness documents.

### Changed

- Hardened bounded network downloads and arXiv archive processing.
- Normalized source figures to PNG before report use.
- Expanded plugin metadata and public installation documentation.

## [0.1.0] - 2026-08-17

### Added

- Initial Paper Lens skill, deterministic preparation pipeline, quick/deep report contract, and unit tests.

[Unreleased]: https://github.com/YSQ-boop/paper-lens/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/YSQ-boop/paper-lens/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/YSQ-boop/paper-lens/compare/75e4dd4...v0.2.0
[0.1.0]: https://github.com/YSQ-boop/paper-lens/tree/75e4dd4
