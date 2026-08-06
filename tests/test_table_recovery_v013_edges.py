from __future__ import annotations

from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import opcode_names


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
    num_params: int = 0,
) -> LuauBytecodeModule:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=stack,
        num_params=num_params,
        num_upvalues=0,
        is_vararg=False,
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


def test_self_reference_materializes_before_write() -> None:
    constants = (LuauConstant("string", "Self", 3),)
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("SETTABLEKS", a=0, b=0),
        0,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "self-table.luau")

    assert "= {}" in output
    assert ".Self =" in output
    assert "{Self =" not in output


def test_dependency_redefinition_materializes_constructor_first() -> None:
    constants = (LuauConstant("string", "Value", 3),)
    code = (
        _abc("NEWTABLE", a=1),
        0,
        _abc("SETTABLEKS", a=0, b=1),
        0,
        _ad("LOADN", a=0, d=9),
        _abc("RETURN", a=1, b=2),
    )

    output = decompile_module(
        _module(code, constants, stack=3, num_params=1),
        {},
        "dependency.luau",
    )

    constructor = output.index("{Value = arg1}")
    redefinition = output.index("arg1 = 9")
    assert constructor < redefinition


def test_child_with_external_use_is_not_absorbed() -> None:
    constants = (
        LuauConstant("string", "Value", 3),
        LuauConstant("string", "Child", 3),
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
        _abc("RETURN", a=1, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "shared-child.luau")

    assert "{Value = 7}" in output
    assert "{Child = tbl" in output
    assert "Child = {Value = 7}" not in output


def test_interleaved_independent_tables_remain_complete() -> None:
    constants = (
        LuauConstant("string", "A", 3),
        LuauConstant("string", "B", 3),
        LuauConstant("string", "C", 3),
    )
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("NEWTABLE", a=1),
        0,
        _ad("LOADN", a=2, d=1),
        _abc("SETTABLEKS", a=2, b=0),
        0,
        _ad("LOADN", a=2, d=2),
        _abc("SETTABLEKS", a=2, b=1),
        1,
        _ad("LOADN", a=2, d=3),
        _abc("SETTABLEKS", a=2, b=0),
        2,
        _abc("RETURN", a=0, b=3),
    )

    output = decompile_module(_module(code, constants), {}, "interleaved.luau")

    assert "{A = 1, C = 3}" in output
    assert "{B = 2}" in output


def test_duptable_key_template_accepts_runtime_values() -> None:
    constants = (
        LuauConstant("string", "A", 3),
        LuauConstant("string", "B", 3),
        LuauConstant("table", (0, 1), 5),
    )
    code = (
        _ad("DUPTABLE", a=0, d=2),
        _ad("LOADN", a=1, d=10),
        _abc("SETTABLEKS", a=1, b=0),
        0,
        _ad("LOADN", a=1, d=20),
        _abc("SETTABLEKS", a=1, b=0),
        1,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "key-template.luau")

    assert "{A = 10, B = 20}" in output
    assert "A = nil" not in output


def test_dynamic_boolean_key_is_preserved() -> None:
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("LOADB", a=1, b=1),
        _ad("LOADN", a=2, d=5),
        _abc("SETTABLE", a=2, b=0, c=1),
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code), {}, "boolean-key.luau")

    assert "{[true] = 5}" in output


def test_noncontiguous_open_setlist_uses_conservative_fallback() -> None:
    constants = (LuauConstant("string", "collect", 3),)
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _ad("LOADN", a=1, d=2),
        _abc("SETTABLEN", a=1, b=0, c=1),
        _abc("GETGLOBAL", a=1),
        0,
        _abc("CALL", a=1, b=1, c=0),
        _abc("SETLIST", a=0, b=1, c=0),
        2,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "open-gap.luau")

    assert "{[2] = 2}" in output
    assert "multiple returns" in output
    assert "set all stack values" in output
