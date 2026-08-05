# LunaUX Decompiler Next

A local Roblox Luau bytecode decompiler and disassembler with multiple independent engines, a request-compatible HTTP API, a command-line application, and a Windows graphical launcher.

> **Version 0.5:** adds optional [Unluau](https://github.com/atrexus/unluau) support and per-request fallback between the native LunaUX extension, Unluau, and the open Python engine.

## What changed

LunaUX Next no longer depends on a single decompiler implementation. In the recommended `auto` mode it builds this chain:

```text
compatible luna.pyd / luna.so
    -> Unluau CLI
    -> LunaUX pure-Python engine
```

The fallback is performed for every submitted script. If one engine is unavailable, crashes, times out, or produces empty output, LunaUX tries the next engine.

This improves recovery across different Roblox/Luau compiler generations without pretending that one decompiler is perfect.

## Features

- Parses serialized Luau bytecode versions 3 through 12.
- Supports the original native `luna.pyd` and `.so` extension.
- Supports the Apache-2.0 Unluau CLI as a separate optional process.
- Reconstructs common locals, globals, imports, calls, methods, tables, closures, conditions, and loops in Python.
- Resolves constants, properties, line numbers, prototypes, and jump targets in disassembly.
- Falls through to another engine when an individual file fails.
- Supports raw files and Base64 input.
- Provides classic plain-text API routes and structured `/v1` routes.
- Applies bytecode size, output size, filename, timeout, and reference validation.
- Never executes submitted Luau bytecode.
- Never silently downloads native or external decompiler binaries.

## Windows quick start

Requirements:

- Windows 10 or 11;
- Python 3.11 or newer;
- Python 3.13 x64 only when using the recovered Windows `luna.pyd`.

Clone or download the repository and double-click:

```text
run.bat
```

In the launcher:

1. Select **Install / Update**.
2. Keep the backend mode on **auto**.
3. Optionally configure `luna.pyd` or Unluau.
4. Select **Start server**.
5. Open **API docs** or copy the local API URL.

The default address is:

```text
http://127.0.0.1:8000
```

## Add Unluau

Unluau is optional and is not bundled in this repository.

Place an authorized upstream build in one of these locations:

```text
tools/unluau/unluau.exe
tools/unluau/Unluau.CLI.exe
tools/unluau/Unluau.CLI.dll
```

LunaUX detects it automatically. You can also set an explicit path:

```bat
set LUNAUX_UNLUAU_PATH=C:\Tools\Unluau.CLI.exe
```

For a framework-dependent DLL:

```bat
set LUNAUX_UNLUAU_PATH=C:\Tools\Unluau.CLI.dll
```

DLL builds require `dotnet` in PATH. Self-contained `.exe` builds do not.

Run diagnostics:

```bat
.venv\Scripts\python.exe -m lunaux doctor
```

Detailed instructions are in [`docs/UNLUAU.md`](docs/UNLUAU.md).

## Backend modes

| Mode | Behavior |
| --- | --- |
| `auto` | Native, then Unluau, then Python. Recommended. |
| `native` | Require the `luna` Python extension. |
| `unluau` | Require the external Unluau CLI. |
| `reconstructed` | Use only the LunaUX Python engine. |

Set a mode temporarily on Windows:

```bat
set LUNAUX_BACKEND_MODE=unluau
lunaux doctor
```

Linux/macOS:

```bash
export LUNAUX_BACKEND_MODE=auto
export LUNAUX_UNLUAU_PATH=$HOME/tools/unluau/Unluau.CLI
lunaux doctor
```

## Why Unluau is isolated

LunaUX does not import or execute Unluau inside the API process. For each request it:

1. creates a private temporary directory;
2. writes the submitted bytecode there;
3. invokes the CLI without a shell;
4. captures output and errors;
5. enforces a timeout;
6. removes the temporary directory.

The adapter enables Unluau's table inlining, variable-name guessing, and upvalue renaming options to improve readability.

## Pure-Python engine

The built-in engine remains available on every supported platform and does not require external binaries. It contains:

1. a validated Luau container parser;
2. an instruction and AUX-word decoder;
3. a register-aware source lifter;
4. enriched disassembly and debug metadata recovery.

See [`docs/PYTHON_ENGINE.md`](docs/PYTHON_ENGINE.md) for supported constants, opcodes, metadata, and limitations.

## Native LunaUX engine

Windows CPython 3.13 x64 example:

```bat
set LUNAUX_BACKEND_MODE=auto
set LUNAUX_BACKEND_MODULE=luna
set LUNAUX_NATIVE_PATH=C:\path\to\luna.pyd
lunaux doctor
```

Linux CPython 3.12 x86-64 example:

```bash
export LUNAUX_BACKEND_MODE=auto
export LUNAUX_BACKEND_MODULE=luna
export LUNAUX_NATIVE_PATH=$HOME/path/to/luna-linux.so
lunaux doctor
```

The module name must match its exported Python initializer. A binary exporting `PyInit_luna` must use the module name `luna`.

## API client

Start the server:

```bat
run.bat
```

or manually:

```bash
lunaux run
```

Use [`examples/api_script.luau`](examples/api_script.luau) in an authorized environment that provides:

```text
request
getscriptbytecode
base64encode or crypt.base64.encode
```

Classic routes return plain text:

```text
GET  /health
POST /decompile
POST /disassemble
POST /decomp
POST /disasm
```

Structured routes return JSON with backend metadata:

```text
GET  /v1/health
POST /v1/decompile
POST /v1/disassemble
```

Interactive documentation:

```text
http://127.0.0.1:8000/docs
```

## Decompilation options

The API accepts PascalCase and snake_case names.

| Option | Default | Purpose |
| --- | --- | --- |
| `Semicolons` | `false` | Add semicolons when supported. |
| `StringInterpolation` | `true` | Prefer Luau interpolation. |
| `UpvalueComment` | `true` | Show known upvalues/captures. |
| `ShowLineDefined` | `true` | Show prototype definition lines. |
| `ShowFunctionId` | `false` | Show prototype IDs. |
| `PreserveForStep` | `false` | Preserve numeric loop steps. |
| `UseIfExpression` | `true` | Prefer conditional expressions. |
| `MaxOutputCharacters` | `4000000` | Reject unexpectedly large output. |

Each engine supports a different subset. Unsupported formatting preferences do not change the bytecode analysis itself.

## CLI

```text
lunaux run
lunaux serve
lunaux decomp input.luac output-folder
lunaux disasm input.luac output-folder
lunaux doctor
lunaux -v
lunaux -ih
```

Exact output paths are supported with `-o`:

```bat
lunaux decompile input.luac -o recovered.luau
lunaux disassemble input.luac -o instructions.txt
```

## Manual installation

Windows:

```bat
py -3.13 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .
lunaux run
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
lunaux run
```

Development:

```bash
pip install -e ".[dev]"
ruff check .
mypy
pytest
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LUNAUX_BACKEND_MODE` | `auto` | `auto`, `native`, `unluau`, or `reconstructed`. |
| `LUNAUX_BACKEND_MODULE` | `luna` | Native Python extension name. |
| `LUNAUX_NATIVE_PATH` | empty | Path to `.pyd` or `.so`. |
| `LUNAUX_UNLUAU_PATH` | auto-detect | Path to Unluau executable or `.dll`. |
| `LUNAUX_EXTERNAL_TIMEOUT_SECONDS` | `45` | External engine timeout per operation. |
| `LUNAUX_MAX_BYTECODE_BYTES` | `16777216` | Maximum accepted bytecode size. |
| `LUNAUX_CORS_ORIGINS` | empty | Comma-separated browser origins. |

## Limitations

Decompilation cannot recover information that bytecode does not contain. Comments, exact formatting, and many original temporary names are permanently lost.

Unluau is an alpha project and can fail on newer or heavily optimized bytecode. The Python lifter is intentionally conservative and may emit labels or explanatory comments for ambiguous control flow. The native extension may also be tied to a specific Python ABI and operating system.

The multi-engine chain improves coverage, but it does not guarantee the original source code.

Only inspect bytecode you own or are authorized to analyze.

## Third-party attribution

- Luau is distributed under the MIT License.
- Unluau is a separate Apache-2.0 project and is not redistributed by LunaUX Next.
- LunaUX Next is distributed under the repository's Apache-2.0 license.
