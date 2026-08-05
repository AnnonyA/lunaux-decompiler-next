# LunaUX Decompiler Next

A local Luau bytecode decompiler and disassembler with a native-first backend, a portable pure-Python engine, a request-compatible API, and a Windows graphical launcher.

> **Version 0.4:** adds a serialized Luau bytecode parser, prototype and constant recovery, heuristic Luau source reconstruction, enriched disassembly, and a complete `run.bat` + `installer.py` experience for Windows.

## Highlights

- Parses serialized Luau bytecode containers instead of treating every input as raw words.
- Reads string tables, prototypes, constants, child closures, source lines, locals, and upvalues.
- Reconstructs common assignments, expressions, tables, calls, methods, returns, closures, conditionals, and loops.
- Resolves constant names, imports, properties, line numbers, and jump targets in disassembly.
- Supports raw bytecode and Base64-encoded input.
- Uses a compatible native `luna.pyd` or `.so` first when configured.
- Continues with the Python engine when native loading is unavailable.
- Provides classic plain-text routes and a structured versioned API.
- Validates Base64, file names, input size, references, collection counts, and output size.
- Never executes submitted Luau bytecode.
- Never downloads native binaries or silently modifies its own installation.

The Python engine understands the public serialized layout used by Luau bytecode versions 3 through 12. Source reconstruction remains heuristic: bytecode does not preserve comments, exact formatting, every original local name, or all high-level control-flow choices.

## Windows quick start

Requirements:

- Windows 10 or 11;
- Python 3.11 or newer;
- Python 3.13 x64 when using the recovered Windows native backend.

Clone or download the repository, then double-click:

```text
run.bat
```

The launcher opens a graphical interface where you can:

1. Select **Install / Update** to create `.venv` and install LunaUX Next.
2. Optionally select a compatible `luna.pyd` under **Native backend**.
3. Choose `auto`, `native`, or `reconstructed` mode.
4. Select **Start server**.
5. Open the API documentation or copy the local API URL.

The launcher also includes diagnostics, live logs, server status, persistent host/port settings, and safe server shutdown.

### Manual Windows installation

```bat
py -3.13 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .
```

Start the server:

```bat
lunaux run
```

## Linux and macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
lunaux run
```

For development:

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy
```

## Decompiler backends

`LUNAUX_BACKEND_MODE` controls startup behavior:

| Mode | Behavior |
| --- | --- |
| `auto` | Try the native extension first, then use the Python engine. Default. |
| `native` | Require a compatible native extension and fail clearly otherwise. |
| `reconstructed` | Skip native loading and always use the Python engine. |

Run diagnostics:

```bash
lunaux doctor
```

### Windows native backend

The recovered Windows extension targets CPython 3.13 x64:

```bat
set LUNAUX_BACKEND_MODE=auto
set LUNAUX_BACKEND_MODULE=luna
set LUNAUX_NATIVE_PATH=C:\path\to\luna.pyd
lunaux doctor
```

### Linux native backend

The recovered Linux extension targets CPython 3.12 x86-64:

```bash
export LUNAUX_BACKEND_MODE=auto
export LUNAUX_BACKEND_MODULE=luna
export LUNAUX_NATIVE_PATH=$HOME/path/to/luna-linux.so
lunaux doctor
```

The module name must match its initializer. A binary exporting `PyInit_luna` must use `LUNAUX_BACKEND_MODULE=luna`.

Native binaries are not committed or downloaded by the application. Keep authorized binaries locally and label them with their operating system, architecture, Python ABI, and hash.

## Pure-Python engine

The open engine has three stages:

1. **Container parser** — validates the Luau header and reads strings, prototypes, code, constants, debug information, line information, and child-prototype links.
2. **Instruction decoder** — interprets Luau instruction fields and AUX words.
3. **Source lifter** — tracks registers and reconstructs common Luau statements and expressions.

Commonly reconstructed features include:

- nil, booleans, numbers, strings, vectors, imports, and closures;
- globals, locals, upvalues, tables, fields, and indexed accesses;
- arithmetic, boolean operators, concatenation, unary operators, and length;
- function calls, method calls, varargs, and multiple returns;
- child functions and captures;
- forward conditional regions;
- numeric and generic loops when their shape is recognizable.

Unsupported or ambiguous optimized patterns are emitted as comments or labeled control flow rather than fabricated source. See [`docs/PYTHON_ENGINE.md`](docs/PYTHON_ENGINE.md) for format details and current limitations.

