from __future__ import annotations

import re

import lunaux.backends.quality_lifter as quality
from lunaux.backends.ast import Expr, NameExpr, ensure_expr
from lunaux.backends.compat_quality_safe import _SafeCompatibilityQualityFunctionLifter
from lunaux.backends.remaining_semantics import (
    _ACCESS_OPS,
    _access_expression_for_value,
    _access_value_can_reconstruct,
    _stable_value_expression,
)
from lunaux.backends.ssa import SSAValue

_INSTALLED = False
_SCALAR_LITERAL = re.compile(
    r"(?:nil|true|false|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*')"
)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _normalize_operand(expression: str) -> str:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    return expression


def _replace_identifier(expression: str, name: str, replacement: str) -> str:
    """Replace a standalone identifier in a generated pure expression."""

    return re.sub(rf"(?<![A-Za-z0-9_.:]){re.escape(name)}(?![A-Za-z0-9_])", replacement, expression)


def _access_provenance_expression(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    value: SSAValue,
    consumer_pc: int,
    seen: frozenset[SSAValue] = frozenset(),
) -> Expr | None:
    """Recover the exact table-access provenance behind a MOVE chain.

    Materialized names normally outrank replay because they are the lexical identity that
    was actually emitted. A MOVE can however be assigned that *same* name, producing a
    self alias such as ``local Stats = Stats``. In that one shape the lexical name hides
    the value's real provenance rather than preserving it.

    Follow only exact SSA MOVE edges until an actual GETTABLE* producer is reached, then
    reconstruct that access only when the existing same-block/no-hazard proof says replay
    at the MOVE is safe. This preserves the safety boundary that removed the broad MOVE
    replay regressions while still recovering the table path that the self alias erased.
    """

    if value in seen or value.kind != "instruction" or value.origin_pc is None:
        return None
    instruction = lifter.instruction_by_pc.get(value.origin_pc)
    if instruction is None:
        return None

    if instruction.name == "MOVE":
        source = lifter.ssa.value_at_use(instruction.pc, instruction.b)
        if source is None:
            return None
        return _access_provenance_expression(
            lifter,
            source,
            consumer_pc,
            seen | frozenset({value}),
        )

    if instruction.name not in _ACCESS_OPS:
        return None
    if not _access_value_can_reconstruct(lifter, value, consumer_pc):
        return None
    return _access_expression_for_value(lifter, value, seen)


def _repair_move_source_expression(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    register: int,
    expression: Expr | str,
    pc: int,
) -> Expr:
    """Recover a MOVE source from its exact SSA value before emitting the assignment.

    A copied table-access value can lose its source identity when friendly/debug naming
    gives the MOVE destination the same identifier that the source reference resolves to.
    The normal emitter then produces a self alias such as ``local field = field``; alias
    cleanup removes that declaration and later field uses become undefined.

    Repair only MOVE assignments whose current RHS collapsed to a bare name. Resolve the
    source SSA value at the MOVE itself, where using the original value is semantically
    faithful, rather than replaying a historical GETTABLE* at a later consumer. The
    stable resolver never consults mutable physical-register naming state and therefore
    cannot reproduce the broad MOVE replay regressions that affected ordinary arithmetic
    and multiple assignment values.
    """

    rendered = ensure_expr(expression)
    instruction = lifter.instruction_by_pc.get(pc)
    if (
        instruction is None
        or instruction.name != "MOVE"
        or instruction.a != register
        or not isinstance(rendered, NameExpr)
    ):
        return rendered

    source = lifter.ssa.value_at_use(pc, instruction.b)
    if source is None:
        return rendered
    stable = _stable_value_expression(lifter, source, pc, frozenset())
    if stable is not None and stable != rendered:
        return stable

    # A materialized source can legitimately resolve to the same identifier as the MOVE
    # destination. If that source is really a GETTABLE* (possibly behind more MOVEs), the
    # resulting self alias will be deleted by cleanup and leave later uses undefined.
    # Bypass the materialized name only for this exact proven access provenance.
    provenance = _access_provenance_expression(lifter, source, pc)
    if provenance is not None and provenance != rendered:
        return provenance
    return rendered


