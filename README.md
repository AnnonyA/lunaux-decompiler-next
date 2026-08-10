# LunaUX Decompiler Next

LunaUX is a local Luau bytecode decompiler/disassembler focused on Roblox. It keeps the heavy work on your machine, supports modern serialized Luau bytecode, and tries to produce readable Luau without executing the bytecode you give it.

**Current status:** **2304/2304 semantic passes**, zero fallback/timeouts. Stage 0 removed repeated CFG/SSA/scope work, and Stage 2 now reconstructs affected v3/v6 `SETLIST` array entries directly inside table literals.

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
- Debug names, smarter fallback names, types, flow-sensitive typing and Roblox API types.
- Metatable/classes, contextual functions and conservative state-machine unflattening.
- Native / Unluau / Python backends through `auto` mode.

> A decompiler cannot restore comments, formatting or every original variable name. LunaUX aims for a safe, readable reconstruction rather than pretending it has the exact original source.

Stage 2 fixes an old `SETLIST` off-by-one path in older bytecode, so code that used to become separate `table[1] = ...` writes can now stay inside the recovered constructor when it is safe.

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
| **Stage 0 / 0.20 dev** | Shared analysis cache: much less repeated CFG/SSA/scope work. |
| **Stage 2** | Correct `SETLIST` index semantics and cleaner v3/v6 table literals. |

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
