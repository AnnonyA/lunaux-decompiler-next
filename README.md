# LunaUX Decompiler Next

LunaUX is a local Luau bytecode decompiler/disassembler focused on Roblox. It keeps the heavy work on your machine, supports modern serialized Luau bytecode, and tries to produce readable Luau without executing the bytecode you give it.

**Current status:** **2304/2304 semantic passes**, 100% execution/syntax/recompilation/stability/zero-fallback, **384/384 Medal-compatible**, with **0 semantic failures** and **0 timeouts**. Stage 7 source fidelity is now implemented in `main`: exact CALL/MULTRET result shapes, transactional call-valued table construction, stronger SSA expression folding, returned-module naming, dot-function declarations, value-position short-circuit recovery, type preservation, and deterministic complex-table formatting build on the completed Stage 0→6+ architecture.

## Quick start

### Windows

```bat
git clone https://github.com/AnnonyA/lunaux-decompiler-next.git
cd lunaux-decompiler-next
run.bat
```

### Linux

```bash
git clone https://github.com/AnnonyA/lunaux-decompiler-next.git
cd lunaux-decompiler-next
chmod +x run.sh
./run.sh
```

The local API starts at:

```text
http://127.0.0.1:8000
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## Roblox / loadstring

Start LunaUX first, then run this in an **authorized environment** that provides `request`, `getscriptbytecode`, and Base64 support:

```luau
loadstring(game:HttpGet(
    "https://raw.githubusercontent.com/AnnonyA/lunaux-decompiler-next/main/examples/api_script.luau"
))()

local module = game:GetService("ReplicatedStorage"):WaitForChild("MyModule")
print(decompile(module))
```

The full Roblox client is in [`examples/api_script.luau`](examples/api_script.luau).

## What it recovers

- Luau bytecode **v3-v13** plus the experimental **v100** class format.
- CFG + SSA based control flow, loops, `break`/`continue`, short-circuit booleans and phi expressions.
- Tables, nested tables, closures, callbacks, modules and Roblox event patterns.
- Semantic legacy `SETLIST` table initializers with conservative open-tail ownership.
- Exact-SSA expression folding and `CallFrame` reconstruction without duplicating observable evaluation.
- Structural compound assignments such as `data.Stats.Score += data[1]` when lvalue identity is proven.
- SSA-owned proto emission for recursive functions, mutually recursive groups, methods and inline closures.
- Canonical CFG region planning over branches, loops, booleans, phis, state machines and conservative fallbacks.
- Deterministic semantic naming that preserves debug evidence and uses role/context evidence without inventing source facts.
- Types, flow-sensitive typing and Roblox API types.
- Metatable/classes, contextual functions and conservative state-machine unflattening.
- Native / Unluau / Python backends through `auto` mode.

> A decompiler cannot restore comments, formatting or every original variable name. LunaUX aims for a safe, readable reconstruction rather than pretending it has the exact original source.

## Stage 2: `SETLIST` / table initializer recovery

Stage 2 fixes the v3/v6 `SETLIST` indexing mismatch without version-specific output hacks. `SetListSemantics` is the shared format-level source of truth, keeping the one-based semantic array index separate from the legacy zero-based statement-emission offset. Structural table recovery consumes only the semantic domain and never mutates raw AUX values.

That turns legacy output like separate indexed writes back into the constructor shape the bytecode represents:

```luau
local value = {Name = "case-0", Stats = {Score = 0, Enabled = true}, 0, 0}
```

The recovery remains conservative: batches must be contiguous, owned by the exact pending-table SSA value, and must not cross observable escapes, calls, incompatible CFG boundaries, dependency redefinitions, unsafe nested ownership, or unproven open CALL/VARARG tails. When proof fails, LunaUX keeps the existing statement fallback.

Stage 2 changed exactly **144/2304** corpus outputs: **72 v3 + 72 v6**, with **0 v11** or other-version changes. All 144 were readability wins, with **0 losses** and **2160 ties**. Tables median readability moved from **85.125 → 88.0263**; global median moved from **86.0977 → 86.75095**.

Validation for this stage: **223 pytest passed**, Ruff clean, mypy clean, and `git diff --check` clean. Stage 0 analysis counts are preserved.

## Stage 3 + Stage 4: SSA folding, `CallFrame` and `ReadModifyWrite`

Stage 3 replaces legacy register-oriented temporary cleanup with conservative planning over exact `SSAValue` identities. Single-use expressions are folded only when dependency versions, basic-block ownership, debug-local constraints, effects and the original evaluation trace prove that materialization can be removed safely. `CallFrame` gives calls a shared semantic model for callee/receiver ownership, fixed or open arguments, MULTRET tails and result shape.

Stage 4 builds on that infrastructure with structural lvalue identity. Locals, globals, upvalues, fields and indexed locations are compared through semantic storage identity and exact SSA base/key versions — never through rendered source strings or physical-register history.

```luau
local value = {Name = "case-0", Stats = {Score = 0, Enabled = true}, 0, 0}
value.Stats.Score += value[1]
print(value.Name, value.Stats.Score, value[2])
```

Across the deterministic 2304-case corpus, Stage 3+4 changed **2088 outputs**, removed **5544 synthetic temporaries**, recovered **1260 compound assignments** including **144 nested targets**, and moved global median readability from **86.7510 → 90.7895**. The warmed decompiler-only throughput moved from **110.97 → 125.49 cases/s** while Stage 0 shared-analysis construction counts stayed unchanged.

Validation for Stage 3+4: **232 pytest passed**, Ruff clean, mypy clean, `git diff --check` clean, **2304/2304 semantic**, **384/384 Medal-compatible**, 100% execution/syntax/recompilation/stability/zero-fallback. The post-merge GitHub CI matrix and public benchmark also completed successfully.

## Stage 5 + Stage 6+: `ProtoEmissionPlan`, canonical CFG and semantic naming

Stage 5 introduces `ProtoEmissionPlan`, a shared SSA-based authority for deciding how each closure/proto is represented in source. Closure ownership follows exact `SSAValue` identity through aliases rather than physical-register history. The planner can recover local recursive functions, conservatively predeclare mutual-recursion groups, prove method declarations from stable receiver/field/call evidence, and inline single-consumer closures while preserving capture/upvalue lifetime and evaluation order.

Stage 6+ adds canonical CFG planning and semantic naming. `CanonicalCFGPlan` centralizes known structured regions from loops, boolean chains, phi diamonds, state-machine recovery and dominator/postdominator branch evidence, while irreducible multi-entry flow retains a conservative fallback. `SemanticNamePlan` resolves names deterministically from debug bindings first, then parameter/function roles, structural/contextual evidence and stable fallbacks.

Representative source can now move from decompiler-shaped closure materialization toward forms such as:

```luau
local function factorial(n)
    if n <= 0 then
        return 1
    end

    return n * factorial(n - 1)
