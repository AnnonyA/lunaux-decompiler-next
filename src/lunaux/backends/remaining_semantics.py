from __future__ import annotations

from typing import cast

import lunaux.backends.quality_lifter as quality
from lunaux.backends import lifter as legacy
from lunaux.backends.ast import Expr, FieldExpr, IndexExpr, LiteralExpr, NameExpr
from lunaux.backends.compat_quality_safe import _SafeCompatibilityQualityFunctionLifter
from lunaux.backends.full_corpus_semantics import _debug_value_names
from lunaux.backends.ssa import SSAValue
from lunaux.backends.table_recovery import PendingTableLiteral

_INSTALLED = False
_ACCESS_OPS = frozenset({"GETTABLE", "GETTABLEKS", "GETUDATAKS", "GETTABLEN"})
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


def _materialized_value_names(
    lifter: _SafeCompatibilityQualityFunctionLifter,
) -> dict[SSAValue, str]:
    """Return source names that were actually emitted for exact SSA values.

    ``register_names`` is deliberately mutable and follows the current physical register
    lifetime.  It therefore cannot be consulted later to render an older SSA value: the
    same register may already hold ``print`` (or any unrelated temporary).  Keep a
    value-keyed ledger at the moment a definition is materialized instead.
    """

    cached = getattr(lifter, "_remaining_materialized_value_names", None)
    if cached is None:
        cached = {}
        setattr(lifter, "_remaining_materialized_value_names", cached)  # noqa: B010
    return cast(dict[SSAValue, str], cached)


def _remember_materialized_value(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue,
    register: int,
) -> None:
    name = lifter.register_names.get(register)
    if name is None or name not in lifter.declared:
        return
    _materialized_value_names(lifter)[value] = name


def _parameter_expression(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue,
) -> Expr | None:
    if value.kind != "entry" or value.register >= lifter.proto.num_params:
        return None
    register = value.register
    local_name = legacy._local_name(lifter.proto, register, 0)
    contextual_name = lifter.parameter_name_overrides.get(register)
    recovered_name = (
        lifter.symbols.entry_names.get(register)
        if lifter.options.smart_variable_names and lifter.symbols is not None
        else None
    )
    name = legacy._sanitize_identifier(
        local_name or contextual_name or recovered_name,
        f"arg{register + 1}",
    )
    return NameExpr(name)


def _access_value_can_reconstruct(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue,
    consumer_pc: int,
) -> bool:
    """Prove that an *elided* table read can be replayed at one later use.

    Only actual GETTABLE* reads qualify.  MOVE is intentionally excluded: treating every
    copied value as a replay candidate caused ordinary multiple assignment and arithmetic
    values to be rebuilt from whatever happened to occupy the physical register later.

    Re-evaluation is additionally limited to one basic block with no call or write in
    between, so a mutable table path cannot silently observe a newer value.
    """

    if value.kind != "instruction" or value.origin_pc is None:
        return False
    if value.origin_pc >= consumer_pc:
        return False
    definition = lifter.instruction_by_pc.get(value.origin_pc)
    if definition is None or definition.name not in _ACCESS_OPS:
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


def _stable_value_expression(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue,
    consumer_pc: int,
    seen: frozenset[SSAValue],
) -> Expr | None:
    """Render one SSA value without consulting mutable physical-register name state."""

    if value in seen:
        return None

    direct = lifter.inline_expressions.get(value)
    if direct is not None:
        return direct

    materialized = _materialized_value_names(lifter).get(value)
    if materialized is not None:
        return NameExpr(materialized)

    parameter = _parameter_expression(lifter, value)
    if parameter is not None:
        return parameter

    forced = lifter._forced_value_names().get(value)
    if forced is not None and forced in lifter.declared:
        return NameExpr(forced)

    debug_name = _debug_value_names(lifter).get(value)
    if debug_name is not None and debug_name in lifter.declared:
        return NameExpr(debug_name)

    if value.kind == "phi":
        phi_name = lifter._all_phi_names().get(value)
        if phi_name is not None and phi_name in lifter.declared:
            return NameExpr(phi_name)
        return None

    if value.kind != "instruction" or value.origin_pc is None:
        return None
    instruction = lifter.instruction_by_pc.get(value.origin_pc)
    if instruction is None:
        return None

    next_seen = seen | frozenset({value})
    if instruction.name == "MOVE":
        source = lifter.ssa.value_at_use(instruction.pc, instruction.b)
        if source is None:
            return None
        return _stable_value_expression(
            lifter,
            source,
            instruction.pc,
            next_seen,
        )

    if instruction.name in _ACCESS_OPS and _access_value_can_reconstruct(
        lifter,
        value,
        consumer_pc,
    ):
        return _access_expression_for_value(
            lifter,
            value,
            next_seen,
        )
    return None


