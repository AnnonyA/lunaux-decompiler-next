# LunaUX Decompiler Next

A clean CLI and HTTP API for Luau bytecode analysis with automatic native compatibility and a portable Python fallback.

> **Version 0.2:** LunaUX Next now tries the exact native `luna` engine when available, can load a `.pyd` or `.so` directly by path, and falls back to a readable Python instruction decoder instead of refusing to start.

## What it does

- Decompiles Luau bytecode through a compatible native LunaUX extension.
- Disassembles raw 32-bit Luau instruction streams without a native binary.
- Reports metadata and printable strings for unsupported serialized containers.
- Exposes the same backend through a local CLI and versioned HTTP API.
- Validates input sizes, filenames, Base64 payloads, and output limits.
- Never downloads native binaries or modifies its own installation at runtime.

The Python fallback is intentionally conservative. It does not present guessed pseudocode as recovered source. Complete serialized-container decompilation still requires a compatible native backend.

## Installation

```bash
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
pytest
```

## Backend selection

`LUNAUX_BACKEND_MODE` controls how LunaUX Next starts:

| Mode | Behavior |
| --- | --- |
| `auto` | Try native first, then activate the Python fallback. This is the default. |
| `native` | Require the native extension and fail clearly if it cannot load. |
| `reconstructed` | Skip native loading and always use the Python fallback. |

Run diagnostics at any time:

```bash
lunaux doctor
```

The diagnostics show the active backend, version, configured native path, and the reason for any fallback.

## Use the recovered `luna.pyd` on Windows

The recovered Windows extension targets **CPython 3.13 x64**. Use a matching interpreter.

CMD:

```bat
set LUNAUX_BACKEND_MODE=auto
set LUNAUX_BACKEND_MODULE=luna
set LUNAUX_NATIVE_PATH=C:\path\to\luna.pyd
lunaux doctor
```

PowerShell:

```powershell
$env:LUNAUX_BACKEND_MODE = "auto"
$env:LUNAUX_BACKEND_MODULE = "luna"
$env:LUNAUX_NATIVE_PATH = "C:\path\to\luna.pyd"
lunaux doctor
```

A `.pyd` is a native Python extension. Its Python version, architecture, operating system, and exported initializer must match the current interpreter.

## Use the recovered `.so` on Linux

The recovered Linux extension targets **CPython 3.12 x86-64**.

```bash
export LUNAUX_BACKEND_MODE=auto
export LUNAUX_BACKEND_MODULE=luna
export LUNAUX_NATIVE_PATH=$HOME/path/to/luna-linux.so
lunaux doctor
```

Both recovered binaries export `PyInit_luna`, so the module name must remain `luna` even when the file is named `luna-linux.so`.

Native binaries are not committed to this repository. Keep them locally or distribute authorized artifacts separately with hashes and ABI labels.

## CLI

Decompile a raw bytecode file:

```bash
lunaux decompile script.luac -o script.luau
```

Disassemble:

```bash
lunaux disassemble script.luac -o instructions.txt
```

Read Base64 text explicitly:

```bash
lunaux decompile script.txt --input-format base64 -o script.luau
```

Start the API:

```bash
lunaux serve --host 127.0.0.1 --port 8000
```

Input formats:

- `raw`: preserve the file bytes exactly.
- `base64`: require valid Base64 and decode it.
- `auto`: conservatively detect canonical Base64; otherwise use raw bytes.

Use an explicit format for untrusted or ambiguous files.

## Fallback output

When the native backend is unavailable, `auto` mode selects `python-reconstruction`.

For a raw word stream it prints decoded instructions with:

- program counter;
- raw 32-bit word;
- opcode name;
- `A`, `B`, `C`, `D`, and `E` fields;
- auxiliary words for opcodes that use them.

For a complete serialized container that the fallback cannot parse, it returns structured metadata rather than false source code. Switch to a matching native runtime for complete decompilation.

Force fallback mode:

Windows CMD:

```bat
set LUNAUX_BACKEND_MODE=reconstructed
lunaux disassemble script.luac
```

Linux/macOS:

```bash
export LUNAUX_BACKEND_MODE=reconstructed
lunaux disassemble script.luac
```

## HTTP API

Start the server:

```bash
lunaux serve
```

Health check:

```text
GET /v1/health
```

Decompile:

```text
POST /v1/decompile
Content-Type: application/json
```

```json
{
  "bytecode": "BASE64_DATA",
  "filename": "Example.luau",
  "options": {
    "string_interpolation": true,
    "use_if_expression": true
  }
}
```

Disassemble:

```text
POST /v1/disassemble
```

The response reports the backend name and backend version. The server binds to `127.0.0.1` by default, and CORS is disabled unless `LUNAUX_CORS_ORIGINS` is configured.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LUNAUX_BACKEND_MODE` | `auto` | Select `auto`, `native`, or `reconstructed`. |
| `LUNAUX_BACKEND_MODULE` | `luna` | Import name and native initializer name. |
| `LUNAUX_NATIVE_PATH` | empty | Direct path to a compatible `.pyd` or `.so`. |
| `LUNAUX_MAX_BYTECODE_BYTES` | `16777216` | Maximum accepted bytecode size. |
| `LUNAUX_CORS_ORIGINS` | empty | Comma-separated allowed API origins. |

## Repository layout

```text
src/lunaux/
├── api/                  # FastAPI application and request models
├── backends/
│   ├── auto.py           # Native-first backend selection
│   ├── base.py           # Backend protocol
│   ├── native.py         # Installed-module and direct-path native loader
│   ├── opcodes.py        # Pure Python Luau word decoder
│   └── reconstructed.py  # Conservative portable fallback
├── cli.py                # Typer CLI and diagnostics
├── config.py             # Environment-backed configuration
├── errors.py             # Stable public error codes
├── io.py                 # Raw/Base64 input handling
├── models.py             # Shared decompilation options
└── service.py            # Validation and orchestration
```

See [`docs/NATIVE_BACKEND.md`](docs/NATIVE_BACKEND.md) for native loading details and [`ARCHITECTURE.md`](ARCHITECTURE.md) for the long-term open-engine design.

## Native backend interface

A compatible module must expose:

```python
decompile_bytecode(bytecode: bytes, options: dict, filename: str | None) -> str
disassemble_bytecode(bytecode: bytes, filename: str | None) -> str
```

The adapter reads `__version__` or calls `get_version()` when available.

## Testing

```bash
pytest
```

The suite covers input decoding, service validation, HTTP behavior, backend fallback, raw opcode decoding, and prevention of misleading serialized-container output.

## Attribution

This project is an independent redesign inspired by the public LunaUX-Decompiler repository by `boydev-1444` and contributors. See [`NOTICE`](NOTICE). It is not an official release of the original project.

The Python reconstruction is a behavioral interoperability layer based on analysis material supplied for this project. It is not the original Cython source.

## Responsible use

Only analyze bytecode you own or are authorized to inspect. Decompilation cannot restore comments, original local names, exact formatting, or server-only source code that was never present in the provided bytecode.

## License

Apache License 2.0. See [`LICENSE`](LICENSE). Rights to separately supplied native binaries remain with their respective owners.
