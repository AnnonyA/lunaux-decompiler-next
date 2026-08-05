from __future__ import annotations

from lunaux.backends.bytecode import LocalInfo, LuauBytecodeModule, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import opcode_names


def _ad(name: str, a: int, d: int) -> int:
    opcode = opcode_names().index(name)
    return opcode | (a << 8) | ((d & 0xFFFF) << 16)


def _abc(name: str, a: int, b: int, c: int) -> int:
    opcode = opcode_names().index(name)
    return opcode | (a << 8) | (b << 16) | (c << 24)


def _module(
    code: tuple[int, ...],
    *,
    locals_: tuple[LocalInfo, ...] = (),
) -> LuauBytecodeModule:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=8,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=(),
        child_proto_ids=(),
        line_defined=0,
        debug_name=None,
        line_info=(),
        locals=locals_,
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


def test_inlines_adjacent_single_use_value_by_default() -> None:
    module = _module(
        (
            _ad("LOADN", 0, 42),
            _abc("RETURN", 0, 2, 0),
        )
    )

    source = decompile_module(module, {}, "inline.luac")

    assert "local v0 = 42" not in source
    assert "return 42" in source


def test_can_disable_temporary_inlining() -> None:
    module = _module(
        (
            _ad("LOADN", 0, 42),
            _abc("RETURN", 0, 2, 0),
        )
    )

    source = decompile_module(
        module,
        {"InlineSingleUseTemporaries": False},
        "inline.luac",
    )

    assert "local v0 = 42" in source
    assert "return v0" in source


def test_preserves_debug_named_local() -> None:
    module = _module(
        (
            _ad("LOADN", 0, 42),
            _abc("RETURN", 0, 2, 0),
        ),
        locals_=(LocalInfo(name="answer", start_pc=0, end_pc=2, register=0),),
    )

    source = decompile_module(module, {}, "named.luac")

    assert "local answer = 42" in source
    assert "return answer" in source


def test_folds_a_short_expression_chain() -> None:
    module = _module(
        (
            _ad("LOADN", 0, 4),
            _abc("MINUS", 1, 0, 0),
            _abc("RETURN", 1, 2, 0),
        )
    )

    source = decompile_module(module, {}, "chain.luac")

    assert "local v0" not in source
    assert "local v1" not in source
    assert "return -4" in source


def test_does_not_duplicate_a_value_used_twice_by_one_instruction() -> None:
    module = _module(
        (
            _ad("LOADN", 0, 2),
            _abc("ADD", 1, 0, 0),
            _abc("RETURN", 1, 2, 0),
        )
    )

    source = decompile_module(module, {}, "duplicate.luac")

    assert "local v0 = 2" in source
    assert "return (v0 + v0)" in source
