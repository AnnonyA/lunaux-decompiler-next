# LunaUX Decompiler Next

A local Roblox Luau bytecode decompiler and disassembler with a native backend, the optional Unluau CLI, a portable Python engine, an HTTP API, a CLI, and Windows/Linux launchers.

> **Version 0.15:** adds flow-sensitive narrowing and an owner-aware Roblox API catalog for properties, methods, services, events, and callback parameter types on top of the 0.14 callback/module pass.

## Engine chain

The recommended `auto` mode tries each engine for every script:

```text
compatible luna.pyd / luna.so
    -> Unluau CLI
    -> LunaUX Python engine
```

A crash, timeout, unsupported file, or empty result from one engine moves the request to the next engine.

## Highlights

- Parses official serialized Luau bytecode v3 through v13.
- Parses the current experimental class format v100.
- Tracks all 90 opcodes currently defined in `Luau/Bytecode.h`, including `NEWCLASS`.
- Validates AUX words, opcode/version compatibility, jump targets, constants, closures, captures, prototypes, feedback slots, and metadata ranges.
- Recovers strings, imports, constants, child functions, line information, debug locals, upvalue names, typed locals, typed upvalues, userdata names, proto flags, sizes, costs, and feedback data.
- Builds an AUX-aware control-flow graph with dominators, postdominators, dominance frontiers, branch joins, natural loops, and strongly connected components.
- Computes register liveness, reaching definitions, reverse def-use chains, and conservative SSA phi placement.
- Renames register definitions into versioned SSA values and resolves phi operands for each predecessor.
- Converts validated two-branch phi diamonds into typed Luau `if ... then ... else ...` expressions.
- Combines reducible short-circuit branch chains into `and` and `or` conditions without crossing side effects.
- Reconstructs full table constructors from `NEWTABLE` and `DUPTABLE`, including nested tables, named/indexed/dynamic keys, fixed `SETLIST` ranges, and final open call or vararg tails.
- Reconstructs Roblox event connections, including `Connect`, `ConnectParallel`, `Once`, and signal waits, with `RBXScriptConnection` result evidence.
- Inlines single-owner closures into recognized event, scheduler, action-binding, sorting, module-field, and returned-function callback positions.
- Rebinds callback captures and follows single-use closure aliases while preserving shared callbacks as named functions.
- Recovers `require` dependency paths, derives stable module names, reports ModuleScript export shape, and folds function-valued module tables.
- Eliminates safe adjacent single-use temporaries without duplicating evaluations or hiding named/typed debug locals.
- Represents recovered unary, binary, table, field, index, call, and method expressions as immutable AST nodes.
- Prints Luau expressions with formal precedence and associativity, including safe nested unary rendering.
- Reconstructs lexical scopes from debug ranges, including shadowing, register reuse, and typed bindings.
- Recovers symbol names from debug metadata, SSA relationships, imports, fields, prototype bindings, and Roblox API call evidence.
- Uses a dedicated Roblox pattern registry for services, children, tags, attributes, signals, spatial queries, constructors, players, and raycasts.
- Generates stable type-family names such as `num1`, `bool1`, `str1`, `arg1`, `vec1`, and `buf1` when original names are absent.
- Infers conservative parameter, local, and return types from serialized type metadata plus data flow and known operation contracts.
- Runs reusable opcode, property, method, constructor, and flow type heuristics before source emission.
- Narrows optional and union values along `nil`, truthiness, `type`/`typeof`, `assert`, and `Instance:IsA` control-flow edges.
- Uses owner-aware Roblox API signatures to type properties, method results, signals, and inline callback parameters.
- Inlines single-use temporaries across short pure instruction gaps while blocking calls, mutations, branches, and source-register redefinitions.
- Tracks table ownership, aliases, contained tables, and SSA dependencies; it materializes constructors before escapes, cycles, dependency redefinitions, unsafe calls, control flow, or ambiguous stack-top writes.
- Reconstructs supported v100 `NEWCLASS` and `NEWCLASSMEMBER` regions as Luau `class ... end` declarations.
- Reconstructs common expressions, table access, calls, methods, returns, closures, numeric/generic loops, `while`/`repeat` regions, and `if`/`else` layouts using compatibility patterns plus whole-function CFG/SSA analysis.
- Resolves modern userdata, class, fastcall, feedback, and proto operands in disassembly.
- Never executes submitted Luau bytecode.

