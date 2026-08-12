# Changelog

All notable changes are documented here.

## [0.21.0.dev0] - 2026-08-12

### New identity

- Renamed the user-facing project and primary command to **ByteWeft**.
- Added a provenance header with the ByteWeft version, UTC timestamp, bytecode
  version, and type-data version to CLI and API decompilations.
- Added `--no-header` and `IncludeHeader=false` for deterministic consumers, plus
  `SOURCE_DATE_EPOCH` support for reproducible timestamps.
- Kept the `lunaux` Python namespace, CLI alias, and `LUNAUX_*` environment
  variables as compatibility interfaces.

### Semantic and structural recovery

- Fixed symbol recovery for decoded instructions that are unreachable and therefore
  intentionally absent from the SSA instruction map.
- Corrected `FORGPREP*` successor semantics so generic-loop bodies consume the
  values defined by `FORGLOOP`, rather than stale physical-register lifetimes.
- Fixed overlapping legacy/advanced loop ownership and recovered safe terminal
  single-break loops as `repeat ... until` without duplicating loop regions.
- Preserved captured phi names and created a fresh lexical binding when a physical
  register is reused after its proven structural lifetime.
- Recovered mixed terminal short-circuit guards while preserving the exact branch
  edge represented by each condition.
- Extended transactional table ownership to call-preparation values used by open
  `SETLIST`, while preserving call barriers and flushing nested pending tables before
  observable uses.

### Real-module impact

- Removes the invalid global assignment produced when a loop register was reused for
  a later `math.clamp` result.
- Removes a duplicated infinite-loop wrapper around the missile-rise interpolation
  loop.
- Preserves the early validation guard as a direct `not a or not b or not c` test.
- Keeps call-valued GUI clones inside their proven table constructor and preserves
  child-before-parent table initialization order.

The portable backend remains deterministic. The timestamped provenance line is a
presentation-layer feature and can be disabled without changing the recovered body.

## [0.20.0.dev0-stage7] - 2026-08-11

### Added

- Added shared `CallResultShape` semantics for fixed-zero, fixed-one, fixed-many and open CALL results, including exact FASTCALL result-phi handling.
- Added transactional `TableBuildPlan` ownership for call-valued and nested table construction with explicit escape, dependency, ordering and MULTRET rejection reasons.
- Added a real serialized Luau v9 source-fidelity regression fixture with byte-level SHA verification and structural output assertions.
- Added stable dot-field function declaration emission through `ProtoEmissionPlan` while keeping colon-method proof separate.
- Added high-confidence returned-module-root naming, exact operand-valued short-circuit recovery, serialized parameter-type preservation and unused iterator `_` naming.
- Added deterministic recursive pretty-printing for large/complex `TableExpr` values without sorting or reordering semantic evaluation.

### Changed

- Fixed constructor recovery so an observable CALL no longer forces a table flush when its exact SSA result is itself the next proven constructor operation.
- Fixed false MULTRET materialization in table construction by sharing CALL result cardinality with SETLIST/open-tail ownership.
- Extended exact-SSA folding for one-use compiler temporaries while preserving debug lifetimes, repeated mutable-read snapshots and effect barriers.
- Module field closures with stable ownership can now emit as `function module.name(...)` instead of anonymous assignment forms.
- Value-position `and`/`or` recovery now preserves Luau operand-return semantics and conditional evaluation.
- Large nested constructors now render structurally across multiple lines instead of as pathological single-line expressions.

### Real-world source fidelity

On the pinned v9 regression module:

- synthetic temporaries: `148 → 4`;
- constructor temporaries: `138 → 0`;
- false MULTRET annotations: `33 → 0`;
- anonymous module-field functions: `5 → 0`;
- dot function declarations: `0 → 5`;
- numbered `data*` / `color*` temporaries: `0` final;
- final table constructors: `96`;
- CALL expressions directly owned by tables: `47`;
- final output is byte-identical across repeated decompilations.

### Corpus / readability

- Semantic corpus: `2304/2304`; Medal-compatible: `384/384`; all execution/syntax/recompilation/stability/zero-fallback gates remain `100%`.
- Changed outputs: `1696/2304` across arithmetic, boolean, closure, conditional, loops, methods, MULTRET, recursion, strings and table families.
- Global median readability: `92.42905 → 93.45525`.
- Paired readability: `1056` wins, `496` losses, `752` ties. Several lexical-score losses correspond to human simplifications such as direct return-call folding and unused `_` bindings.
- Deterministic corpus digest: `b2a8325981a45828cc4a687f87840529b2b15de518478f13602f5e444f64a3ac`.

