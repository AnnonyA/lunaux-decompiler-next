# Optional Unluau engine

Build the reviewed, pinned upstream source into this directory:

```bat
py -3 scripts\install_unluau.py --runtime win-x64
```

Or place an authorized Unluau command-line build here using one of these names:

```text
unluau.exe
unluau
Unluau.CLI.exe
Unluau.CLI
Unluau.CLI.dll
```

LunaUX discovers these files automatically in `auto` mode. Generated binaries, licenses, and manifests in this directory are intentionally ignored by Git; this README remains committed.

See [`../../docs/UNLUAU.md`](../../docs/UNLUAU.md).
