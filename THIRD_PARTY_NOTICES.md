# Third-party notices

## Luau

LunaUX Next's bytecode metadata and parser behavior are implemented from the public Luau bytecode specification and serializer/runtime sources.

- Project: `luau-lang/luau`
- License: MIT
- Referenced files include `Common/include/Luau/Bytecode.h`, `Common/include/Luau/BytecodeUtils.h`, `Bytecode/src/BytecodeBuilder.cpp`, and `VM/src/lvmload.cpp`.

No Luau virtual machine is embedded or used to execute submitted bytecode.

## Unluau

- Project: `atrexus/unluau`
- License: Apache License 2.0
- Source installer pin: `f89e03a560f535eb19f11e89a6aadec636d2a8f5`

Unluau remains a separate command-line program. `scripts/install_unluau.py` can explicitly fetch and build the pinned source. When built, the installer copies the upstream license into the generated output directory and records the source commit in `unluau-build.json`.

Generated third-party source and binaries are excluded from the LunaUX repository by `.gitignore`.
