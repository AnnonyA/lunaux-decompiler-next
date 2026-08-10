# Changelog

All notable changes are documented here.

## [0.20.0.dev0-stage0] - 2026-08-10

### Added

- Added a per-decompilation `ModuleAnalysis` cache shared by the lifter and structural collectors.
- Added immutable `ProtoAnalysis` records for decoded instructions, CFG analysis, SSA, and lexical scope analysis.
- Added lazy symbol-recovery caching keyed by the symbol-analysis configuration.
- Added regression coverage that verifies shared analysis reuse across main and child protos without changing reconstructed source.

### Changed

- Class recovery, contextual-function recovery, Roblox recovery, and nested function lifting now reuse the same analyzed proto state instead of rebuilding decode/CFG/SSA/scope data independently.
- On the 2,304-case public corpus, core analysis is reduced to one decode, CFG, SSA, and scope build per proto: `3,456` each.
- Symbol recovery is reduced to `3,200` distinct builds on the same corpus.

### Validation

Validated on commit `9cf5201c22e3372c887157a3cfe5682ac4ae49d8`:

- CI #448: passed.
- LunaUX 0.18 Public Benchmark #121: passed.
- Semantics: `2304/2304`.
- Execution: `100%`.
- Syntax: `100%`.
- Recompilation: `100%`.
- Stability: `100%`.
- Zero fallback: `100%`.
- Medal-compatible semantic gate: `384/384`.
- Readability median: `86.0977`, unchanged by Stage 0.
- Semantic failures: `0`.
- Timeouts: `0`.

Stage 0 is intentionally output-neutral. It removes repeated analysis work and establishes one shared analysis foundation for later structural recovery passes.

### Next

- Stage 2: separate `SETLIST` semantic array indices from legacy emission offsets and complete affected table-initializer recovery without regressing v11 behavior.

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
