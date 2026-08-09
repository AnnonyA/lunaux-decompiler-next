from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from lunaux.backends.ast import FieldExpr, NameExpr, render_expression
from lunaux.backends.final_semantics import (
    _repair_move_source_expression,
    _rewrite_extended_boolean_ladders,
)
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAValue


def _move(pc: int, target: int, source: int) -> DecodedInstruction:
    return DecodedInstruction(
        pc=pc,
        word=0,
        opcode=0,
        name="MOVE",
        a=target,
        b=source,
        c=0,
        d=0,
        e=0,
        aux=None,
    )


def test_move_repair_recovers_elided_table_access_source() -> None:
    source_value = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    move = _move(2, 2, 1)

    class FakeSSA:
        def value_at_use(self, pc: int, register: int) -> SSAValue | None:
            if pc == 2 and register == 1:
                return source_value
            return None

    lifter = cast(
        Any,
        SimpleNamespace(
            instruction_by_pc={2: move},
            ssa=FakeSSA(),
            inline_expressions={
                source_value: FieldExpr(NameExpr("record"), "Stats"),
            },
        ),
    )

    repaired = _repair_move_source_expression(
        lifter,
        2,
        NameExpr("Stats"),
        2,
    )
    assert render_expression(repaired) == "record.Stats"


def test_move_repair_preserves_already_stable_source_name() -> None:
    source_value = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    move = _move(2, 2, 1)

    class FakeSSA:
        def value_at_use(self, pc: int, register: int) -> SSAValue | None:
            if pc == 2 and register == 1:
                return source_value
            return None

    lifter = cast(
        Any,
        SimpleNamespace(
            instruction_by_pc={2: move},
            ssa=FakeSSA(),
            inline_expressions={source_value: NameExpr("value4")},
        ),
    )

    repaired = _repair_move_source_expression(
        lifter,
        2,
        NameExpr("value4"),
        2,
    )
    assert repaired == NameExpr("value4")


def test_extended_boolean_ladder_inlines_scalar_temporary() -> None:
    source = """if left then
    local selected = not right
    if not selected then
    end
    selected = right
    if selected then
        value4 = 10
        selected = value4 < value
    end
end
print(selected, left, right)
"""
    expected = (
        "local selected = (left and not (right)) or "
        "(right and ((10) < value))\n"
        "print(selected, left, right)\n"
    )

    assert _rewrite_extended_boolean_ladders(source) == expected


def test_extended_boolean_ladder_rejects_effectful_temporary() -> None:
    source = """if left then
    local selected = not right
    if not selected then
    end
    selected = right
    if selected then
        value4 = nextLimit()
        selected = value4 < value
    end
end
"""

    assert _rewrite_extended_boolean_ladders(source) == source