## Recovery quality

### Latest bytecode

Reads official serialized Luau bytecode v3 through v13, retained type metadata v1 through v3, and the current experimental v100 class format. Roblox opcode-byte encoding used by some clients is normalized conservatively before validation.

```text
bytecode v12 · types v3
```

### Generated names

Names are selected from evidence instead of register position alone. Debug locals and prototype names have the highest priority, followed by imports, fields, string arguments to calls such as `GetService`, SSA copies, and inferred type families.

```text
num1 · bool1 · str1 · arg1 · vec1 · buf1
```

For example, a validated `game:GetService("Players")` result can be named `Players`, while a typed unnamed parameter can become `player: Player` or `num1: number`. Set `ShowRecoveredSymbols` to `true` to emit the SSA value, selected name/type, and the strongest evidence as comments in reconstructed output.

### Types and inference

Serialized parameter/local types are preserved. Missing types are inferred conservatively from constants, numeric/string/table opcodes, property reads, known Luau builtins, selected Roblox method contracts, moves, and SSA merges. Function return annotations are emitted only when the observed return paths agree.

```luau
local function func(
    num1: number,
    bool1: boolean,
    str1: string,
    arg1,
    vec1: vector,
    buf1: buffer
): string?
    -- reconstructed body
end
```

### Flow-sensitive types and Roblox API

Version 0.15 tracks type refinements per CFG edge and per SSA use instead of assigning only one type to a value for the whole function. It recognizes non-`nil` branches, truthy checks, `type`/`typeof` comparisons, `assert`, and validated `Instance:IsA("ClassName")` predicates.

The Roblox API catalog is owner-aware. For example, `BasePart.Position` is `Vector3`, `TweenService:Create` returns `Tween`, and known signals provide callback parameter annotations such as `InputBegan(input: InputObject, gameProcessed: boolean)`. Ambiguous members keep the previous conservative result.

```luau
UserInputService.InputBegan:Connect(function(
    input: InputObject,
    gameProcessed: boolean
)
    if not gameProcessed then
        print(input.KeyCode)
    end
end)
```

Use `FlowSensitiveTypes` and `RobloxAPITypes` to disable either layer independently. See [`docs/FLOW_TYPES_AND_ROBLOX_API.md`](docs/FLOW_TYPES_AND_ROBLOX_API.md).

### Roblox events, callbacks, and modules

Version 0.14 recognizes Roblox signal connections and supported callback sinks. A closure is inlined only when SSA proves that the closure instance has one supported destination; shared or escaping callbacks keep their named prototype form.

```luau
local connection: RBXScriptConnection = button.Activated:Connect(function(input)
    print(input)
end)

local inventoryService = require(script.Parent.InventoryService)

return {
    Start = function()
        inventoryService:Start()
    end,
}
```

The output header reports recognized event bindings, `require` dependencies, and a consistent ModuleScript export kind. Captured values are rebound inside anonymous functions, and pending module tables are materialized before a capture or dependency change could alter semantics. See [`docs/ROBLOX_EVENTS_CALLBACKS_MODULES.md`](docs/ROBLOX_EVENTS_CALLBACKS_MODULES.md).

### Full table reconstruction

Version 0.13 treats table construction as an ownership problem instead of only an adjacent-instruction pattern. A child table is absorbed into its parent only when every use is either part of its own construction or the single parent insertion. Independent tables may be built in an interleaved instruction stream without forcing either constructor to close early.

```luau
local config = {
    Name = "Sword",
    Stats = {
        Damage = 25,
        Critical = true,
    },
    [dynamicKey] = dynamicValue,
    "Fire",
    collectMore(),
}
```

Recovered constructors may include:

- `SETTABLEKS` and `SETUDATAKS` named fields;
- `SETTABLEN` and fixed `SETLIST` array ranges;
- arbitrary `SETTABLE` keys rendered as `[expression] = value`;
- `DUPTABLE` key templates and constant-valued templates;
- deterministic overwrites before the table is observed;
- single-use `MOVE` aliases;
- a final multiple-return call or `...` tail when the open `SETLIST` range is contiguous.

