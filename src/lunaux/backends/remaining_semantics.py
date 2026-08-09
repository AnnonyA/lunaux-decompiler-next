from __future__ import annotations

import re
from typing import cast

import lunaux.backends.quality_lifter as quality
from lunaux.backends import lifter as legacy
from lunaux.backends.ast import (
    Expr,
    FieldExpr,
    IndexExpr,
    LiteralExpr,
    NameExpr,
    ensure_expr,
    render_expression,
)
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
    lifetime. It therefore cannot be consulted later to render an older SSA value: the
    same register may already hold ``print`` (or any unrelated temporary). Keep a
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

    Only actual GETTABLE* reads qualify. MOVE is intentionally excluded: treating every
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

    The key distinction is between *materialized* aliases and *elided* accesses. A
    materialized alias is kept as its exact emitted source local; only an access that was
    never materialized may be reconstructed. Every operand is then resolved by SSA
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


def _repair_access_definition_expression(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue | None,
    expression: Expr | str,
) -> Expr:
    """Restore a GETTABLE* operation that naming accidentally collapsed to a bare name.

    At the definition PC this is not speculative replay: it is the table read encoded by
    the bytecode itself. Reconstructing it from SSA operands is therefore safe even for
    mutable tables and avoids emitting self aliases such as ``local Stats = Stats``.
    """

    rendered = ensure_expr(expression)
    if value is None or value.kind != "instruction" or value.origin_pc is None:
        return rendered
    instruction = lifter.instruction_by_pc.get(value.origin_pc)
    if instruction is None or instruction.name not in _ACCESS_OPS:
        return rendered
    if not isinstance(rendered, NameExpr):
        return rendered
    reconstructed = _access_expression_for_value(lifter, value)
    return reconstructed if reconstructed is not None else rendered


def _normalize_boolean_operand(expression: str) -> str:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    return expression


def _rewrite_short_circuit_boolean_ladders(text: str) -> str:
    """Collapse the exact malformed CFG ladder for a short-circuit boolean value.

    Luau's boolean lowering can feed one result through several conditional assignments.
    If the structured emitter loses the edge predicate it produces an empty guard and an
    unconditional overwrite. Recognize only that complete nine-line shape and restore
    the equivalent ``(a and not b) or (b and c)`` selection. The rule is independent of
    bytecode version, local names, constants, and benchmark cases.
    """

    lines = text.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        outer = re.fullmatch(r"(?P<indent>\s*)if\s+(.+)\s+then", lines[index])
        if outer is None or index + 8 >= len(lines):
            result.append(lines[index])
            index += 1
            continue

        indent = outer.group("indent")
        child = indent + "    "
        grandchild = child + "    "
        first = re.fullmatch(
            rf"{re.escape(child)}(?:local\s+)?"
            r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*not\s+(.+)",
            lines[index + 1],
        )
        if first is None:
            result.append(lines[index])
            index += 1
            continue

        name = first.group("name")
        empty_guard = lines[index + 2] == f"{child}if not {name} then"
        empty_end = lines[index + 3] == f"{child}end"
        second = re.fullmatch(
            rf"{re.escape(child)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 4],
        )
        positive_guard = lines[index + 5] == f"{child}if {name} then"
        third = re.fullmatch(
            rf"{re.escape(grandchild)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 6],
        )
        inner_end = lines[index + 7] == f"{child}end"
        outer_end = lines[index + 8] == f"{indent}end"
        if not (
            empty_guard
            and empty_end
            and second is not None
            and positive_guard
            and third is not None
            and inner_end
            and outer_end
        ):
            result.append(lines[index])
            index += 1
            continue

        negated_operand = _normalize_boolean_operand(first.group(2))
        second_operand = _normalize_boolean_operand(second.group(1))
        if negated_operand != second_operand:
            result.append(lines[index])
            index += 1
            continue

        declared = any(
            re.search(rf"\blocal\b[^\n]*\b{re.escape(name)}\b", previous)
            for previous in lines[:index]
        )
        prefix = "" if declared else "local "
        condition = outer.group(2).strip()
        tail = third.group(1).strip()
        result.append(
            f"{indent}{prefix}{name} = "
            f"({condition} and not ({second_operand})) or "
            f"({second_operand} and ({tail}))"
        )
        index += 9

    return "\n".join(result).rstrip() + "\n"


def _fresh_lifetime_name(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    register: int,
    captured_identifiers: frozenset[str],
) -> str:
    """Allocate a new lexical name when a physical register outlives a REF capture."""

    base = f"value{register + 1}"
    occupied = (
        set(lifter.declared)
        | set(lifter.register_names.values())
        | set(lifter._forced_value_names().values())
        | set(_materialized_value_names(lifter).values())
        | set(captured_identifiers)
    )
    candidate = base
    suffix = 2
    while candidate in occupied:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def install_remaining_semantics_fix() -> None:
    """Install generic recovery for remaining SSA, table, boolean, and capture gaps."""

    global _INSTALLED
    if _INSTALLED:
        return

    lifter_type = _SafeCompatibilityQualityFunctionLifter
    original_friendly_name = lifter_type._friendly_name
    original_name = lifter_type._name
    original_definition_name = lifter_type._definition_name
    original_ref_expr = lifter_type._ref_expr
    original_assign = lifter_type._assign
    original_flush_pending_table = lifter_type._flush_pending_table
    original_clean_output = quality._clean_output

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

    def _name(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> str:
        value = self.ssa.value_at_use(pc, register)
        if value is not None:
            captured_names = self._captured_reference_names()
            if value not in captured_names:
                forced = self._forced_value_names().get(value)
                if forced is not None and forced not in captured_names.values():
                    self.register_names[register] = forced
                    return forced
        return original_name(self, register, pc)

    def _definition_name(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> str:
        value = self.ssa.value_defined_at(pc, register)
        captured_names = self._captured_reference_names()
        captured_identifiers = frozenset(captured_names.values())
        if value is not None and value not in captured_names:
            debug_name = _debug_value_names(self).get(value)
            current_name = self.register_names.get(register)
            if debug_name in captured_identifiers or current_name in captured_identifiers:
                self._forced_value_names().pop(value, None)
                self.register_names.pop(register, None)
                name = _fresh_lifetime_name(self, register, captured_identifiers)
                self._forced_value_names()[value] = name
                self.register_names[register] = name
                return name

        name = original_definition_name(self, register, pc)
        if (
            value is not None
            and value not in captured_names
            and name in captured_identifiers
        ):
            self._forced_value_names().pop(value, None)
            self.register_names.pop(register, None)
            name = _fresh_lifetime_name(self, register, captured_identifiers)
            self._forced_value_names()[value] = name
            self.register_names[register] = name
        return name

    def _assign(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        expression: Expr | str,
        pc: int,
    ) -> None:
        value = self.ssa.value_defined_at(pc, register)
        expression = _repair_access_definition_expression(self, value, expression)
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

    def _clean_output(text: str) -> str:
        return _rewrite_short_circuit_boolean_ladders(original_clean_output(text))

    setattr(lifter_type, "_friendly_name", _friendly_name)  # noqa: B010
    setattr(lifter_type, "_name", _name)  # noqa: B010
    setattr(lifter_type, "_definition_name", _definition_name)  # noqa: B010
    setattr(lifter_type, "_assign", _assign)  # noqa: B010
    setattr(lifter_type, "_flush_pending_table", _flush_pending_table)  # noqa: B010
    setattr(lifter_type, "_ref_expr", _ref_expr)  # noqa: B010
    setattr(quality, "_clean_output", _clean_output)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_remaining_semantics_fix"]
