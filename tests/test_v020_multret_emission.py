from __future__ import annotations

from lunaux.backends.bytecode import LuauBytecodeModule, LuauProto
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
    params: int,
    stack: int,
    is_vararg: bool = False,
) -> LuauBytecodeModule:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=stack,
        num_params=params,
        num_upvalues=0,
        is_vararg=is_vararg,
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


def test_open_call_is_emitted_as_final_multiple_return_expression() -> None:
    module = _module(
        (
            _abc("CALL", a=2, b=1, c=0),
            _abc("RETURN", a=0, b=0),
        ),
        params=3,
        stack=3,
    )

    output = decompile_module(module, {}, "multret-return.luau")

    assert "return arg1, arg2, arg3()" in output
    assert "multiple returns" not in output
    assert "stack top" not in output


def test_open_varargs_become_final_arguments_and_call_result_is_returned() -> None:
    module = _module(
        (
            _abc("GETVARARGS", a=2, b=0),
            _abc("CALL", a=0, b=0, c=0),
            _abc("RETURN", a=0, b=0),
        ),
        params=2,
        stack=3,
        is_vararg=True,
    )

    output = decompile_module(module, {}, "multret-chain.luau")

    assert "return arg1(arg2, ...)" in output
    assert "all arguments through stack top" not in output
    assert "multiple returns" not in output


def test_unproven_open_tuple_keeps_conservative_fallback() -> None:
    module = _module(
        (
            _abc("CALL", a=1, b=1, c=0),
            _ad("LOADN", a=2, d=5),
            _abc("RETURN", a=0, b=0),
        ),
        params=2,
        stack=3,
    )

    output = decompile_module(module, {}, "multret-fallback.luau")

    assert "multiple returns" in output
    assert "stack top" in output
