# Unluau integration

LunaUX Next can use [`atrexus/unluau`](https://github.com/atrexus/unluau) as an optional external engine. Unluau is Apache-2.0 licensed and remains a separate program.

## Reproducible source installation

The repository includes `scripts/install_unluau.py`. It pins the reviewed upstream revision:

```text
f89e03a560f535eb19f11e89a6aadec636d2a8f5
```

The command is explicit; LunaUX never downloads or updates an external engine during API startup or decompilation.

Windows x64 build:

```bat
py -3 scripts\install_unluau.py --runtime win-x64
```

Fetch the source without building:

```bat
py -3 scripts\install_unluau.py --source-only
```

Refresh the pinned checkout and rebuild:

```bat
py -3 scripts\install_unluau.py --refresh --runtime win-x64
```

Requirements for a source build:

- Git;
- .NET SDK;
- a compatible runtime identifier such as `win-x64`.

Generated locations:

```text
third_party/unluau/   pinned source checkout
tools/unluau/         published CLI, license, and build manifest
```

These generated files are ignored by Git. The committed installer, pin, documentation, adapter, tests, and notices make the integration reproducible without silently redistributing an opaque binary.

## Existing binary

You can instead place or select an authorized upstream build named:

```text
unluau.exe
unluau
Unluau.CLI.exe
Unluau.CLI
Unluau.CLI.dll
```

Automatic search includes `tools/unluau`, `unluau`, PATH, and the path configured by `LUNAUX_UNLUAU_PATH`.

For a framework-dependent DLL, `dotnet` must be in PATH. A self-contained executable does not require a separately installed runtime.

## Engine policy

Recommended mode:

```text
native LunaUX -> Unluau -> Python reconstruction
```

Fallback happens for every request. An Unluau timeout, process failure, missing output, or unsupported script does not prevent the Python engine from attempting recovery in `auto` mode.

## Isolation

For each operation the adapter:

1. creates a private temporary directory;
2. writes the submitted bytecode there;
3. invokes Unluau with an argument list and no shell;
4. directs generated source and logs to separate files;
5. captures stdout/stderr;
6. enforces `LUNAUX_EXTERNAL_TIMEOUT_SECONDS`;
7. removes the temporary directory.

LunaUX requests Unluau's table inlining, variable-name guessing, and upvalue renaming options for readable output.

## Limitations

Unluau is alpha software and its upstream history documents incomplete coverage on complex or newer bytecode. It is therefore one engine in a fallback chain, not a promise of exact original-source recovery.