end
```

and, only when receiver semantics are proven:

```luau
function value:Update(amount)
    self.Score += amount
end
```

Stage 5+6 changed **552/2304** corpus outputs: **176 v3 + 176 v6 + 200 v11**. Global median readability moved **90.7895 → 92.12 after Stage 5 → 92.42905 final**, with **544 paired wins, 8 losses and 1752 ties**. The eight scorer losses remove genuine unnecessary materialization rather than introduce semantic regressions.

Final local validation: **244 pytest passed**, Ruff clean, mypy clean across **67 source files**, `git diff --check` clean, **2304/2304 semantic**, **384/384 Medal-compatible**, and 100% execution/syntax/recompilation/stability/zero-fallback. Deterministic corpus digest: `81aa1f1ed69d2f209813e802d14d7160b545829b1881c3a8d20f9e0147fdc598`.

Warmed decompiler-only performance measured **32.348 s / 71.23 cases/s** on the Stage 3+4 base, **32.568 s / 70.74 cases/s** after Stage 5, and **21.509 s / 107.12 cases/s** for the final Stage 5+6 tree. Stage 0 construction remains shared: decode/CFG/SSA/scope **3456 each**, symbols **2880**.

The main remaining structuring limitation is deliberate: generic `elseif` and guard emission remains conservative until the AST emitter can own region closure boundaries end-to-end. The CFG planner records those regions now, but does not fabricate prettier source when emission ownership is not yet proven.

## Stage 7: source fidelity

Stage 7 targets the gap between semantically correct output and human-quality source on real modules. `CallResultShape` now makes fixed-zero, fixed-one, fixed-many and open CALL results explicit through shared `CallFrame` semantics. `TableBuildPlan` can transactionally retain owned CALL expressions inside pending table constructors when exact SSA ownership, evaluation order, escape state and result shape prove that doing so is safe. True open MULTRET tails remain conservative and preserve Luau tail semantics.

That means nested call-valued tables can stay structural instead of exploding into constructor-only temporaries. The real v9 regression fixture moved from **148 → 4 synthetic temporaries**, **138 → 0 constructor temporaries**, and **33 → 0 false MULTRET annotations**. It now recovers **96 table constructors**, **47 CALL expressions directly in tables**, **5 `function module.*` declarations**, no numbered `data*`/`color*` temporaries, and deterministic module-root naming.

Stage 7 also extends `ProtoEmissionPlan` with stable dot-field function declarations, recovers exact operand-valued `and`/`or` expressions, preserves serialized parameter types, uses `_` for proven unused non-debug iterator bindings, and adds deterministic multiline rendering for large or nested `TableExpr` values without reordering entries.

Across the deterministic corpus, Stage 7 changes **1696/2304 outputs** while retaining **2304/2304 semantic**, **384/384 Medal-compatible**, and 100% execution/syntax/recompilation/stability/zero-fallback. Global median readability moves from **92.42905 → 93.45525** with **1056 wins, 496 losses and 752 ties**; several scorer losses are intentional human-readable simplifications such as direct return-call folding and unused `_` bindings. Stage 0 analysis construction remains unchanged at **3456 decode / CFG / SSA / scope** and **2880 symbol** builds.

Validation: **248 pytest passed**, Ruff clean, mypy clean across **67 source files**, `git diff --check` clean, and clean-base `git apply --check` clean. Deterministic corpus digest: `b2a8325981a45828cc4a687f87840529b2b15de518478f13602f5e444f64a3ac`.

The main remaining architecture item is a complete statement AST: generic function-body emission is still line-oriented even though table/call/expression ownership is now substantially more structural.

## Recovery roadmap

| Stage | Focus | Target | Status |
| --- | --- | --- | --- |
| **Stage 0** | Shared analysis cache | Reuse decode / CFG / SSA / scope work. | ✅ Complete |
| **Stage 1** | Def/use + effects + barriers | Safe infrastructure for structural rewrites. | ✅ Complete |
| **Stage 2** | `SETLIST` / `TableInit` | Correct `{ ..., 0, 0 }` reconstruction in v3/v6. | ✅ Complete |
| **Stage 3** | SSA folds + `CallFrame` | Remove compiler temporaries safely. | ✅ Complete |
| **Stage 4** | `ReadModifyWrite` | Recover forms like `data.Stats.Score += data[1]`. | ✅ Complete |
| **Stage 5** | `ProtoEmissionPlan` | Human recursion, methods and closures. | ✅ Complete |
| **Stage 6+** | CFG structuring + naming | Canonical, deterministic source recovery. | ✅ Complete |
| **Stage 7** | Source fidelity | CALL-valued constructors, exact MULTRET ownership, module functions and canonical table output. | ✅ Complete |

## Progress so far

| Version | Main change |
| --- | --- |
| **0.1** | Backend system, CLI, API, validation and cross-platform setup. |
| **0.13** | Full table-constructor recovery, including nested/mixed tables. |
| **0.14** | Roblox events, callback inlining and module recovery. |
| **0.15** | Flow-sensitive types and Roblox API typing. |
| **0.16** | Metatable classes and contextual function recovery. |
| **0.17** | CFG-native loops and conservative state-machine unflattening. |
| **0.18** | Semantic/stability hardening across the public corpus. |
| **Stage 0 / 0.20 dev** | Shared `ModuleAnalysis`: one decode/CFG/SSA/scope build per proto. |
| **Stage 2 / 0.20 dev** | Semantic `SETLIST` domain + contiguous table-initializer recovery for legacy v3/v6. |
| **Stage 3 / 0.20 dev** | Exact-SSA expression folding + `CallFrame` ownership with evaluation-order/effect barriers. |
| **Stage 4 / 0.20 dev** | Structural `ReadModifyWrite` recovery + AST compound assignments. |
| **Stage 5 / 0.20 dev** | SSA-owned `ProtoEmissionPlan` for recursion, methods, captures and closure emission. |
| **Stage 6+ / 0.20 dev** | Canonical CFG region planning + deterministic semantic naming. |
| **Stage 7 / 0.20 dev** | Transactional table/CALL ownership, source-fidelity folding, module field declarations and canonical table formatting. |

## Backend modes

```text
auto          native -> Unluau -> Python
native        luna extension only
unluau        Unluau only
reconstructed Python engine only
```

`auto` is the recommended mode.

## CLI

```bash
lunaux decompile input.luac -o recovered.luau
lunaux disassemble input.luac -o instructions.txt
```

## More

- [`CHANGELOG.md`](CHANGELOG.md)
- [`docs/`](docs/)
- [`examples/api_script.luau`](examples/api_script.luau)

Use LunaUX only on bytecode you are allowed to inspect.
