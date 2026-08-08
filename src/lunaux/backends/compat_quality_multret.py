from __future__ import annotations

import lunaux.backends.lifter as legacy
import lunaux.backends.quality_lifter as quality
from lunaux.backends.ast import Expr
from lunaux.backends.bytecode import LuauBytecodeModule
from lunaux.backends.compat_quality_lifter import _rewrite_legacy_short_circuit_booleans
from lunaux.backends.compat_quality_safe import (
    _SafeCompatibilityQualityFunctionLifter,
    _rewrite_legacy_boolean_ladders,
)


class _MedalCompatibleMultiRetFunctionLifter(_SafeCompatibilityQualityFunctionLifter):
    """Preserve fixed arguments that precede an open Luau tuple.

    Legacy v3-v6 CALL B=0 uses the current stack top.  The SSA use list intentionally
    cannot enumerate that dynamic tail, which means a fixed argument immediately
    before GETVARARGS/CALL can look dead even though it is part of the call.  Medal
    keeps those physical prefix slots during SSA destruction.  Recover the same value
    from the latest definition in the consumer's basic block, without widening legacy
    SSA coalescing to unrelated register lifetimes.
    """

    def _open_tuple_prefix_expression(self, register: int, pc: int) -> Expr | None:
        if not self._legacy_stripped():
            return None
        use = self._persistent_multret_plan()[1].get(pc)
        if (
            use is None
            or use.kind != "arguments"
            or register not in use.prefix_registers
        ):
            return None

        block_start = self.analysis.block_for_pc.get(pc)
        instruction_index = self.instruction_index_by_pc.get(pc)
        if block_start is None or instruction_index is None:
            return None

        for candidate in reversed(self.instructions[:instruction_index]):
            if candidate.pc < block_start:
                break
            access = self.analysis.register_accesses[candidate.pc]
            if register not in access.definitions:
                continue

            value = self.ssa.value_defined_at(candidate.pc, register)
            if value is not None:
                expression = self._legacy_value_expression(value)
                if expression is not None:
                    return expression

            # Scalar LOADK/LOADN/LOADB values are especially important here: in
            # `select("#", ...)` the `"#"` slot may have no explicit SSA use because
            # CALL B=0 consumes it through the open stack-top convention.
            expression = self._legacy_constant_expression(candidate)
            if expression is not None:
                return expression
            return None
        return None

    def _ref_expr(self, register: int, pc: int) -> Expr:
        prefix = self._open_tuple_prefix_expression(register, pc)
        if prefix is not None:
            return prefix
        return super()._ref_expr(register, pc)


def decompile_module(
    module: LuauBytecodeModule,
    options: dict[str, bool],
    filename: str | None,
) -> str:
    previous_lifter = legacy._FunctionLifter
    legacy._FunctionLifter = _MedalCompatibleMultiRetFunctionLifter  # type: ignore[misc]
    try:
        cleaned = quality._clean_output(legacy.decompile_module(module, options, filename))
        if module.version <= 6:
            cleaned = _rewrite_legacy_short_circuit_booleans(cleaned)
            cleaned = _rewrite_legacy_boolean_ladders(cleaned)
        return cleaned
    finally:
        legacy._FunctionLifter = previous_lifter  # type: ignore[misc]


disassemble_module = legacy.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