def _operand_expression(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    register: int,
    pc: int,
    seen: frozenset[SSAValue],
) -> Expr | None:
    value = lifter.ssa.value_at_use(pc, register)
    if value is None:
        return None
    return _stable_value_expression(lifter, value, pc, seen)


def _access_expression_for_value(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue,
    seen: frozenset[SSAValue] = frozenset(),
) -> Expr | None:
    """Recover a table access from SSA operands, never from a historical register name.

    The key distinction is between *materialized* aliases and *elided* accesses.  A
    materialized alias is kept as its exact emitted source local; only an access that was
    never materialized may be reconstructed.  Every operand is then resolved by SSA
    identity, so later physical-register reuse cannot turn ``data.Stats`` into ``print``
    or ``math.floor`` into a path rooted at a newer register lifetime.
    """

    if value in seen or value.kind != "instruction" or value.origin_pc is None:
        return None
    instruction = lifter.instruction_by_pc.get(value.origin_pc)
    if instruction is None or instruction.name not in _ACCESS_OPS:
        return None
    next_seen = seen | frozenset({value})

    if instruction.name in {"GETTABLEKS", "GETUDATAKS"}:
        base = _operand_expression(
            lifter,
            instruction.b,
            instruction.pc,
            next_seen,
        )
        if base is None:
            return None
        return FieldExpr(base, lifter._table_key(instruction))

    if instruction.name == "GETTABLEN":
        base = _operand_expression(
            lifter,
            instruction.b,
            instruction.pc,
            next_seen,
        )
        if base is None:
            return None
        return IndexExpr(base, LiteralExpr(str(instruction.c + 1)))

    if instruction.name == "GETTABLE":
        base = _operand_expression(
            lifter,
            instruction.b,
            instruction.pc,
            next_seen,
        )
        index = _operand_expression(
            lifter,
            instruction.c,
            instruction.pc,
            next_seen,
        )
        if base is None or index is None:
            return None
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
    original_assign = lifter_type._assign
    original_flush_pending_table = lifter_type._flush_pending_table

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

    def _assign(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        expression: Expr | str,
        pc: int,
    ) -> None:
        value = self.ssa.value_defined_at(pc, register)
        original_assign(self, register, expression, pc)
        # Record only a definition emitted at its real origin. Delayed pending-table
        # emission uses a later PC and is recorded by _flush_pending_table below.
        if (
            value is not None
            and value.origin_pc == pc
            and value not in self.inline_expressions
        ):
            _remember_materialized_value(self, value, register)

    def _flush_pending_table(
        self: _SafeCompatibilityQualityFunctionLifter,
        pending: PendingTableLiteral,
    ) -> None:
        active = self.pending_tables.get(pending.value) is pending
        original_flush_pending_table(self, pending)
        if active and pending.value not in self.inline_expressions:
            _remember_materialized_value(self, pending.value, pending.register)

    def _ref_expr(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> Expr:
        expression = original_ref_expr(self, register, pc)
        if not isinstance(expression, NameExpr):
            return expression
        value = self.ssa.value_at_use(pc, register)
        if value is None:
            return expression

        # An actual emitted local is already the semantics-preserving SSA destruction
        # result. Never replace it by replaying its defining GETTABLE* expression.
        if value in _materialized_value_names(self):
            return expression
        if not _access_value_can_reconstruct(self, value, pc):
            return expression
        reconstructed = _access_expression_for_value(self, value)
        return reconstructed if reconstructed is not None else expression

    setattr(lifter_type, "_friendly_name", _friendly_name)  # noqa: B010
    setattr(lifter_type, "_assign", _assign)  # noqa: B010
    setattr(lifter_type, "_flush_pending_table", _flush_pending_table)  # noqa: B010
    setattr(lifter_type, "_ref_expr", _ref_expr)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_remaining_semantics_fix"]