Self-references, shared children, calls that can observe pending state, noncontiguous open ranges, dependency redefinitions, and ambiguous escapes keep the conservative statement form.

### Class recovery

When the v100 class shape and member bindings validate, `NEWCLASS` and `NEWCLASSMEMBER` are emitted as class syntax instead of anonymous table placeholders.

```luau
class Point
    public x

    function length(self: Point): number
        -- reconstructed body
    end
end
```

Class construction remains a normal call expression, for example `local point: Point = Point(1)`. Unsupported or ambiguous class regions retain the conservative compatibility representation.

> Bytecode does not retain comments, original formatting, every source-level construct, or all names. Smart recovery reports the best supported reconstruction; it does not claim exact original source.

## Quick start

### Windows

Requirements:

- Windows 10 or 11;
- Python 3.11 or newer;
- Python 3.13 x64 only for the recovered Windows `luna.pyd`;
- Git and .NET SDK only when building Unluau from source.

```bat
git clone https://github.com/AnnonyA/lunaux-decompiler-next.git
cd lunaux-decompiler-next
run.bat
```

In the launcher:

1. Select **Install / Update**.
2. Keep **Backend mode** on `auto`.
3. Optionally configure `luna.pyd` or an Unluau executable.
4. Select **Start server**.
5. Open **API docs**.

### Linux

Requirements:

- Python 3.11 or newer;
- `python3-venv` on distributions that package `venv` separately;
- Git and .NET SDK only when building Unluau from source.

```bash
git clone https://github.com/AnnonyA/lunaux-decompiler-next.git
cd lunaux-decompiler-next
chmod +x run.sh
./run.sh
```

`run.sh` creates `.venv`, installs or updates LunaUX Next, and starts the local API. Press `Ctrl+C` to stop it.

Default API address:

```text
http://127.0.0.1:8000
```

Interactive documentation:

```text
http://127.0.0.1:8000/docs
```

You can override the Linux bind address with environment variables:

```bash
LUNAUX_HOST=127.0.0.1 LUNAUX_PORT=8000 ./run.sh
```

## Install the pinned Unluau source

LunaUX includes a reproducible installer for the reviewed upstream Unluau revision. It explicitly fetches the Apache-2.0 source, checks out the pinned commit, builds the CLI, copies its license, and writes a build manifest.

Windows x64:

```bat
py -3 scripts\install_unluau.py --runtime win-x64
```

Linux x64:

```bash
python3 scripts/install_unluau.py --runtime linux-x64
```

Fetch only the pinned source:

```bash
python3 scripts/install_unluau.py --source-only
```

The source is stored in `third_party/unluau` and the build in `tools/unluau`. Both generated directories are ignored by Git. LunaUX then detects the CLI automatically.

You may instead select or configure an existing `Unluau.CLI.exe`, `Unluau.CLI.dll`, or compatible executable. See [`docs/UNLUAU.md`](docs/UNLUAU.md).

## Backend modes

| Mode | Behavior |
| --- | --- |
| `auto` | Native, then Unluau, then Python. Recommended. |
| `native` | Require the `luna` extension. |
| `unluau` | Require Unluau. |
| `reconstructed` | Use only the Python parser/lifter. |

Diagnostics on Windows:

```bat
.venv\Scripts\python.exe -m lunaux doctor
```

Diagnostics on Linux:

```bash
.venv/bin/python -m lunaux doctor
```

## File CLI

Windows:

```bat
.venv\Scripts\lunaux.exe decompile input.luac -o recovered.luau
.venv\Scripts\lunaux.exe disassemble input.luac -o instructions.txt
```

Linux:

```bash
.venv/bin/lunaux decompile input.luac -o recovered.luau
.venv/bin/lunaux disassemble input.luac -o instructions.txt
```

Input can be raw bytecode or Base64 according to `--input-format`.

## API routes

Classic plain-text routes:

```text
GET  /health
POST /decompile
POST /disassemble
POST /decomp
POST /disasm
```

Structured routes with backend metadata:

```text
GET  /v1/health
POST /v1/decompile
POST /v1/disassemble
```

## API script

Paste [`examples/api_script.luau`](examples/api_script.luau) into an **authorized environment** that provides:

- `request`;
- `getscriptbytecode`;
- `base64encode` or `crypt.base64.encode`.

Start the LunaUX server first, then use this client:

```luau
-- LunaUX Next local API client
-- Requires an authorized environment that provides request, getscriptbytecode,
-- and either base64encode or crypt.base64.encode.

assert(request, "http request function missing")
assert(getscriptbytecode, "getscriptbytecode function missing")

local base64_encoder = (crypt and crypt.base64 and crypt.base64.encode) or base64encode
assert(base64_encoder, "base64encode function missing")

local http = game:GetService("HttpService")
local environment = getgenv and getgenv() or _G
local apiBaseUrl = environment.LUNAUX_API_URL or "http://127.0.0.1:8000"

environment.LUNAUX_OPTIONS = environment.LUNAUX_OPTIONS or {
    Semicolons = false,
    StringInterpolation = true,
    UpvalueComment = true,
    ShowLineDefined = true,
    ShowFunctionId = false,
    PreserveForStep = false,
    UseIfExpression = true,
    RecoverPhiExpressions = true,
    CombineBooleanConditions = true,
    ReconstructTableLiterals = true,
    InlineSingleUseTemporaries = true,
    SmartVariableNames = true,
    InferTypes = true,
    ShowRecoveredSymbols = false,
    RecoverClasses = true,
    MaxOutputCharacters = 4000000,
}

local function apiRequest(bytecode, branch, scriptName, options)
    local payload = {
        bytecode = base64_encoder(bytecode),
        filename = scriptName,
    }

    if options then
        payload.options = options
    end

    local response = request({
        Url = apiBaseUrl .. "/" .. branch,
        Method = "POST",
        Headers = {
            ["Content-Type"] = "application/json",
        },
        Body = http:JSONEncode(payload),
    })

    if response.StatusCode ~= 200 then
        return `--[[ Server error (HTTP {response.StatusCode}):\n\t{response.Body}\n]]`
    end

    return response.Body
end

local function isValidScript(scriptInstance: BaseScript)
    return
        (scriptInstance.ClassName == "Script" and scriptInstance.RunContext == Enum.RunContext.Client)
        or scriptInstance.ClassName == "LocalScript"
        or scriptInstance.ClassName == "ModuleScript"
end

environment.decompile = function(scriptPath: BaseScript)
    if typeof(scriptPath) ~= "Instance" then
        return "-- Invalid argument #1 to 'decompile' (Instance expected)"
    end
    if not isValidScript(scriptPath) then
        return "-- Server scripts are IMPOSSIBLE to decompile"
    end

    local ok, bytecode = pcall(getscriptbytecode, scriptPath)
    if not ok then
        return `--[[ Failed to get script bytecode:\n\t{bytecode}\n]]`
    end
    if type(bytecode) ~= "string" then
        return `--[[ Failed to get script bytecode, string type expected got {type(bytecode)} ]]`
    end
    if bytecode == "" then
        return "-- Empty bytecode"
    end

    return apiRequest(bytecode, "decompile", scriptPath.Name, environment.LUNAUX_OPTIONS)
end

environment.disassemble = function(scriptPath: BaseScript)
    if typeof(scriptPath) ~= "Instance" then
        return "-- Invalid argument #1 to 'disassemble' (Instance expected)"
    end
    if not isValidScript(scriptPath) then
        return "-- Server scripts are IMPOSSIBLE to disassemble"
    end

    local ok, bytecode = pcall(getscriptbytecode, scriptPath)
    if not ok then
        return `--[[ Failed to get script bytecode:\n\t{bytecode}\n]]`
    end
    if type(bytecode) ~= "string" then
        return `--[[ Failed to get script bytecode, string type expected got {type(bytecode)} ]]`
    end
    if bytecode == "" then
        return "-- Empty bytecode"
    end

    return apiRequest(bytecode, "disassemble", scriptPath.Name)
end
```

Example usage:

```luau
local source = decompile(game.Players.LocalPlayer.PlayerScripts.LocalScript)
print(source)

local instructions = disassemble(game.Players.LocalPlayer.PlayerScripts.LocalScript)
print(instructions)
```

To use a different local API address:

```luau
getgenv().LUNAUX_API_URL = "http://127.0.0.1:8000"
```

