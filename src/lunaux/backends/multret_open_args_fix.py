from __future__ import annotations

import lunaux.backends.lifter as legacy
from lunaux.backends.analysis import BasicBlock
from lunaux.backends.ast import (
    BinaryExpr,
    CallExpr,
    Expr,
    LiteralExpr,
    MethodCallExpr,
    UnaryExpr,
    source_expr,
)
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
) -> BasicBlock | None:
    start = lifter.analysis.block_for_pc.get(pc)
    return lifter.analysis.block_by_start.get(start) if start is not None else None


def _physical_definition_expr(
    lifter: _MultiRetFunctionLifter,
    register: int,
    before_pc: int,
    consumer_block: BasicBlock,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> Expr | None:
    """Resolve the latest dominating definition of a physical open-argument slot.

    CALL B=0 consumes registers through Luau's dynamic stack top. Those fixed prefix
    slots can therefore be absent from ordinary SSA use edges, especially across the
    FASTCALL fallback split used by optimized v6 bytecode. Follow only definitions
    whose blocks dominate the consumer and reconstruct only side-effect-free values.
    """

    for previous in reversed(lifter.instructions):
        if previous.pc >= before_pc:
            continue
        if register not in lifter.analysis.register_accesses[previous.pc].definitions:
            continue

        definition_block = _block_for_pc(lifter, previous.pc)
        if definition_block is None:
            continue
        if not lifter.analysis.dominates(
            definition_block.start_pc,
            consumer_block.start_pc,
        ):
            continue

        marker = (previous.pc, register)
        if marker in seen:
            return None

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

        next_seen = seen | frozenset({marker})
        if previous.name == "MOVE":
            return _physical_definition_expr(
                lifter,
                previous.b,
                previous.pc,
                consumer_block,
                next_seen,
            )

        if previous.name in legacy._BINARY_OPS:
            left = _physical_definition_expr(
                lifter,
                previous.b,
                previous.pc,
                consumer_block,
                next_seen,
            )
            right = _physical_definition_expr(
                lifter,
                previous.c,
                previous.pc,
                consumer_block,
                next_seen,
            )
            if left is not None and right is not None:
                return BinaryExpr(left, legacy._BINARY_OPS[previous.name], right)
            return None

        if previous.name in legacy._BINARY_CONST_OPS:
            left = _physical_definition_expr(
                lifter,
                previous.b,
                previous.pc,
                consumer_block,
                next_seen,
            )
            if left is None or not 0 <= previous.c < len(lifter.proto.constants):
                return None
            return BinaryExpr(
                left,
                legacy._BINARY_CONST_OPS[previous.name],
                source_expr(legacy._constant_expr(lifter.proto, previous.c)),
            )

        if previous.name in {"SUBRK", "DIVRK"}:
            if not 0 <= previous.b < len(lifter.proto.constants):
                return None
            right = _physical_definition_expr(
                lifter,
                previous.c,
                previous.pc,
                consumer_block,
                next_seen,
            )
            if right is None:
                return None
            operator = "-" if previous.name == "SUBRK" else "/"
            return BinaryExpr(
                source_expr(legacy._constant_expr(lifter.proto, previous.b)),
                operator,
                right,
            )

        if previous.name in legacy._UNARY_OPS:
            operand = _physical_definition_expr(
                lifter,
                previous.b,
                previous.pc,
                consumer_block,
                next_seen,
            )
            if operand is not None:
                return UnaryExpr(legacy._UNARY_OPS[previous.name].strip(), operand)
            return None

        # The nearest dominating definition overwrites the slot. Never walk past a
        # side-effectful or otherwise unsupported write and accidentally resurrect an
        # older value from the same physical register.
        return None

    return None


def _open_argument_expr(
    lifter: _MultiRetFunctionLifter,
    register: int,
    pc: int,
) -> Expr:
    """Recover one fixed argument consumed together with an open Luau tuple."""

    consumer_block = _block_for_pc(lifter, pc)
    if consumer_block is not None:
        recovered = _physical_definition_expr(
            lifter,
            register,
            pc,
            consumer_block,
        )
        if recovered is not None:
            return recovered
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
