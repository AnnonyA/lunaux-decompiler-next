# LunaUX Decompiler Next

A clean, testable interface for Luau bytecode decompilation and disassembly.

> **Project status:** early development. The public repository contains the CLI, HTTP API, validation layer, backend interface, tests, and release tooling. The original LunaUX native decompiler engine is **not** reimplemented here; it can be loaded as an optional compatibility backend when a supported `luna` module is installed.

## Why this repository exists

The original LunaUX project proved that a free local Luau decompilation workflow could be practical, but its public repository mixed installation, dependency management, API hosting, terminal output, and binary delivery in one script. LunaUX Next separates those responsibilities so each part can be reviewed and tested independently.

## Highlights

- Versioned HTTP API under `/v1`.
- Typed request and response models.
- Strict input-size limits and consistent error codes.
- No automatic `pip install` or self-modifying installer.
- CLI that calls the backend directly; no local server is required for file operations.
- Pluggable backend interface for native and future open implementations.
- CI for Windows, Linux, and macOS.
- Tests for input decoding, service validation, and API behavior.
- CORS disabled by default.

## Installation

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
pytest
```

## Native backend

LunaUX Next looks for a Python module named `luna` by default. A compatible module must expose:

```python
decompile_bytecode(bytecode: bytes, options: dict, filename: str | None) -> str
disassemble_bytecode(bytecode: bytes, filename: str | None) -> str
```

You can select a different module with:

```bash
# Windows PowerShell
$env:LUNAUX_BACKEND_MODULE = "my_luau_backend"

# Linux/macOS
export LUNAUX_BACKEND_MODULE=my_luau_backend
```

Check availability with:

```bash
lunaux doctor
```

See [`docs/NATIVE_BACKEND.md`](docs/NATIVE_BACKEND.md) for details.

## CLI

```bash
lunaux decompile script.luac -o script.luau
lunaux disassemble script.txt --input-format base64
lunaux serve --host 127.0.0.1 --port 8000
lunaux doctor
```

Input formats:

- `raw`: input is Luau bytecode.
- `base64`: input is Base64 text.
- `auto`: conservative Base64 detection, otherwise raw bytes.

Use an explicit input format for untrusted or ambiguous files.

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

The server binds to `127.0.0.1` by default. CORS is disabled unless `LUNAUX_CORS_ORIGINS` is configured.

## Repository layout

```text
src/lunaux/
├── api/          # FastAPI application and request models
├── backends/     # Backend protocol and native compatibility adapter
├── cli.py        # Typer CLI
├── config.py     # Environment-backed configuration
├── errors.py     # Stable public error codes
├── io.py         # Raw/Base64 input handling
├── models.py     # Shared decompilation options
└── service.py    # Validation and orchestration
```

The intended long-term pipeline for an open decompiler engine is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Attribution

This project is an independent redesign inspired by the public LunaUX-Decompiler repository by `boydev-1444` and contributors. See [`NOTICE`](NOTICE). It is not an official release of the original project.

## Responsible use

Only analyze bytecode you own or are authorized to inspect. Decompilation does not restore comments, original local names, source formatting, or server-only source code that was never present in the provided bytecode.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
