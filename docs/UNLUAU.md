# Unluau integration

LunaUX Next 0.5 can use [atrexus/unluau](https://github.com/atrexus/unluau) as an optional external decompilation engine.

Unluau is not copied into this repository and no binary is downloaded automatically. The upstream project is licensed under Apache-2.0 and remains a separate program. LunaUX communicates with its command-line interface through a restricted subprocess call.

## Why use it

The pure-Python LunaUX engine is portable and conservative. Unluau has a larger source lifter for several older/common Roblox Luau compiler patterns, including table reconstruction and variable-name guessing. Neither engine is perfect, so `auto` mode uses a chain:

```text
compatible luna native extension
    -> Unluau CLI
    -> LunaUX pure-Python engine
```

Fallback happens for each request. If Unluau is installed but fails or returns empty output for one script, LunaUX tries the Python engine instead of failing the whole request.

## Windows setup

1. Obtain or build an authorized Unluau CLI release from the upstream repository.
2. Put the executable in one of these locations:

```text
tools/unluau/unluau.exe
tools/unluau/Unluau.CLI.exe
unluau/Unluau.CLI.exe
```

Alternatively, set an explicit path:

```bat
set LUNAUX_UNLUAU_PATH=C:\Tools\Unluau.CLI.exe
```

Then use the normal launcher:

```text
run.bat
```

Keep `Backend mode` set to `auto`. Run diagnostics from the GUI or command line:

```bat
.venv\Scripts\python.exe -m lunaux doctor
```

## Framework-dependent DLL

A `.NET` build can also be configured:

```bat
set LUNAUX_UNLUAU_PATH=C:\Tools\Unluau.CLI.dll
```

LunaUX will invoke it as:

```text
dotnet C:\Tools\Unluau.CLI.dll
```

The `dotnet` command must be available in PATH for DLL builds. Self-contained `.exe` releases do not need a separate .NET runtime.

## Linux setup

Place an executable named `unluau`, `Unluau.CLI`, or a compatible DLL in PATH or under `tools/unluau`, then optionally configure:

```bash
export LUNAUX_UNLUAU_PATH=$HOME/tools/unluau/Unluau.CLI
export LUNAUX_BACKEND_MODE=auto
```

## Modes

| Mode | Behavior |
| --- | --- |
| `auto` | Native, then Unluau, then Python. Recommended. |
| `native` | Require the `luna` Python extension. |
| `unluau` | Require Unluau and report its errors directly. |
| `reconstructed` | Use only the LunaUX Python engine. |

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `LUNAUX_UNLUAU_PATH` | auto-detect | Executable or `.dll` path. |
| `LUNAUX_EXTERNAL_TIMEOUT_SECONDS` | `45` | Maximum time allowed for one external operation. |
| `LUNAUX_BACKEND_MODE` | `auto` | Select the engine policy. |

## Process isolation

For every request LunaUX:

1. creates a private temporary directory;
2. writes only the submitted bytecode there;
3. invokes Unluau without a shell;
4. captures standard output and standard error;
5. applies a timeout;
6. reads the generated source;
7. removes the temporary directory.

Submitted bytecode is never executed by LunaUX or loaded into the Luau VM.

## Output options

LunaUX enables the following Unluau options for more readable output:

```text
--inline-tables
--smart-variable-names
--rename-upvalues
```

`StringInterpolation=false` is also forwarded when requested through the LunaUX API. Options that Unluau does not support remain handled by the other engines or are ignored by that engine.

## Limitations

Unluau is an alpha project and may fail on newer or heavily optimized bytecode. Its upstream README states that complex scripts can expose bugs. LunaUX therefore treats it as one engine in a chain rather than as an infallible replacement.

Use decompilation only for scripts you own or are authorized to inspect.
