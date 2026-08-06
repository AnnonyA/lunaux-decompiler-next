from __future__ import annotations

from lunaux.backends.analysis import analyze_control_flow
from lunaux.backends.bytecode import LuauConstant, LuauProto
from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.state_machine import recover_state_machines


def _instruction(
    name: str,
    pc: int,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
    d: int = 0,
    aux: int | None = None,
) -> DecodedInstruction:
    return DecodedInstruction(
        pc=pc,
        word=0,
        opcode=opcode_names().index(name),
        name=name,
        a=a,
        b=b,
        c=c,
        d=d,
        e=0,
        aux=aux,
    )


def _proto(constants: tuple[LuauConstant, ...] = ()) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=8,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=(),
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


def _recover(
    proto: LuauProto,
    instructions: tuple[DecodedInstruction, ...],
):
    return recover_state_machines(
        proto,
        instructions,
        analyze_control_flow(instructions, 13),
    )


def test_unflattens_boolean_state_cycle() -> None:
    instructions = (
        _instruction("LOADB", 0, a=0, b=0),
        _instruction("JUMP", 1, d=0),
        _instruction("JUMPXEQKB", 2, a=0, d=4, aux=0),
        _instruction("JUMPXEQKB", 4, a=0, d=5, aux=1),
        _instruction("JUMPBACK", 6, d=-5),
        _instruction("LOADN", 7, a=1, d=10),
        _instruction("LOADB", 8, a=0, b=1),
        _instruction("JUMPBACK", 9, d=-8),
        _instruction("LOADN", 10, a=2, d=20),
        _instruction("LOADB", 11, a=0, b=0),
        _instruction("JUMPBACK", 12, d=-11),
    )

    region = _recover(_proto(), instructions).at(0)

    assert region is not None
    assert region.kind == "cycle"
    assert [case.state for case in region.cases] == [False, True]
    assert region.ordered_body_pcs == (7, 10)
    assert "boolean" in region.evidence[2]


def test_unflattens_string_state_cycle() -> None:
    constants = (
        LuauConstant("string", "start", 3),
        LuauConstant("string", "done", 3),
    )
    instructions = (
        _instruction("LOADK", 0, a=0, d=0),
        _instruction("JUMP", 1, d=0),
        _instruction("JUMPXEQKS", 2, a=0, d=4, aux=0),
        _instruction("JUMPXEQKS", 4, a=0, d=5, aux=1),
        _instruction("JUMPBACK", 6, d=-5),
        _instruction("LOADN", 7, a=1, d=10),
        _instruction("LOADK", 8, a=0, d=1),
        _instruction("JUMPBACK", 9, d=-8),
        _instruction("LOADN", 10, a=2, d=20),
        _instruction("LOADK", 11, a=0, d=0),
        _instruction("JUMPBACK", 12, d=-11),
    )

    region = _recover(_proto(constants), instructions).at(0)

    assert region is not None
    assert [case.state for case in region.cases] == ["start", "done"]
    assert "string" in region.evidence[2]


def test_unflattens_transition_back_to_nil() -> None:
    instructions = (
        _instruction("LOADNIL", 0, a=0),
        _instruction("JUMP", 1, d=0),
        _instruction("JUMPXEQKNIL", 2, a=0, d=4, aux=0),
        _instruction("JUMPXEQKB", 4, a=0, d=5, aux=1),
        _instruction("JUMPBACK", 6, d=-5),
        _instruction("LOADN", 7, a=1, d=10),
        _instruction("LOADB", 8, a=0, b=1),
        _instruction("JUMPBACK", 9, d=-8),
        _instruction("LOADN", 10, a=2, d=20),
        _instruction("LOADNIL", 11, a=0),
        _instruction("JUMPBACK", 12, d=-11),
    )

    region = _recover(_proto(), instructions).at(0)

    assert region is not None
    assert region.kind == "cycle"
    assert [case.state for case in region.cases] == [None, True]
    assert region.cases[1].transition_state is None
    assert region.cases[1].transition_pc == 11


def test_boolean_false_and_numeric_zero_remain_distinct_states() -> None:
    constants = (LuauConstant("number", 0.0, 2),)
    instructions = (
        _instruction("LOADB", 0, a=0, b=0),
        _instruction("JUMP", 1, d=0),
        _instruction("JUMPXEQKB", 2, a=0, d=4, aux=0),
        _instruction("JUMPXEQKN", 4, a=0, d=5, aux=0),
        _instruction("JUMPBACK", 6, d=-5),
        _instruction("LOADN", 7, a=1, d=10),
        _instruction("LOADK", 8, a=0, d=0),
        _instruction("JUMPBACK", 9, d=-8),
        _instruction("LOADN", 10, a=2, d=20),
        _instruction("LOADB", 11, a=0, b=0),
        _instruction("JUMPBACK", 12, d=-11),
    )

    region = _recover(_proto(constants), instructions).at(0)

    assert region is not None
    assert [case.state for case in region.cases] == [False, 0.0]
    assert "boolean" in region.evidence[2]
    assert "number" in region.evidence[2]


def test_rejects_selector_with_wrong_constant_kind() -> None:
    constants = (
        LuauConstant("number", 0.0, 2),
        LuauConstant("number", 1.0, 2),
    )
    instructions = (
        _instruction("LOADK", 0, a=0, d=0),
        _instruction("JUMP", 1, d=0),
        _instruction("JUMPXEQKS", 2, a=0, d=4, aux=0),
        _instruction("JUMPXEQKN", 4, a=0, d=5, aux=1),
        _instruction("JUMPBACK", 6, d=-5),
        _instruction("LOADN", 7, a=1, d=10),
        _instruction("LOADK", 8, a=0, d=1),
        _instruction("JUMPBACK", 9, d=-8),
        _instruction("LOADN", 10, a=2, d=20),
        _instruction("LOADK", 11, a=0, d=0),
        _instruction("JUMPBACK", 12, d=-11),
    )

    assert not _recover(_proto(constants), instructions).regions
