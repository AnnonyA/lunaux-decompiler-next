# Native backend compatibility

LunaUX Next 0.2 can use a native `luna` extension either as an installed Python module or from an explicit `.pyd`/`.so` path. Native binaries are not committed or downloaded automatically.

## Backend modes

Set `LUNAUX_BACKEND_MODE` to one of:

- `auto` (default): try the native extension, then use the Python reconstruction if loading fails.
- `native`: require the native extension and return an error if it cannot load.
- `reconstructed`: skip native loading and use the open Python fallback.

## Loading an installed module

The default module name is `luna`. Change it with `LUNAUX_BACKEND_MODULE`.

```powershell
$env:LUNAUX_BACKEND_MODE = "native"
$env:LUNAUX_BACKEND_MODULE = "luna"
lunaux doctor
```

## Loading a `.pyd` or `.so` directly

Use `LUNAUX_NATIVE_PATH` when the extension is not installed into the active environment.

Windows CMD:

```bat
set LUNAUX_BACKEND_MODE=auto
set LUNAUX_BACKEND_MODULE=luna
set LUNAUX_NATIVE_PATH=C:\tools\lunaux\luna.pyd
lunaux doctor
```

Linux:

```bash
export LUNAUX_BACKEND_MODE=auto
export LUNAUX_BACKEND_MODULE=luna
export LUNAUX_NATIVE_PATH=$HOME/lunaux/luna-linux.so
lunaux doctor
```

The extension filename may vary, but the module name must match its exported initializer. A binary that exports `PyInit_luna` must be loaded with `LUNAUX_BACKEND_MODULE=luna`.

Native extensions are ABI-specific. A CPython 3.13 Windows x64 `.pyd`, for example, cannot be loaded by CPython 3.12 or a 32-bit interpreter.

## Required functions

```python
def decompile_bytecode(
    bytecode: bytes,
    options: dict[str, bool],
    filename: str | None,
) -> str: ...


def disassemble_bytecode(
    bytecode: bytes,
    filename: str | None,
) -> str: ...
```

The adapter also reads `__version__` or calls `get_version()` when available.

## Reconstructed fallback

The Python backend decodes raw 32-bit Luau instruction words and reports container metadata and printable strings. It intentionally does not invent source code when a complete serialized Luau container cannot be parsed.

Use the native backend for exact behavior and complete container decompilation. Use the fallback for diagnostics, portability, tests, and raw instruction analysis.

## Distribution guidance

If native artifacts are distributed in releases:

- Build them in CI from reviewed source where possible.
- Publish a SHA-256 checksum manifest.
- Sign the manifest or release provenance.
- Keep platform and Python ABI tags in filenames.
- Never replace an existing release asset in place.
- Document the exact source commit and toolchain.

LunaUX Next does not install dependencies, download executables, or modify itself at runtime.
