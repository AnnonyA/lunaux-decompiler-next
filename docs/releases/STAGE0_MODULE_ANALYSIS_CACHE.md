# Stage 0 — Shared Module Analysis Cache

Stage 0 is the first performance-focused milestone in the current LunaUX structural recovery roadmap. It does not intentionally change generated Luau. Instead, it makes the decompiler analyze each proto once per decompilation and share that result across consumers.

## What changed

The decompiler now builds one shared `ModuleAnalysis` for a module and exposes per-proto `ProtoAnalysis` records containing:

- decoded instructions;
- control-flow analysis;
- SSA;
- lexical scope analysis.

Symbol recovery is cached lazily by its analysis configuration. Class recovery, contextual-function recovery, Roblox recovery, and nested lifters reuse the same proto analysis rather than rebuilding the same data independently.

## Why this matters

Before Stage 0, multiple structural collectors independently decoded bytecode and rebuilt CFG/SSA state for the same proto. That duplicated expensive work and made later proof-oriented passes harder to centralize.

On the 2,304-case public corpus, Stage 0 reduces core analysis to exactly one build per proto:

| Analysis | Stage 0 count |
| --- | ---: |
| decoded proto instruction stream | 3,456 |
| CFG analysis | 3,456 |
| SSA program | 3,456 |
| scope tree | 3,456 |
| symbol recovery configurations | 3,200 |

The corpus contains 3,456 protos across 2,304 modules.

## Output compatibility

Stage 0 is deliberately output-neutral. The 2,304 reconstructed outputs were verified byte-for-byte against the pre-Stage-0 baseline during development.

The public GitHub validation on commit `9cf5201c22e3372c887157a3cfe5682ac4ae49d8` also passed the full release gate:

| Gate | Result |
| --- | ---: |
| semantics | 2304/2304 |
| execution | 100% |
| syntax | 100% |
| recompilation | 100% |
| stability | 100% |
| zero fallback | 100% |
| Medal-compatible semantics | 384/384 |
| readability median | 86.0977 |
| semantic failures | 0 |
| timeouts | 0 |

CI #448 and LunaUX 0.18 Public Benchmark #121 both passed on that exact head.

## Architecture

The important architectural change is not a global cache. Analysis lifetime is scoped to one `decompile_module` invocation. This avoids cross-request state while still allowing all structural consumers inside one decompilation to share the same facts.

Conceptually:

```text
bytecode module
    ↓
ModuleAnalysis
    ↓
ProtoAnalysis per proto
    ├─ decoded instructions
    ├─ CFG
    ├─ SSA
    ├─ scopes
    └─ lazy symbol recovery
    ↓
collectors + lifter
```

This shared analysis layer is also the foundation for later def/use indexes, effect facts, mutation barriers, call-frame recovery, read-modify-write recovery, closure/proto planning, and canonical source reconstruction.

## What Stage 0 does not do

Stage 0 intentionally does not change:

- table reconstruction semantics;
- `SETLIST` handling;
- general SSA inlining;
- call-frame reconstruction;
- read-modify-write or compound assignment recovery;
- recursion or method recovery;
- naming policy;
- CFG region restructuring.

Those remain separate milestones so each output-changing step can be validated independently.

## Next milestone

Stage 2 targets `SETLIST` and table initialization. The goal is to separate the semantic one-based first array index from the legacy fallback emission offset, allowing affected v3/v6 table entries to remain inside their recovered constructors while preserving the already-correct v11 behavior.
