# Native backend compatibility

The public repository does not bundle or download native decompiler binaries. This avoids self-updating code and makes installation behavior explicit.

By default, LunaUX Next imports `luna`. Change the module name with `LUNAUX_BACKEND_MODULE`.

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

## Distribution guidance

If native artifacts are distributed in releases:

- Build them in CI from reviewed source where possible.
- Publish a SHA-256 checksum manifest.
- Sign the manifest or release provenance.
- Keep platform and Python ABI tags in filenames.
- Never replace an existing release asset in place.
- Document the exact source commit and toolchain.

LunaUX Next intentionally does not install dependencies or native modules at runtime.