## API options

All decompiling options can be placed inside `LUNAUX_OPTIONS` or sent in the JSON `options` object.

| Option | Default | Description |
| --- | --- | --- |
| `Semicolons` | `false` | Add a semicolon after generated statements. |
| `StringInterpolation` | `true` | Prefer Luau string interpolation when the backend can reconstruct it. |
| `UpvalueComment` | `true` | Include information about upvalues used by reconstructed functions. |
| `ShowLineDefined` | `true` | Include the original prototype line-defined metadata when available. |
| `ShowFunctionId` | `false` | Include the original function/prototype identifier. `ShowLineDefined` should also be enabled. |
| `PreserveForStep` | `false` | Keep the explicit step in numeric loops, including a step of `1`. |
| `UseIfExpression` | `true` | Prefer `if ... then ... else ...` expressions instead of equivalent `and`/`or` expressions. |
| `RecoverPhiExpressions` | `true` | Convert validated two-way SSA phi diamonds into Luau `if` expressions. |
| `CombineBooleanConditions` | `true` | Combine reducible short-circuit jump chains into `and` and `or`. |
| `ReconstructTableLiterals` | `true` | Recover owned table-construction regions, including nested tables, templates, dynamic keys, aliases, overwrites, and supported `SETLIST` tails. |
| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
| `RecoverRobloxEvents` | `true` | Report recognized Roblox signal connections and event waits. |
| `InlineRobloxCallbacks` | `true` | Inline single-owner closures into supported callback, module-field, and returned-function positions. |
| `RecoverRobloxModules` | `true` | Recover `require` dependency paths and ModuleScript export shape. |
| `SmartVariableNames` | `true` | Select names from debug metadata, SSA relationships, imports, fields, types, and Roblox API evidence. |
| `InferTypes` | `true` | Infer conservative parameter, local, expression, and return types. |
| `ShowRecoveredSymbols` | `false` | Emit comments describing recovered SSA names, types, and evidence. |
| `RecoverClasses` | `true` | Reconstruct validated experimental class regions as Luau class syntax. |
| `MaxOutputCharacters` | `4000000` | Maximum generated output length. Accepted range: 1,000 to 20,000,000 characters. |

The exact effect of formatting options can vary by backend. Unsupported options are preserved for compatibility but may not change every engine's output.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LUNAUX_BACKEND_MODE` | `auto` | `auto`, `native`, `unluau`, or `reconstructed`. |
| `LUNAUX_BACKEND_MODULE` | `luna` | Native extension import name. |
| `LUNAUX_NATIVE_PATH` | empty | Direct `.pyd` or `.so` path. |
| `LUNAUX_UNLUAU_PATH` | auto-detect | Unluau executable or `.dll`. |
| `LUNAUX_EXTERNAL_TIMEOUT_SECONDS` | `45` | External operation timeout. |
| `LUNAUX_MAX_BYTECODE_BYTES` | `16777216` | Maximum accepted input size. |
| `LUNAUX_CORS_ORIGINS` | empty | Allowed browser origins. |

## Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check .
mypy
pytest
```

The repository also checks its opcode, constant, builtin, and bytecode-version metadata against the current upstream `Luau/Bytecode.h` on a schedule. See [`scripts/check_luau_bytecode_spec.py`](scripts/check_luau_bytecode_spec.py). The compiler-analysis design is documented in [`docs/COMPILER_ANALYSIS.md`](docs/COMPILER_ANALYSIS.md), the SSA stage in [`docs/SSA_AND_EXPRESSIONS.md`](docs/SSA_AND_EXPRESSIONS.md), and the structured AST/scope stage in [`docs/AST_AND_SCOPES.md`](docs/AST_AND_SCOPES.md).

## Accuracy and limitations

This update improves bytecode compatibility and semantic reconstruction, but bytecode does not preserve comments, exact formatting, every local name, or every original high-level control-flow choice. Optimized or irreducible patterns may still be represented conservatively with labels or comments. No decompiler can guarantee byte-for-byte recovery of the original source.

Only inspect scripts you own or are authorized to analyze.

## Third-party attribution

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Luau is MIT-licensed. Unluau is an Apache-2.0 project and remains separately attributed.
