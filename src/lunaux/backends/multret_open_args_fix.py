from __future__ import annotations

from lunaux.backends.ast import (
    CallExpr,
    Expr,
    LiteralExpr,
    MethodCallExpr,
    source_expr,
)
import lunaux.backends.lifter as legacy
from lunaux.backends.multret_lifter import _MultiRetFunctionLifter
from lunaux.backends.opcodes import DecodedInstruction


_INSTALLED = False


def _scalar_definition_expr(
    lifter: _MultiRetFunctionLifter,
    instruction: DecodedInstruction,
) -> Expr | None:
    """Recover a side-effect-free scalar directly from its defining instruction."""

    if instruction.name == "LOADNIL":
        return LiteralExpr("nil")
    if instruction.name == "LOADB":
        return LiteralExpr("true" if instruction.b else "false")
    if instruction.name == "LOADN":
        return LiteralExpr(str(instruction.d))
    if instruction.name == "LOADK":
        return source_expr(legacy._constant_expr(lifter.proto, instruction.d))
    if instruction.name == "LOADKX":
        index = instruction.aux if instruction.aux is not None else 0
        return source_expr(legacy._constant_expr(lifter.proto, index))
    return None


def _block_for_pc(
    lifter: _MultiRetFunctionLifter,
    pc: int,
):
    return next(
        (
            block
            for block in lifter.analysis.blocks
            if any(instruction.pc == pc for instruction in block.instructions)
        ),
        None,
    )


def _open_argument_expr(
    lifter: _MultiRetFunctionLifter,
    register: int,
    pc: int,
) -> Expr:
    """Recover a fixed argument hidden or misidentified by CALL B=0 SSA uses.

    Luau models B=0 calls as consuming arguments through the dynamic stack top, so
    ordinary SSA use analysis cannot reliably enumerate every fixed prefix register.
    The MULTRET plan does know the prefix range. Optimized legacy bytecode can place a
    FASTCALL boundary between a fixed scalar argument and the fallback CALL, splitting
    them into different basic blocks. Resolve the nearest *dominating* physical
    definition instead of requiring it to live in the consumer block. This preserves
    `select("#", ...)` at O1/O2 without crossing an ambiguous branch definition.
    """

    consumer_block = _block_for_pc(lifter, pc)
    if consumer_block is None:
        return lifter._ref_expr(register, pc)

    for previous in reversed(lifter.instructions):
        if previous.pc >= pc:
            continue
        if register not in lifter.analysis.register_accesses[previous.pc].definitions:
            continue

        definition_block = _block_for_pc(lifter, previous.pc)
        if definition_block is None:
            continue
        if not lifter.analysis.dominates(definition_block.start_pc, consumer_block.start_pc):
            continue

        value = lifter.ssa.value_defined_at(previous.pc, register)
        if value is not None:
            callback = lifter.callback_expressions.get(value)
            if callback is not None:
                return callback
            inline = lifter.inline_expressions.get(value)
            if inline is not None:
                return inline

        scalar = _scalar_definition_expr(lifter, previous)
        if scalar is not None:
            return scalar

        # The nearest dominating physical definition is authoritative for this slot.
        # If it is not safely reconstructible, preserve the ordinary SSA reference.
        break

    return lifter._ref_expr(register, pc)


def install_open_argument_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original = _MultiRetFunctionLifter._call_expression

    def _call_expression(
        self: _MultiRetFunctionLifter,
        instruction: DecodedInstruction,
    ) -> Expr:
        use = self._persistent_multret_use(instruction.pc)
        if use is None or use.kind != "arguments":
            return original(self, instruction)

        tail = self._multret_expressions().get(use.value)
        if tail is None:
            return original(self, instruction)

        self._multret_expressions().pop(use.value, None)
        if instruction.a in self.pending_namecalls:
            base, method = self.pending_namecalls.pop(instruction.a)
            fixed = tuple(
                _open_argument_expr(self, register, instruction.pc)
                for register in use.prefix_registers
                if register >= instruction.a + 2
            )
            return MethodCallExpr(base, method, (*fixed, tail))

        function = self._ref_expr(instruction.a, instruction.pc)
        fixed = tuple(
            _open_argument_expr(self, register, instruction.pc)
            for register in use.prefix_registers
        )
        return CallExpr(function, (*fixed, tail))

    setattr(_MultiRetFunctionLifter, "_call_expression", _call_expression)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_open_argument_fix"]