### Validation

- pytest: `248 passed`, `0 failed`;
- Ruff: `0` failures;
- mypy: `0` issues across `67` source files;
- `git diff --check`: clean;
- clean-base `git apply --check`: clean;
- Stage 0 shared analysis unchanged: decode/CFG/SSA/scope `3456` each, symbols `2880`.

### Performance / limitations

- Host wall measurements improved materially in the recorded run, but CPU increased from `26.969 s` to `29.406 s`; no unsupported net-speedup claim is made because the host was noisy.
- Generic statement emission remains line-oriented; a complete statement AST is still future architecture work.
- Repeated mutable table reads, true open MULTRET outside legal tail ownership, escaping tables and ambiguous/cross-block constructor ownership remain deliberately conservative.

## [0.20.0.dev0-stage56] - 2026-08-10

### Added

- Added `ProtoEmissionPlan`, a shared SSA-owned plan for closure/proto emission, alias ownership, capture/upvalue provenance, recursion groups, method evidence and inline-consumer decisions.
- Added conservative direct-recursion recovery with human `local function` declarations when lexical visibility is proven.
- Added mutual-recursion SCC handling with explicit predeclarations when declaration sugar would change visibility.
- Added proof-based method declaration recovery, including colon syntax only when the receiver, field and call evidence agree.
- Added `CanonicalCFGPlan` as a common region-planning authority for loops, short-circuit boolean chains, phi diamonds, branch regions, recovered state machines and irreducible fallbacks.
- Added deterministic `SemanticNamePlan` naming based on debug bindings, function/parameter roles, contextual evidence and stable fallback names.
- Added focused positive and negative regression suites for proto emission and canonical CFG planning.

### Changed

- Closure ownership now follows exact `SSAValue` identity instead of physical-register history, including MOVE aliases and repeated register lifetimes.
- CallFrame ownership is reused by proto planning instead of maintaining a competing call/closure decision path.
- Recursive closures can now emit as named local functions, while unsafe recursion groups remain explicitly predeclared.
- Proven table-field functions can emit as methods without using rendered source strings as semantic identity.
- Existing callback, contextual-function, class, MULTRET, table-initializer and ReadModifyWrite recovery now share the Stage 5/6 planning infrastructure.
- CFG structuring now records canonical region evidence using existing dominator/postdominator, loop, phi, short-circuit and state-machine analysis.
- Variable/function naming is more deterministic and role-aware while preserving valid debug metadata as the strongest evidence.
- Generic `elseif`/guard source emission remains conservative where AST region-closure ownership is not yet complete.

### Readability

- Changed `552/2304` deterministic corpus outputs: `176` v3, `176` v6 and `200` v11.
- Global median readability: `90.7895 → 92.12` after Stage 5 and `92.42905` final.
- Paired comparison: `544` wins, `8` losses and `1752` ties.
- The eight scorer losses remove genuine unnecessary materialization and did not produce semantic regressions.

### Performance

Warmed decompiler-only measurements:

- Stage 3+4 base: `32.348 s`, `71.23 cases/s`.
- Stage 5: `32.568 s`, `70.74 cases/s`.
- Final Stage 5+6: `21.509 s`, `107.12 cases/s`.
- Shared Stage 0 construction remains `3456` decode / CFG / SSA / scope analyses; symbol recovery is `2880` builds on the final corpus.

### Validation

Validated locally against the Stage 3+4 code base `a96259eec6fe07b9b181c15cb3317ce831c414a6` before publication:

- pytest: `244 passed`.
- Ruff: `0` errors.
- mypy: `0` errors across `67` source files.
- `git diff --check`: passed.
- `git apply --check`: passed for the final patch against its recorded base.
- Semantic corpus: `2304/2304`.
- Medal-compatible semantic gate: `384/384`.
- Execution: `100%`.
- Syntax: `100%`.
- Recompilation: `100%`.
- Stability: `100%`.
- Zero fallback: `100%`.
- Semantic failures: `0`.
- Timeouts: `0`.
- Deterministic digest: `81aa1f1ed69d2f209813e802d14d7160b545829b1881c3a8d20f9e0147fdc598`.

### Known limitation

- Canonical CFG planning now identifies generic `elseif`/early-guard regions, but source emission intentionally stays conservative until the AST emitter can own region closure boundaries end-to-end. This prevents pretty-printing from changing control-flow semantics.

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