## API script

Start the local server first:

```bash
lunaux run
```

Then use [`examples/api_script.luau`](examples/api_script.luau) in an authorized environment that provides `request`, `getscriptbytecode`, and either `base64encode` or `crypt.base64.encode`.

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

Successful classic responses use `Content-Type: text/plain`, so `response.Body` directly contains the source or disassembly.

Routes:

```text
POST /decompile
POST /disassemble
POST /decomp
POST /disasm
```

## Decompilation options

Pass options inside the `options` object sent to `/decompile` or `/v1/decompile`.

| Option | Default | Description |
| --- | --- | --- |
| `Semicolons` | `false` | Add semicolons to generated statements. |
| `StringInterpolation` | `true` | Request interpolation reconstruction when supported. |
| `UpvalueComment` | `true` | Show known function upvalues and captures. |
| `ShowLineDefined` | `true` | Show the original prototype definition line. |
| `ShowFunctionId` | `false` | Show the original prototype ID. |
| `PreserveForStep` | `false` | Keep the numeric-loop step when reconstructable. |
| `UseIfExpression` | `true` | Prefer Luau conditional expressions when supported. |
| `MaxOutputCharacters` | `4000000` | Maximum accepted backend output size. |

PascalCase and snake_case forms are both accepted.

## Structured API

Applications needing backend metadata can use:

```text
GET  /v1/health
POST /v1/decompile
POST /v1/disassemble
```

Example response:

```json
{
  "result": "-- decompiled output",
  "backend": "python-reconstruction",
  "backend_version": "0.4.0"
}
```

Compatibility health is available at `GET /health`. Interactive documentation is served at `/docs` and `/redoc`.

## CLI application

```text
Options:
  -h, --help       Show help.
  -v, --version    Show version information.
  -ih, --hash      Show the current installation SHA-256.

Commands:
  run
    Start the local API server.

  serve
    Start the same server with explicit options.

  decomp, decompile <input_file> [output_directory]
    Decompile raw or Base64-encoded bytecode.

  disasm, disassemble <input_file> [output_directory]
    Disassemble raw or Base64-encoded bytecode.

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

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LUNAUX_BACKEND_MODE` | `auto` | Select `auto`, `native`, or `reconstructed`. |
| `LUNAUX_BACKEND_MODULE` | `luna` | Native import and initializer name. |
| `LUNAUX_NATIVE_PATH` | empty | Path to a compatible `.pyd` or `.so`. |
| `LUNAUX_MAX_BYTECODE_BYTES` | `16777216` | Maximum accepted bytecode size. |
| `LUNAUX_CORS_ORIGINS` | empty | Comma-separated allowed API origins. |

## Repository layout

```text
run.bat                         # Windows double-click launcher
installer.py                    # Tkinter installer and server dashboard
examples/api_script.luau        # Request-based Luau client

src/lunaux/
├── api/                        # FastAPI routes and request models
├── backends/
│   ├── auto.py                 # Native-first selection
│   ├── base.py                 # Backend protocol
│   ├── bytecode.py             # Serialized Luau container parser
│   ├── lifter.py               # Heuristic Luau source reconstruction
│   ├── native.py               # Native module/path loader
│   ├── opcodes.py              # Instruction decoder
│   └── reconstructed.py        # Pure-Python backend orchestration
├── cli.py                      # CLI and server commands
├── config.py                   # Environment configuration
├── errors.py                   # Stable error codes
├── hashing.py                  # Installation SHA-256
├── io.py                       # Raw/Base64 handling
├── models.py                   # Shared options
└── service.py                  # Validation and orchestration
```

## Testing

```bash
pytest
ruff check .
mypy
```

CI validates Windows, Ubuntu, and macOS with Python 3.11, 3.12, and 3.13.

## Attribution and responsible use

This project is an independent redesign inspired by the public LunaUX-Decompiler repository by `boydev-1444` and contributors. See [`NOTICE`](NOTICE). It is not an official release of the original project.

Only analyze bytecode you own or are authorized to inspect. A decompiler cannot restore comments, original formatting, exact temporary names, or server-only source that was never present in the supplied bytecode.

## License

Apache License 2.0. See [`LICENSE`](LICENSE). Rights to separately supplied native binaries remain with their respective owners.
