# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] - 2026-05-05

### Added
- **Major Documentation Overhaul**: New professional README with custom branding.
- **Project Assets**: Added high-resolution banner and UI mockups.
- **Community Standards**: Added `CODE_OF_CONDUCT.md` and detailed `CONTRIBUTING.md`.
- **Issue Templates**: Added GitHub Issue Templates for bug reports and feature requests.

### Fixed
- Fixed inconsistencies in repository URLs and command names across documentation.

## [0.1.1] - 2026-05-05

### Fixed
- **CI Stability**: Resolved failing GitHub workflows by fixing ruff formatting and mypy type errors.
- **Unicode Support**: Fixed `UnicodeEncodeError` in `mock_chain.py` demo script for Windows/legacy terminals.
- **Type Safety**: Resolved 14 `mypy` violations across the core library and CLI.
- **OS Compatibility**: Fixed directory casing and path inconsistencies for Linux/macOS runners.

### Changed
- Improved error handling in `StorageEngine` for thread-local connections.
- Optimized `TraceCollector` background worker for non-blocking execution.

## [0.1.0] - 2026-05-03

### Added
- **Core Engine**: Initial release of Trazo execution tracer.
- **Instrumentation**: Sync and async `@trace` decorators and context managers.
- **Storage**: SQLite-backed local storage with WAL mode support.
- **CLI**: Rich terminal interface with `view`, `diff`, and `replay` commands.
- **Web UI**: Local FastAPI dashboard with D3.js DAG visualization.
- **Integrations**: Auto-instrumentation for OpenAI and Ollama.
- **Semantic Diff**: Lightweight n-gram similarity engine for pipeline comparison.

---

[0.1.2]: https://github.com/Vikhram-S/trazo-dev/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Vikhram-S/trazo-dev/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Vikhram-S/trazo-dev/releases/tag/v0.1.0
