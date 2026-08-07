from __future__ import annotations

from lunaux.backends.bytecode import LuauBytecodeModule
from lunaux.backends.compat_quality_lifter import (
    decompile_module as decompile_legacy_module,
)
from lunaux.backends.compat_quality_lifter import disassemble_module
from lunaux.backends.compat_quality_safe import (
    decompile_module as decompile_safe_module,
)


def decompile_module(
    module: LuauBytecodeModule,
    options: dict[str, bool],
    filename: str | None,
) -> str:
    if options.get("Semicolons", False):
        return decompile_legacy_module(module, options, filename)
    return decompile_safe_module(module, options, filename)


__all__ = ["decompile_module", "disassemble_module"]
