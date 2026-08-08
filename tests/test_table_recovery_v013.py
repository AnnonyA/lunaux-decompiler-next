from __future__ import annotations

from lunaux.backends.ast import CallExpr, LiteralExpr, NameExpr, render_expression
from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.ssa import SSAValue
from lunaux.backends.table_recovery import PendingTableLiteral, should_flush_tables_before


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


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    opcode = opcode_names().index(name)
    return opcode | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, *, a: int = 0, d: int = 0) -> int:
    opcode = opcode_names().index(name)
    return opcode | (a << 8) | ((d & 0xFFFF) << 16)


def _module(
    code: tuple[int, ...],
    constants: tuple[LuauConstant, ...] = (),
    *,
    stack: int = 8,
    vararg: bool = False,
) -> LuauBytecodeModule:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=stack,
        num_params=0,
        num_upvalues=0,
        is_vararg=vararg,
        flags=0,
        type_info=b"",
        code=code,
        constants=constants,
        child_proto_ids=(),
        line_defined=1,
        debug_name="main",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    return LuauBytecodeModule(
        version=13,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def test_dynamic_keys_overwrite_and_open_tail() -> None:
    value = SSAValue(register=0, version=1, origin_pc=0, kind="instruction")
    pending = PendingTableLiteral(value=value, register=0, definition_pc=0)

    assert pending.add_dynamic(NameExpr("key"), LiteralExpr("1"))
    assert pending.add_dynamic(NameExpr("key"), LiteralExpr("2"))
    assert pending.add_index(1, LiteralExpr('"head"'))
    assert pending.add_open_tail(2, CallExpr(NameExpr("collect"), ()))
    assert not pending.add_named("late", LiteralExpr("3"))

    assert render_expression(pending.expression()) == (
        '{[key] = 2, "head", collect()}'
    )


def test_dependency_redefinition_forces_materialization() -> None:
    pending = frozenset({0})
    dependencies = frozenset({2})

    assert should_flush_tables_before(
        _instruction(1, "LOADN", a=2),
        pending,
        dependencies,
    )
    assert not should_flush_tables_before(
        _instruction(2, "LOADN", a=3),
        pending,
        dependencies,
    )


def test_decompiles_nested_dynamic_and_fixed_list_tables() -> None:
    constants = (
        LuauConstant("string", "Value", 3),
        LuauConstant("string", "Child", 3),
        LuauConstant("string", "dynamic-key", 3),
    )
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("NEWTABLE", a=1),
        0,
        _ad("LOADN", a=2, d=7),
        _abc("SETTABLEKS", a=2, b=1),
        0,
        _abc("SETTABLEKS", a=1, b=0),
        1,
        _ad("LOADK", a=3, d=2),
        _ad("LOADN", a=4, d=9),
        _abc("SETTABLE", a=4, b=0, c=3),
        _abc("NEWTABLE", a=5),
        0,
        _ad("LOADN", a=6, d=11),
        _abc("SETTABLEN", a=6, b=5, c=0),
        _abc("SETLIST", a=0, b=5, c=2),
        1,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "nested.luau")

    assert "Child = {Value = 7}" in output
    assert '["dynamic-key"] = 9' in output
    assert "{11}" in output
    assert ".Child =" not in output


def test_decompiles_duptable_template_and_deterministic_overwrite() -> None:
    constants = (
        LuauConstant("string", "Name", 3),
        LuauConstant("string", "Sword", 3),
        LuauConstant("table_with_constants", ((0, 1),), 8),
        LuauConstant("string", "Axe", 3),
        LuauConstant("string", "Damage", 3),
    )
    code = (
        _ad("DUPTABLE", a=0, d=2),
        _ad("LOADK", a=1, d=3),
        _abc("SETTABLEKS", a=1, b=0),
        0,
        _ad("LOADN", a=2, d=25),
        _abc("SETTABLEKS", a=2, b=0),
        4,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "template.luau")

    assert 'Name = "Axe"' in output
    assert 'Name = "Sword"' not in output
    assert "Damage = 25" in output
    assert ".Name =" not in output


def test_decompiles_open_call_and_vararg_setlist_tails() -> None:
    call_constants = (LuauConstant("string", "collect", 3),)
    call_code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("GETGLOBAL", a=1),
        0,
        _abc("CALL", a=1, b=1, c=0),
        _abc("SETLIST", a=0, b=1, c=0),
        1,
        _abc("RETURN", a=0, b=2),
    )
    call_output = decompile_module(
        _module(call_code, call_constants),
        {},
        "open-call.luau",
    )

    assert "{collect()}" in call_output
    assert "multiple returns" not in call_output
    assert "set all stack values" not in call_output

    vararg_code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("GETVARARGS", a=1, b=0),
        _abc("SETLIST", a=0, b=1, c=0),
        1,
        _abc("RETURN", a=0, b=2),
    )
    vararg_output = decompile_module(
        _module(vararg_code, vararg=True),
        {},
        "open-vararg.luau",
    )

    assert "{...}" in vararg_output
    assert "set all stack values" not in vararg_output


def test_transfers_single_use_table_across_move() -> None:
    constants = (LuauConstant("string", "Value", 3),)
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("MOVE", a=1, b=0),
        _ad("LOADN", a=2, d=5),
        _abc("SETTABLEKS", a=2, b=1),
        0,
        _abc("RETURN", a=1, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "move.luau")

    assert "{Value = 5}" in output
    assert "= v0" not in output
