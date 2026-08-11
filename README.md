# LunaUX Decompiler Next

LunaUX is a local Luau bytecode decompiler/disassembler focused on Roblox. It keeps the heavy work on your machine, supports modern serialized Luau bytecode, and tries to produce readable Luau without executing the bytecode you give it.

**Current status:** **2304/2304 semantic passes**, 100% execution/syntax/recompilation/stability/zero-fallback, **384/384 Medal-compatible**, with **0 semantic failures** and **0 timeouts**. Stages 0–4 are now merged into `main`: shared analysis, safety/effect infrastructure, semantic `SETLIST` table recovery, exact-SSA expression folding with `CallFrame`, and structural `ReadModifyWrite` recovery.

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
- CFG + SSA based control flow, loops, `break`/`continue`, booleans and phi expressions.
- Tables, nested tables, closures, callbacks, modules and Roblox event patterns.
- Semantic legacy `SETLIST` table initializers with conservative open-tail ownership.
- Exact-SSA expression folding and `CallFrame` reconstruction without duplicating observable evaluation.
- Structural compound assignments such as `data.Stats.Score += data[1]` when lvalue identity is proven.
- Debug names, smarter fallback names, types, flow-sensitive typing and Roblox API types.
- Metatable/classes, contextual functions and conservative state-machine unflattening.
- Native / Unluau / Python backends through `auto` mode.

> A decompiler cannot restore comments, formatting or every original variable name. LunaUX aims for a safe, readable reconstruction rather than pretending it has the exact original source.

## Stage 2: `SETLIST` / table initializer recovery

Stage 2 fixes the v3/v6 `SETLIST` indexing mismatch without version-specific output hacks. `SetListSemantics` is now the shared format-level source of truth, keeping the one-based semantic array index separate from the legacy zero-based statement-emission offset. Structural table recovery consumes only the semantic domain and never mutates raw AUX values.

That turns legacy output like separate indexed writes back into the constructor shape the bytecode represents:

```luau
local value = {Name = "case-0", Stats = {Score = 0, Enabled = true}, 0, 0}
```

The recovery remains conservative: batches must be contiguous, owned by the exact pending-table SSA value, and must not cross observable escapes, calls, incompatible CFG boundaries, dependency redefinitions, unsafe nested ownership, or unproven open CALL/VARARG tails. When proof fails, LunaUX keeps the existing statement fallback.

Stage 2 changed exactly **144/2304** corpus outputs: **72 v3 + 72 v6**, with **0 v11** or other-version changes. All 144 were readability wins, with **0 losses** and **2160 ties**. Tables median readability moved from **85.125 → 88.0263**; global median moved from **86.0977 → 86.75095**.

Validation for this stage: **223 pytest passed**, Ruff clean, mypy clean, and `git diff --check` clean. Stage 0 analysis counts are preserved, so Stage 2 adds no duplicate decode/CFG/SSA/scope construction.

## Stage 3 + Stage 4: SSA folding, `CallFrame` and `ReadModifyWrite`

Stage 3 replaces legacy register-oriented temporary cleanup with conservative planning over exact `SSAValue` identities. Single-use expressions are folded only when dependency versions, basic-block ownership, debug-local constraints, effects and the original evaluation trace prove that materialization can be removed safely. `CallFrame` gives calls a shared semantic model for callee/receiver ownership, fixed or open arguments, MULTRET tails and result shape rather than reconstructing call setup from rendered temporaries.

Stage 4 builds on that SSA infrastructure with structural lvalue identity. Locals, globals, upvalues, fields and indexed locations are compared through their semantic storage identity and exact SSA base/key versions — never through rendered source strings or physical-register history. When the read/operation/write sequence is proven exact, LunaUX can recover human Luau such as:

```luau
local value = {Name = "case-0", Stats = {Score = 0, Enabled = true}, 0, 0}
value.Stats.Score += value[1]
print(value.Name, value.Stats.Score, value[2])
```

Calls, mutable reads and metamethod-observable operations are not duplicated; arbitrary CFG crossings, phis and loop boundaries remain conservative. Stage 2 table ownership and open `CALL`/`VARARG` `SETLIST` tails remain intact.

Across the deterministic 2304-case corpus, Stage 3+4 changed **2088 outputs**, removed **5544 synthetic temporaries**, recovered **1260 compound assignments** including **144 nested targets**, and moved global median readability from **86.7510 → 90.7895**. The measured warmed decompiler-only throughput moved from **110.97 → 125.49 cases/s** while Stage 0 shared-analysis construction counts stayed unchanged.

Validation for Stage 3+4: **232 pytest passed**, Ruff clean, mypy clean, `git diff --check` clean, **2304/2304 semantic**, **384/384 Medal-compatible**, 100% execution/syntax/recompilation/stability/zero-fallback, with 0 semantic failures and 0 timeouts. The post-merge GitHub CI matrix and public benchmark also completed successfully.

## Recovery roadmap

| Stage | Focus | Target | Status |
| --- | --- | --- | --- |
| **Stage 0** | Shared analysis cache | Speed: reuse decode / CFG / SSA / scope work. | ✅ Complete |
| **Stage 1** | Def/use + effects + barriers | Safe infrastructure for later structural rewrites. | ✅ Complete |
| **Stage 2** | `SETLIST` / `TableInit` | Correct `{ ..., 0, 0 }` reconstruction in v3/v6. | ✅ Complete |
| **Stage 3** | SSA folds + `CallFrame` | Remove many `value2` / `value3` / `value4` temporaries. | ✅ Complete |
| **Stage 4** | `ReadModifyWrite` | Recover forms like `data.Stats.Score += data[1]`. | ✅ Complete |
| **Stage 5** | `ProtoEmissionPlan` | Human recursion, methods and closures. | Next |
| **Stage 6+** | CFG structuring + naming | Canonical source approaching Oracle-style readability. | Planned |

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