def _rewrite_extended_boolean_ladders(text: str) -> str:
    """Recover short-circuit ladders whose final predicate uses scalar temporaries.

    Legacy Luau can materialize a comparison constant in a temporary inside the final
    guarded edge. The simpler ladder recovery intentionally rejects that extra line.
    Accept only straight-line scalar-literal temporaries followed by the result write,
    inline those temporaries into the final predicate, and collapse the same complete
    short-circuit CFG shape. Calls, table reads, writes, and nested control flow remain
    untouched.
    """

    lines = text.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        outer = re.fullmatch(r"(?P<indent>\s*)if\s+(.+)\s+then", lines[index])
        if outer is None or index + 9 >= len(lines):
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
        if lines[index + 2] != f"{child}if not {name} then" or lines[index + 3] != f"{child}end":
            result.append(lines[index])
            index += 1
            continue

        second = re.fullmatch(
            rf"{re.escape(child)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 4],
        )
        if second is None or lines[index + 5] != f"{child}if {name} then":
            result.append(lines[index])
            index += 1
            continue

        inner_end = index + 6
        while inner_end < len(lines) and lines[inner_end] != f"{child}end":
            inner_end += 1
        if inner_end >= len(lines) or inner_end + 1 >= len(lines):
            result.append(lines[index])
            index += 1
            continue
        if lines[inner_end + 1] != f"{indent}end":
            result.append(lines[index])
            index += 1
            continue

        body = lines[index + 6 : inner_end]
        if len(body) < 2:
            result.append(lines[index])
            index += 1
            continue
        final = re.fullmatch(
            rf"{re.escape(grandchild)}{re.escape(name)}\s*=\s*(.+)",
            body[-1],
        )
        if final is None:
            result.append(lines[index])
            index += 1
            continue

        replacements: list[tuple[str, str]] = []
        valid = True
        for line in body[:-1]:
            temporary = re.fullmatch(
                rf"{re.escape(grandchild)}(?:local\s+)?"
                r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+)",
                line,
            )
            if temporary is None:
                valid = False
                break
            temporary_name = temporary.group("name")
            temporary_value = temporary.group("value").strip()
            if temporary_name == name or _SCALAR_LITERAL.fullmatch(temporary_value) is None:
                valid = False
                break
            if any(previous_name == temporary_name for previous_name, _ in replacements):
                valid = False
                break
            replacements.append((temporary_name, temporary_value))
        if not valid:
            result.append(lines[index])
            index += 1
            continue

        negated_operand = _normalize_operand(first.group(2))
        second_operand = _normalize_operand(second.group(1))
        if negated_operand != second_operand:
            result.append(lines[index])
            index += 1
            continue

        tail = final.group(1).strip()
        for temporary_name, temporary_value in replacements:
            if _IDENTIFIER.search(tail) is None:
                valid = False
                break
            tail = _replace_identifier(tail, temporary_name, f"({temporary_value})")
        if not valid:
            result.append(lines[index])
            index += 1
            continue

        declared = any(
            re.search(rf"\blocal\b[^\n]*\b{re.escape(name)}\b", previous)
            for previous in lines[:index]
        )
        prefix = "" if declared else "local "
        condition = outer.group(2).strip()
        result.append(
            f"{indent}{prefix}{name} = "
            f"({condition} and not ({second_operand})) or "
            f"({second_operand} and ({tail}))"
        )
        index = inner_end + 2

    return "\n".join(result).rstrip() + "\n"


def install_final_semantics_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    lifter_type = _SafeCompatibilityQualityFunctionLifter
    original_assign = lifter_type._assign
    original_clean_output = quality._clean_output

    def _assign(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        expression: Expr | str,
        pc: int,
    ) -> None:
        original_assign(
            self,
            register,
            _repair_move_source_expression(self, register, expression, pc),
            pc,
        )

    def _clean_output(text: str) -> str:
        return _rewrite_extended_boolean_ladders(original_clean_output(text))

    setattr(lifter_type, "_assign", _assign)  # noqa: B010
    setattr(quality, "_clean_output", _clean_output)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_final_semantics_fix"]
