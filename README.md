# LunaUX Decompiler Next

A local Luau bytecode decompiler and disassembler with a native-first backend, a portable Python fallback, a request-compatible API, and a command-line application.

> **Version 0.3:** adds classic `/decompile` and `/disassemble` routes that return plain text, PascalCase API options, the `run`, `decomp`, and `disasm` CLI aliases, and an installation hash flag.

## Features

- Uses a compatible native `luna.pyd` or `.so` for complete decompilation.
- Loads an authorized native extension directly through `LUNAUX_NATIVE_PATH`.
- Falls back to a readable Python Luau instruction decoder when native loading fails.
- Supports raw bytecode and Base64-encoded bytecode.
- Provides plain-text compatibility routes for request-based Luau clients.
- Keeps the structured, versioned `/v1` API for applications that need backend metadata.
- Validates Base64, input size, filenames, options, and output size.
- Never downloads native binaries or modifies its own installation at runtime.

The Python fallback is intentionally conservative. It does not claim that heuristic output is recovered source. Complete serialized-container decompilation still requires a compatible native backend.

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

## Native backend

LunaUX Next supports three backend modes:

| Mode | Behavior |
| --- | --- |
| `auto` | Try native first, then use the Python fallback. This is the default. |
| `native` | Require the native extension and fail if it cannot load. |
| `reconstructed` | Skip native loading and always use the Python fallback. |

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

The module name must match the exported initializer. A binary exporting `PyInit_luna` must use `LUNAUX_BACKEND_MODULE=luna`.

## API Script

Start the local server first:

```bash
lunaux run
```

Then paste [`examples/api_script.luau`](examples/api_script.luau) into an authorized environment that supports `request`, `getscriptbytecode`, and either `base64encode` or `crypt.base64.encode`.

```luau
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

The client calls these plain-text endpoints:

```text
POST /decompile
POST /disassemble
```

Successful responses use `Content-Type: text/plain`, so `response.Body` is directly the decompiled source or disassembly.

The following short route aliases are also available:

```text
POST /decomp
POST /disasm
```

## API Options

Pass options inside the `options` object sent to `/decompile` or `/v1/decompile`.

| Option | Default | Description |
| --- | --- | --- |
| `Semicolons` | `false` | Add a semicolon to every generated line. |
| `StringInterpolation` | `true` | Reconstruct string interpolation when supported. |
| `UpvalueComment` | `true` | Show the upvalues used by a function. |
| `ShowLineDefined` | `true` | Add the original prototype line information. |
| `ShowFunctionId` | `false` | Add the original function ID. `ShowLineDefined` should remain enabled. |
| `PreserveForStep` | `false` | Preserve the numeric-loop step even when it equals one. |
| `UseIfExpression` | `true` | Use `if ... then ... else ...` expressions instead of AND/OR reconstruction. |
| `MaxOutputCharacters` | `4000000` | Reject unexpectedly large backend output. Range: 1,000–20,000,000. |

Classic PascalCase and Python-style snake_case names are both accepted. For example, `StringInterpolation` and `string_interpolation` are equivalent.

Example request:

```json
{
  "bytecode": "BASE64_DATA",
  "filename": "Example.luau",
  "options": {
    "Semicolons": false,
    "StringInterpolation": true,
    "UpvalueComment": true,
    "ShowLineDefined": true,
    "ShowFunctionId": false,
    "PreserveForStep": false,
    "UseIfExpression": true
  }
}
```

## Structured API

Applications that need backend metadata can use the versioned routes:

```text
GET  /v1/health
POST /v1/decompile
POST /v1/disassemble
```

The versioned routes return JSON:

```json
{
  "result": "-- decompiled output",
  "backend": "luna",
  "backend_version": "..."
}
```

Compatibility health is also available at:

```text
GET /health
```

Interactive API documentation is served at `/docs` and `/redoc`.

## CLI Application

Tool for quick local analysis, automation, or starting the API server. File commands support raw bytecode and Base64-encoded bytecode.

```text
Options:
  -h, --help       Show the help message.
  -v, --version    Show version information.
  -ih, --hash      Show the current installation SHA-256.

Commands:
  run
    Start the LunaUX Next local server.

  serve
    Alias-compatible server command with the same host and port options.

  decomp, decompile <input_file> [output_directory]
    Decompile the specified bytecode file.
    If an output directory is supplied, the result is saved as <name>.luau.
    Otherwise, the result is printed to the console.

  disasm, disassemble <input_file> [output_directory]
    Disassemble the specified bytecode file.
    If an output directory is supplied, the result is saved as <name>.disasm.txt.
    Otherwise, the result is printed to the console.

  doctor
    Show Python, backend, native extension, and fallback diagnostics.
```

Examples:

```bash
lunaux run
lunaux decomp script.luac output
lunaux decompile script.txt output --input-format base64
lunaux disasm script.luac output
lunaux disassemble script.luac -o instructions.txt
lunaux doctor
lunaux -v
lunaux -ih
```

Input formats:

- `raw`: preserve the file bytes exactly.
- `base64`: require valid Base64 and decode it.
- `auto`: conservatively detect canonical Base64; otherwise use raw bytes.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LUNAUX_BACKEND_MODE` | `auto` | Select `auto`, `native`, or `reconstructed`. |
| `LUNAUX_BACKEND_MODULE` | `luna` | Native import and initializer name. |
| `LUNAUX_NATIVE_PATH` | empty | Direct path to a compatible `.pyd` or `.so`. |
| `LUNAUX_MAX_BYTECODE_BYTES` | `16777216` | Maximum accepted bytecode size. |
| `LUNAUX_CORS_ORIGINS` | empty | Comma-separated allowed API origins. |

## Repository layout

```text
examples/
└── api_script.luau       # Request-based Luau client

src/lunaux/
├── api/                  # FastAPI application and request models
├── backends/
│   ├── auto.py           # Native-first backend selection
│   ├── base.py           # Backend protocol
│   ├── native.py         # Installed-module and direct-path native loader
│   ├── opcodes.py        # Pure Python Luau word decoder
│   └── reconstructed.py  # Conservative portable fallback
├── cli.py                # CLI, aliases, server launcher, global flags
├── config.py             # Environment-backed configuration
├── errors.py             # Stable public error codes
├── hashing.py            # Deterministic installation SHA-256
├── io.py                 # Raw/Base64 input handling
├── models.py             # Decompilation options and API aliases
└── service.py            # Validation and orchestration
```

## Native backend interface

A compatible native module must expose:

```python
decompile_bytecode(bytecode: bytes, options: dict, filename: str | None) -> str
disassemble_bytecode(bytecode: bytes, filename: str | None) -> str
```

The adapter reads `__version__` or calls `get_version()` when available.

## Testing

```bash
pytest
ruff check .
mypy
```

CI validates the project on Windows, Ubuntu, and macOS with Python 3.11, 3.12, and 3.13.

## Attribution

This project is an independent redesign inspired by the public LunaUX-Decompiler repository by `boydev-1444` and contributors. See [`NOTICE`](NOTICE). It is not an official release of the original project.

The Python reconstruction is a behavioral interoperability layer based on analysis material supplied for this project. It is not the original Cython source.

## Responsible use

Only analyze bytecode you own or are authorized to inspect. Decompilation cannot restore comments, original local names, exact formatting, or server-only source code that was never present in the supplied bytecode.

## License

Apache License 2.0. See [`LICENSE`](LICENSE). Rights to separately supplied native binaries remain with their respective owners.
