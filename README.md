# ByteWeft

ByteWeft is a local Luau bytecode decompiler. It rebuilds control flow, SSA value
identity, scopes, tables, calls, closures, and Roblox-specific patterns before it
writes source. The goal is simple: output that reads like Luau, not a transcript of
reused VM registers.

The project was formerly called LunaUX Next. The Python package remains `lunaux`
for compatibility, and the old `lunaux` command is still available as an alias.

## What it recovers

- mixed and nested table constructors, including fixed and open `SETLIST` writes;
- numeric and generic loops with evidence-backed `break` and `continue` ownership;
- short-circuit values, conditional expressions, and conservative repeat loops;
- fixed/open calls and exact multiple-return behavior;
- recursive functions, closures, captures, methods, and module fields;
- debug names and serialized Luau types when the bytecode preserves them;
- Roblox services, events, callbacks, modules, and common API types.

ByteWeft does not invent comments, names, or source structure that compilation
destroyed. When a prettier form cannot be proven safe, it keeps the conservative
form.

## Install and run

Windows:

```bat
git clone https://github.com/AnnonyA/byteweft.git
cd byteweft
run.bat
```

Linux:

```bash
git clone https://github.com/AnnonyA/byteweft.git
cd byteweft
chmod +x run.sh
./run.sh
```

Direct CLI use:

```bash
byteweft decompile input.luac -o recovered.luau
byteweft disassemble input.luac -o instructions.txt
```

Every normal decompilation begins with a provenance header such as:

```luau
-- [[ ByteWeft v0.21.0.dev0 | decompiled at 2026-08-12T12:00:00Z | bytecode v9 | types v3 ]]
```

Use `--no-header` when a byte-for-byte deterministic body is needed. Setting
`SOURCE_DATE_EPOCH` makes the header timestamp reproducible.

The local API runs at `http://127.0.0.1:8000`; its documentation is at `/docs`.
The client in [`examples/api_script.luau`](examples/api_script.luau) can be used in
an authorized Roblox environment.

## How it works

```text
serialized Luau bytecode
  -> shared decode, CFG, dominance, scopes, and SSA
  -> effects, call frames, table ownership, captures, and proto ownership
  -> structured regions and semantic AST
  -> canonical Luau renderer
```

This release additionally fixes unreachable-instruction symbol analysis, generic
loop successor modeling, nested-loop ownership, reused-register lexical lifetimes,
mixed boolean guards, and call-valued table construction. Those fixes are based on
SSA values and CFG evidence; they do not replay historical physical registers.

## Compatibility and validation

- Luau bytecode versions 3 through 13;
- experimental version 100 class bytecode;
- Python 3.11, 3.12, and 3.13;
- native, Unluau, and portable Python backends;
- legacy `lunaux` CLI and `LUNAUX_*` environment variables remain supported.

The last published full corpus gate passed 2,304/2,304 semantic cases and 384/384
Medal-compatible cases with 100% syntax, recompilation, execution, stability, and
zero-fallback coverage. Correctness is a release constraint, not a readability
tradeoff.

See [CHANGELOG.md](CHANGELOG.md) for release details and [docs/](docs/) for the
architecture notes. Use ByteWeft only on bytecode you are authorized to inspect.

Licensed under the [Apache License 2.0](LICENSE).
