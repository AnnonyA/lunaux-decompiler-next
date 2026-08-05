# LunaUX Decompiler Next

A local Roblox Luau bytecode decompiler and disassembler with a native backend, the optional Unluau CLI, a portable Python engine, an HTTP API, a CLI, and a Windows launcher.

> **Version 0.6:** synchronizes the open engine with the current official Luau bytecode specification: standard bytecode versions 3–13, experimental class bytecode version 100, the complete 90-opcode table, structured type metadata, double-precision vectors, classes, userdata field opcodes, feedback slots, and stricter validation.

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
- Reconstructs common expressions, table access, calls, methods, returns, closures, numeric/generic loops, simple `while`/`repeat` regions, and common `if`/`else` layouts.
- Resolves modern userdata, class, fastcall, feedback, and proto operands in disassembly.
- Never executes submitted Luau bytecode.

## Windows quick start

Requirements:

- Windows 10 or 11;
- Python 3.11 or newer;
- Python 3.13 x64 only for the recovered Windows `luna.pyd`;
- Git and .NET SDK only when building Unluau from source.

Clone or download the repository and double-click:

```text
run.bat
```

In the launcher:

1. Select **Install / Update**.
2. Keep **Backend mode** on `auto`.
3. Optionally configure `luna.pyd` or an Unluau executable.
4. Select **Start server**.
5. Open **API docs**.

Default API address:

```text
http://127.0.0.1:8000
```

## Install the pinned Unluau source

LunaUX includes a reproducible installer for the reviewed upstream Unluau revision. It explicitly fetches the Apache-2.0 source, checks out the pinned commit, builds the CLI, copies its license, and writes a build manifest.

Windows x64:

```bat
py -3 scripts\install_unluau.py --runtime win-x64
```

Fetch only the pinned source:

```bat
py -3 scripts\install_unluau.py --source-only
```

The source is stored in `third_party/unluau` and the build in `tools/unluau`. Both generated directories are ignored by Git. LunaUX then detects the CLI automatically.

You may instead select an existing `Unluau.CLI.exe`, `Unluau.CLI.dll`, or compatible executable in the graphical launcher. See [`docs/UNLUAU.md`](docs/UNLUAU.md).

## Backend modes

| Mode | Behavior |
| --- | --- |
| `auto` | Native, then Unluau, then Python. Recommended. |
| `native` | Require the `luna` extension. |
| `unluau` | Require Unluau. |
| `reconstructed` | Use only the Python parser/lifter. |

Diagnostics:

```bat
.venv\Scripts\python.exe -m lunaux doctor
```

## File CLI

```bat
lunaux decompile input.luac -o recovered.luau
lunaux disassemble input.luac -o instructions.txt
```

Input can be raw bytecode or Base64 according to `--input-format`.

## API

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

Interactive documentation:

```text
http://127.0.0.1:8000/docs
```

Use [`examples/api_script.luau`](examples/api_script.luau) only in an authorized environment that supplies `request`, `getscriptbytecode`, and Base64 encoding.

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

The repository also checks its opcode, constant, builtin, and bytecode-version metadata against the current upstream `Luau/Bytecode.h` on a schedule. See [`scripts/check_luau_bytecode_spec.py`](scripts/check_luau_bytecode_spec.py).

## Accuracy and limitations

This update improves bytecode compatibility and semantic reconstruction, but bytecode does not preserve comments, exact formatting, every local name, or every original high-level control-flow choice. Optimized or irreducible patterns may still be represented conservatively with labels or comments. No decompiler can guarantee byte-for-byte recovery of the original source.

Only inspect scripts you own or are authorized to analyze.

## Third-party attribution

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Luau is MIT-licensed. Unluau is an Apache-2.0 project and remains separately attributed.
