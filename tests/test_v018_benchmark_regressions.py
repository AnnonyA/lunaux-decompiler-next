from __future__ import annotations

from lunaux.backends.bytecode import (
    LuauBytecodeModule,
    LuauProto,
    TypedLocalInfo,
)
from lunaux.backends.multret_lifter import decompile_module
from lunaux.backends.opcodes import opcode_names


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, *, a: int = 0, d: int = 0) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _module(
    code: tuple[int, ...],
    *,
    typed_locals: tuple[TypedLocalInfo, ...] = (),
    stack: int = 8,
) -> LuauBytecodeModule:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=stack,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=(),
        child_proto_ids=(),
        line_defined=1,
        debug_name="main",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
        typed_locals=typed_locals,
    )
    return LuauBytecodeModule(
        version=6,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def test_setlist_aux_is_already_one_based() -> None:
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _ad("LOADN", a=1, d=10),
        _ad("LOADN", a=2, d=20),
        _abc("SETLIST", a=0, b=1, c=3),
        1,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code), {}, "setlist-v6.luau")

    assert "{10, 20}" in output
    assert "[2] = 10" not in output
    assert "[3] = 20" not in output


def test_bare_function_bytecode_type_is_not_emitted_as_invalid_luau() -> None:
    code = (
        _abc("LOADNIL", a=0),
        _abc("RETURN", a=0, b=1),
    )
    typed = (TypedLocalInfo(type_tag=5, register=0, start_pc=0, end_pc=2),)

    output = decompile_module(_module(code, typed_locals=typed), {}, "function-type.luau")

    assert ": function" not in output
