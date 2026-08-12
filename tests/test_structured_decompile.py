from __future__ import annotations

from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import opcode_names
from lunaux.backends.reconstructed import decompile_module as decompile_reconstructed_module


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


def test_closes_nested_if_before_transitioning_outer_else() -> None:
    proto = _proto(
        (
            _ad("JUMPIFNOT", a=0, d=7),
            _ad("JUMPIFNOT", a=1, d=3),
            _ad("LOADN", a=2, d=10),
            _abc("SETUPVAL", a=2, b=0),
            _ad("JUMP", d=3),
            _ad("LOADN", a=2, d=20),
            _abc("SETUPVAL", a=2, b=0),
            _ad("JUMP", d=2),
            _ad("LOADN", a=2, d=30),
            _abc("SETUPVAL", a=2, b=0),
            _abc("RETURN", b=1),
        ),
        num_params=2,
        max_stack_size=3,
    )

    result = decompile_module(_module(proto), {}, "NestedIfOuterElse")

    assert """if arg1 then
    if arg2 then
        upvalue_0 = 10
    else
        upvalue_0 = 20
    end
else
    upvalue_0 = 30
end""" in result
    assert "else\n    else" not in result


def test_generic_for_is_not_reclassified_as_repeat_regions() -> None:
    proto = _proto(
        (
            _abc("LOADNIL", a=0),
            _abc("LOADNIL", a=1),
            _abc("LOADNIL", a=2),
            _ad("FORGPREP", a=0, d=2),
            _abc("SETUPVAL", a=3, b=0),
            _abc("NOP"),
            _ad("FORGLOOP", a=0, d=-3),
            1,
            _abc("RETURN", b=1),
        ),
        max_stack_size=4,
    )

    result = decompile_module(_module(proto), {}, "GenericFor")

    assert "for " in result
    assert "until" not in result
    assert "repeat" not in result


def test_advanced_loop_action_is_not_reopened_as_legacy_while() -> None:
    proto = _proto(
        (
            _abc("LOADB", a=0, b=1),
            _ad("JUMPIF", a=0, d=3),
            _ad("LOADN", a=1, d=1),
            _abc("SETUPVAL", a=1, b=0),
            _ad("JUMPBACK", d=-5),
            _abc("RETURN", b=1),
        ),
        max_stack_size=2,
    )

    result = decompile_module(_module(proto), {}, "AdvancedLoopBreak")

    assert result.count("while ") == 1
    assert "while not true do" in result


def test_phi_declaration_assignment_and_uses_share_one_name() -> None:
    constants = (
        LuauConstant(kind="string", value="Model", tag=3),
        LuauConstant(kind="string", value="IsA", tag=3),
        LuauConstant(kind="string", value="PrimaryPart", tag=3),
    )
    proto = _proto(
        (
            _ad("LOADK", a=4, d=0),
            _abc("NAMECALL", a=2, b=0),
            1,
            _abc("CALL", a=2, b=3, c=2),
            _ad("JUMPIFNOT", a=2, d=3),
            _abc("GETTABLEKS", a=1, b=0),
            2,
            _ad("JUMP", d=1),
            _abc("MOVE", a=1, b=0),
            _ad("JUMPIF", a=1, d=1),
            _abc("RETURN", b=1),
            _abc("RETURN", a=1, b=2),
        ),
        constants=constants,
        num_params=1,
        max_stack_size=5,
    )

    result = decompile_reconstructed_module(_module(proto), {}, "PhiName")

    assert "local result\nresult = if" in result
    assert "if not result then" in result
    assert "return result" in result
    assert "PrimaryPart2" not in result
