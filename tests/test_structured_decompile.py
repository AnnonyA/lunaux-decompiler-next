from __future__ import annotations

from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import opcode_names


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, a: int = 0, b: int = 0, c: int = 0) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, a: int = 0, d: int = 0) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(
    code: tuple[int, ...],
    *,
    constants: tuple[LuauConstant, ...] = (),
    num_params: int = 0,
    max_stack_size: int = 4,
) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=max_stack_size,
        num_params=num_params,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=constants,
        child_proto_ids=(),
        line_defined=1,
        debug_name=None,
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )


def _module(proto: LuauProto) -> LuauBytecodeModule:
    return LuauBytecodeModule(
        version=12,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def test_decompiles_phi_diamond_to_if_expression() -> None:
    proto = _proto(
        (
            _ad("JUMPIFNOT", a=0, d=2),
            _ad("LOADN", a=1, d=10),
            _ad("JUMP", d=1),
            _ad("LOADN", a=1, d=20),
            _abc("RETURN", a=1, b=2),
        ),
        num_params=1,
        max_stack_size=2,
    )

    result = decompile_module(_module(proto), {}, "PhiDiamond")

    assert "local result = 20" in result
    assert "if arg1 then" in result
    assert "result = 10" in result
    assert "return result" in result
    assert "jump to" not in result


def test_decompiles_straight_line_table_writes_to_literal() -> None:
    constants = (
        LuauConstant(kind="string", value="Sword", tag=3),
        LuauConstant(kind="string", value="Name", tag=3),
        LuauConstant(kind="string", value="Damage", tag=3),
        LuauConstant(kind="string", value="Fire", tag=3),
    )
    proto = _proto(
        (
            _abc("NEWTABLE", a=0),
            0,
            _ad("LOADK", a=1, d=0),
            _abc("SETTABLEKS", a=1, b=0),
            1,
            _ad("LOADN", a=1, d=25),
            _abc("SETTABLEKS", a=1, b=0),
            2,
            _ad("LOADK", a=1, d=3),
            _abc("SETTABLEN", a=1, b=0, c=0),
            _abc("RETURN", a=0, b=2),
        ),
        constants=constants,
        max_stack_size=2,
    )

    result = decompile_module(_module(proto), {}, "TableLiteral")

    assert '{Name = "Sword", Damage = 25, "Fire"}' in result
    assert ".Name =" not in result
    assert ".Damage =" not in result
