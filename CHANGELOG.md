# Changelog

All notable changes are documented here.

## [0.1.0] - 2026-08-05

### Added

- Pluggable decompiler backend protocol.
- Compatibility adapter for a `luna` native module.
- Direct Typer CLI for decompilation and disassembly.
- Versioned FastAPI service with structured errors.
- Input-size, filename, and output-size validation.
- Conservative raw/Base64 input handling.
- Cross-platform CI, tests, architecture documentation, and security policy.

### Changed

- Replaced the self-updating installer model with standard Python packaging.
- Removed the CLI dependency on a running HTTP server and external `curl`.
- Disabled CORS by default.
