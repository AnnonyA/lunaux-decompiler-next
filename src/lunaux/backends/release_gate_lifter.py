from __future__ import annotations

from typing import cast

import lunaux.backends.compat_quality_lifter as compat
import lunaux.backends.lifter as legacy
from lunaux.backends.bytecode import LuauBytecodeModule
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAValue


class _ReleaseGateFunctionLifter(compat._CompatibilityQualityFunctionLifter):
    """Targeted legacy-v6 correctness fixes discovered by the 0.18 release corpus."""

    def _legacy_component_name(self, value: SSAValue) -> str:
        name = super()._legacy_component_name(value)
        if legacy._IDENTIFIER.fullmatch(name) and name not in legacy._RESERVED:
            return name

        key = self._legacy_group_key(value)
        cached = self._legacy_group_names().get(key)
        if cached is not None and legacy._IDENTIFIER.fullmatch(cached):
            return cached

        replacement = self._legacy_fresh_name(
            self._legacy_instruction_stem(value),
            key,
        )
        self._legacy_group_names()[key] = replacement
        return replacement

    def _handle_loop_prep(self, instruction: DecodedInstruction) -> bool:
        handled = super()._handle_loop_prep(instruction)
        if (
            handled
            and self.module.version <= 6
            and instruction.name == "FORNPREP"
        ):
            target = legacy._jump_target(instruction)
            register = instruction.a + 2
            variable = self.register_names.get(register, "index")
            # Legacy v3-v6 uses A+2 as the visible induction variable throughout
            # the loop body.  Force the structural name over the complete region;
            # SSA versions at FORNPREP/FORNLOOP alone are insufficient when the
            # stripped compiler exposes an entry/phi value at intermediate uses.
            self._force_register_name(register, instruction.pc, target, variable)
        return handled


def decompile_module(
    module: LuauBytecodeModule,
    options: dict[str, bool],
    filename: str | None,
) -> str:
    previous = compat._CompatibilityQualityFunctionLifter
    compat._CompatibilityQualityFunctionLifter = _ReleaseGateFunctionLifter
    try:
        return compat.decompile_module(module, options, filename)
    finally:
        compat._CompatibilityQualityFunctionLifter = cast(
            type[compat._CompatibilityQualityFunctionLifter],
            previous,
        )


disassemble_module = compat.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
