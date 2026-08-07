from __future__ import annotations

from typing import cast

from lunaux.backends.ast import CallExpr, Expr, MethodCallExpr
from lunaux.backends.multret_lifter import _MultiRetFunctionLifter
from lunaux.backends.opcodes import DecodedInstruction


_INSTALLED = False


def _open_argument_expr(
    lifter: _MultiRetFunctionLifter,
    register: int,
    pc: int,
) -> Expr:
    """Recover a fixed argument hidden from SSA by CALL B=0.

    Luau models B=0 calls as consuming arguments through the dynamic stack top, so
    the ordinary register-use analysis cannot enumerate fixed prefix registers.
    The MULTRET plan *can* enumerate that prefix because it knows where the open
    tuple begins. If SSA has no use edge for one of those registers, recover the
    most recent same-block definition and reuse an already materialized/inlined
    expression. This preserves evaluation order and avoids emitting an undefined
    generated name such as ``select(value3, ...)`` when ``value3`` was the
    optimized literal ``\"#\"``.
    """

    if lifter.ssa.value_at_use(pc, register) is not None:
        return lifter._ref_expr(register, pc)

    block = next(
        (
            candidate
            for candidate in lifter.analysis.blocks
            if any(instruction.pc == pc for instruction in candidate.instructions)
        ),
        None,
    )
    if block is None:
        return lifter._ref_expr(register, pc)

    for previous in reversed(block.instructions):
        if previous.pc >= pc:
            continue
        if register not in lifter.analysis.register_accesses[previous.pc].definitions:
            continue
        value = lifter.ssa.value_defined_at(previous.pc, register)
        if value is not None:
            callback = lifter.callback_expressions.get(value)
            if callback is not None:
                return callback
            inline = lifter.inline_expressions.get(value)
            if inline is not None:
                return inline
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

    _MultiRetFunctionLifter._call_expression = cast(
        object,
        _call_expression,
    )  # type: ignore[method-assign]
    _INSTALLED = True


__all__ = ["install_open_argument_fix"]
