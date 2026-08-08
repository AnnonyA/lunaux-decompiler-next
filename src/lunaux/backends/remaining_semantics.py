from __future__ import annotations

from collections.abc import Callable
from typing import cast

import lunaux.backends.quality_lifter as quality
from lunaux.backends import lifter as legacy
from lunaux.backends.ast import Expr, FieldExpr, IndexExpr, LiteralExpr, NameExpr
from lunaux.backends.compat_quality_safe import _SafeCompatibilityQualityFunctionLifter
from lunaux.backends.ssa import SSAValue

_INSTALLED = False
_ACCESS_OR_MOVE = frozenset({"MOVE", "GETTABLE", "GETTABLEKS", "GETUDATAKS", "GETTABLEN"})
_ACCESS_RECONSTRUCTION_HAZARDS = frozenset(
    {
        "CALL",
        "CALLFB",
        "SETGLOBAL",
        "SETUPVAL",
        "SETTABLE",
        "SETTABLEKS",
        "SETUDATAKS",
        "SETTABLEN",
        "SETLIST",
        "NEWCLASSMEMBER",
    }
)


def _reserved_debug_names(
    lifter: _SafeCompatibilityQualityFunctionLifter,
) -> frozenset[str]:
    cached = getattr(lifter, "_remaining_reserved_debug_names", None)
    if cached is not None:
        return cast(frozenset[str], cached)
    names = frozenset(
        legacy._sanitize_identifier(local.name, f"v{local.register}")
        for local in lifter.proto.locals
        if local.name is not None
    )
    setattr(lifter, "_remaining_reserved_debug_names", names)  # noqa: B010
    return names


def _nonconflicting_generated_name(
    candidate: str,
    reserved: frozenset[str],
    occupied: set[str],
) -> str:
    """Keep generated temporaries away from source-local names reserved for later use."""

    if candidate not in reserved:
        return candidate
    suffix = 2
    replacement = f"{candidate}{suffix}"
    unavailable = occupied | set(reserved)
    while replacement in unavailable:
        suffix += 1
        replacement = f"{candidate}{suffix}"
    return replacement


def _access_value_can_reconstruct(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue,
    consumer_pc: int,
) -> bool:
    """Prove that a table-access SSA value can be re-evaluated at one later use.

    A GETTABLE* result can be materialized under a temporary source name even though
    the table path itself is still the more faithful expression. Re-evaluating an
    access is only safe while the definition and consumer remain in one basic block and
    no call or write that could replace/mutate the observed path occurs in between.
    This keeps the recovery structural instead of globally inlining mutable table reads.
    """

    if value.kind != "instruction" or value.origin_pc is None:
        return False
    if value.origin_pc >= consumer_pc:
        return False
    definition = lifter.instruction_by_pc.get(value.origin_pc)
    if definition is None or definition.name not in _ACCESS_OR_MOVE:
        return False

    origin_block = lifter.analysis.block_for_pc.get(value.origin_pc)
    consumer_block = lifter.analysis.block_for_pc.get(consumer_pc)
    if origin_block is None or origin_block != consumer_block:
        return False

    return not any(
        value.origin_pc < instruction.pc < consumer_pc
        and instruction.name in _ACCESS_RECONSTRUCTION_HAZARDS
        for instruction in lifter.instructions
    )


def _operand_expression(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    register: int,
    pc: int,
    original_ref_expr: Callable[[_SafeCompatibilityQualityFunctionLifter, int, int], Expr],
    seen: frozenset[SSAValue],
) -> Expr:
    value = lifter.ssa.value_at_use(pc, register)
    direct = lifter.inline_expressions.get(value) if value is not None else None
    if direct is not None:
        return direct
    fallback = original_ref_expr(lifter, register, pc)
    if (
        isinstance(fallback, NameExpr)
        and value is not None
        and _access_value_can_reconstruct(lifter, value, pc)
    ):
        reconstructed = _access_expression_for_value(
            lifter,
            value,
            original_ref_expr,
            seen,
        )
        if reconstructed is not None:
            return reconstructed
    return fallback


