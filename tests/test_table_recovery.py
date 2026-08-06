from __future__ import annotations

from lunaux.backends.ast import LiteralExpr, NameExpr, render_expression
from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.ssa import SSAValue
from lunaux.backends.table_recovery import (
    PendingTableLiteral,
    should_flush_tables_before,
)


def _instruction(
    pc: int,
    name: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
) -> DecodedInstruction:
    opcode = opcode_names().index(name)
    return DecodedInstruction(
        pc=pc,
        word=opcode,
        opcode=opcode,
        name=name,
        a=a,
        b=b,
        c=c,
        d=0,
        e=0,
        aux=None,
    )


def test_builds_named_and_array_table_fields() -> None:
    value = SSAValue(register=0, version=1, origin_pc=0, kind="instruction")
    pending = PendingTableLiteral(value=value, register=0, definition_pc=0)

    assert pending.add_named("Name", LiteralExpr('"Sword"'))
    assert pending.add_named("Damage", LiteralExpr("25"))
    assert pending.add_index(1, LiteralExpr('"Fire"'))
    assert pending.add_index(2, LiteralExpr('"Ice"'))
    assert pending.add_named("Name", NameExpr("other"))

    assert render_expression(pending.expression()) == ('{Name = other, Damage = 25, "Fire", "Ice"}')


def test_flushes_before_calls_and_table_escapes() -> None:
    pending = frozenset({0})

    assert not should_flush_tables_before(
        _instruction(1, "LOADN", a=1),
        pending,
    )
    assert not should_flush_tables_before(
        _instruction(2, "SETTABLEN", a=1, b=0, c=0),
        pending,
    )
    assert should_flush_tables_before(
        _instruction(3, "CALL", a=2, b=1, c=1),
        pending,
    )
    assert should_flush_tables_before(
        _instruction(4, "MOVE", a=2, b=0),
        pending,
    )
