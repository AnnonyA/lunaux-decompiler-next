# LunaUX Decompiler Next

LunaUX is a local Luau bytecode decompiler focused on producing safe, readable
source instead of register-shaped output. It supports modern Roblox Luau
bytecode, runs entirely on your machine, and never executes the bytecode it is
decompiling.

The current development build passes all **2,304 semantic corpus cases** and
all **384 Medal-compatible cases**, with 100% syntax, recompilation, execution,
stability, and zero-fallback coverage.

## Why LunaUX?

Decompilation is more than translating opcodes line by line. LunaUX rebuilds
control flow and value identity before emitting source, which lets it recover
things such as:

- nested and mixed table constructors;
- numeric and generic loops with correct `break` and `continue` ownership;
- short-circuit expressions and conditional values;
- exact fixed/open call and multiple-return behavior;
- recursive functions, closures, methods, and captured variables;
- safe compound assignments such as `data.Stats.Score += data[1]`;
- debug names and serialized Luau types when that information survives.

When the bytecode does not prove a prettier reconstruction, LunaUX keeps a
conservative form. It does not guess destroyed names or replay old physical
register contents as if they were stable variables.

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

The local API starts at `http://127.0.0.1:8000`, with interactive documentation
at `http://127.0.0.1:8000/docs`.

## CLI

```bash
lunaux decompile input.luac -o recovered.luau
lunaux disassemble input.luac -o instructions.txt
```

Available backend modes:

```text
auto          native -> Unluau -> Python
native        native luna extension only
unluau        Unluau only
reconstructed Python engine only
```

`auto` is recommended for normal use.

## Roblox client

Start the local LunaUX server, then use the provided client in an authorized
environment with `request`, `getscriptbytecode`, and Base64 support:

```luau
loadstring(game:HttpGet(
    "https://raw.githubusercontent.com/AnnonyA/lunaux-decompiler-next/main/examples/api_script.luau"
))()

local module = game:GetService("ReplicatedStorage"):WaitForChild("MyModule")
print(decompile(module))
```

See [`examples/api_script.luau`](examples/api_script.luau) for the complete
client.

## How it works

The reconstructed backend follows a structural pipeline:

```text
serialized bytecode
  -> shared module analysis
  -> CFG, dominance, scopes, and SSA
  -> effects, calls, tables, captures, and proto ownership
  -> structured regions and semantic AST
  -> canonical Luau renderer
```

Recent work hardened the difficult interactions between phi values, FASTCALL
paths, open tuples, `SETLIST`, nested loops, mutual recursion, and closure
cells. Analysis is cached once per prototype and shared by all collectors.

## Validation

The current tree is validated with:

- **258 pytest tests**;
- Ruff and strict Mypy across 67 source files;
- **2,304 / 2,304** semantic corpus cases;
- **384 / 384** Medal-compatible cases;
- a real Luau v13 MegaStress fixture with 89 prototypes;
- deterministic differential execution over 19 seeds;
- a bounded compile/decompile/recompile fuzz campaign.

Corpus readability improved from `93.45525` to `93.5133` in the latest stage,
with 56 paired wins and no losses. Readability is telemetry only: semantic
correctness remains the hard requirement.

## Supported formats

- Luau bytecode versions **3 through 13**;
- experimental version **100** class bytecode;
- modern serialized type metadata where available;
- Roblox-oriented module, event, class, and API recovery.

## Honest limits

A compiler destroys comments, formatting, and sometimes local names or source
structure. LunaUX cannot recover information that is no longer in the
bytecode. Its goal is deterministic, idiomatic Luau backed by evidence—not a
fictional claim that the exact original source was restored.

Use LunaUX only on bytecode you are authorized to inspect.

## Project links

- [Changelog](CHANGELOG.md)
- [Documentation](docs/)
- [Issues](https://github.com/AnnonyA/lunaux-decompiler-next/issues)

Licensed under the [Apache License 2.0](LICENSE).