def _access_expression_for_value(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue,
    original_ref_expr: Callable[[_SafeCompatibilityQualityFunctionLifter, int, int], Expr],
    seen: frozenset[SSAValue] = frozenset(),
) -> Expr | None:
    """Recover table-access values from their side-effect-free SSA origins.

    Pending table-literal reconstruction can absorb the table that originally produced
    a GETTABLE* base while a later use still refers to that SSA value. Reconstruct the
    access from its defining instruction instead of trusting a physical-register name.
    Only MOVE/GETTABLE* chains are followed; callers additionally prove that replaying
    the access at the consumer crosses no mutating instruction.
    """

    if value in seen or value.kind != "instruction" or value.origin_pc is None:
        return None
    instruction = lifter.instruction_by_pc.get(value.origin_pc)
    if instruction is None:
        return None
    next_seen = seen | frozenset({value})

    if instruction.name == "MOVE":
        source = lifter.ssa.value_at_use(instruction.pc, instruction.b)
        if source is not None:
            reconstructed = _access_expression_for_value(
                lifter,
                source,
                original_ref_expr,
                next_seen,
            )
            if reconstructed is not None:
                return reconstructed
        return _operand_expression(
            lifter,
            instruction.b,
            instruction.pc,
            original_ref_expr,
            next_seen,
        )

    if instruction.name in {"GETTABLEKS", "GETUDATAKS"}:
        base = _operand_expression(
            lifter,
            instruction.b,
            instruction.pc,
            original_ref_expr,
            next_seen,
        )
        return FieldExpr(base, lifter._table_key(instruction))

    if instruction.name == "GETTABLEN":
        base = _operand_expression(
            lifter,
            instruction.b,
            instruction.pc,
            original_ref_expr,
            next_seen,
        )
        return IndexExpr(base, LiteralExpr(str(instruction.c + 1)))

    if instruction.name == "GETTABLE":
        base = _operand_expression(
            lifter,
            instruction.b,
            instruction.pc,
            original_ref_expr,
            next_seen,
        )
        index = _operand_expression(
            lifter,
            instruction.c,
            instruction.pc,
            original_ref_expr,
            next_seen,
        )
        return IndexExpr(base, index)

    return None


def install_remaining_semantics_fix() -> None:
    """Install generic recovery for the remaining table and debug-name lifetime gaps."""

    global _INSTALLED
    if _INSTALLED:
        return

    lifter_type = _SafeCompatibilityQualityFunctionLifter
    original_friendly_name = lifter_type._friendly_name
    original_ref_expr = lifter_type._ref_expr

    def _friendly_name(
        self: _SafeCompatibilityQualityFunctionLifter,
        name: str,
    ) -> str:
        friendly = original_friendly_name(self, name)
        if quality._GENERATED_NAME.fullmatch(name) is None:
            return friendly
        reserved = _reserved_debug_names(self)
        replacement = _nonconflicting_generated_name(
            friendly,
            reserved,
            set(self._friendly_name_cache().values()) | set(self.declared),
        )
        if replacement != friendly:
            self._friendly_name_cache()[name] = replacement
        return replacement

    def _ref_expr(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> Expr:
        expression = original_ref_expr(self, register, pc)
        if not isinstance(expression, NameExpr):
            return expression
        value = self.ssa.value_at_use(pc, register)
        if value is None or not _access_value_can_reconstruct(self, value, pc):
            return expression
        reconstructed = _access_expression_for_value(
            self,
            value,
            original_ref_expr,
        )
        return reconstructed if reconstructed is not None else expression

    setattr(lifter_type, "_friendly_name", _friendly_name)  # noqa: B010
    setattr(lifter_type, "_ref_expr", _ref_expr)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_remaining_semantics_fix"]
