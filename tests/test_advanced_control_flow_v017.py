from __future__ import annotations

from lunaux.backends.advanced_loops import analyze_advanced_loops
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
    e: int = 0,
    aux: int | None = None,
) -> DecodedInstruction:
    opcode = opcode_names().index(name)
    return DecodedInstruction(
        pc=pc,
        word=0,
        opcode=opcode,
        name=name,
        a=a,
        b=b,
        c=c,
        d=d,
        e=e,
        aux=aux,
    )


def _proto(constants: tuple[LuauConstant, ...]) -> LuauProto:
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


def test_recovers_while_break_continue_and_backedge() -> None:
    instructions = (
        _instruction("JUMPIF", 0, a=0, d=5),
        _instruction("LOADN", 1, a=2, d=1),
        _instruction("JUMPIF", 2, a=1, d=3),
        _instruction("JUMPIF", 3, a=2, d=-4),
        _instruction("LOADN", 4, a=3, d=5),
        _instruction("JUMPBACK", 5, d=-6),
        _instruction("RETURN", 6, a=0, b=1),
    )
    analysis = analyze_control_flow(instructions, 7)
    plan = analyze_advanced_loops(analysis, instructions)

    region = plan.by_open_pc[0]
    assert region.kind == "while"
    assert region.close_pc == 6
    assert plan.actions[2].kind == "break"
    assert plan.actions[2].edge == "taken"
    assert plan.actions[3].kind == "continue"
    assert plan.actions[3].edge == "taken"
    assert {0, 5} <= plan.skipped_pcs


def test_recovers_repeat_with_internal_break_and_continue() -> None:
    instructions = (
        _instruction("LOADN", 0, a=1, d=1),
        _instruction("LOADN", 1, a=2, d=2),
        _instruction("JUMPIF", 2, a=3, d=2),
        _instruction("JUMP", 3, d=0),
        _instruction("JUMPIF", 4, a=4, d=-5),
        _instruction("RETURN", 5, a=0, b=1),
    )
    analysis = analyze_control_flow(instructions, 6)
    plan = analyze_advanced_loops(analysis, instructions)

    region = plan.by_open_pc[0]
    assert region.kind == "repeat"
    assert region.condition_pc == 4
    assert region.continue_target == 4
    assert plan.actions[2].kind == "break"
    assert plan.actions[3].kind == "continue"
    assert 4 in plan.skipped_pcs


def test_recovers_infinite_loop_with_explicit_break() -> None:
    instructions = (
        _instruction("LOADN", 0, a=1, d=1),
        _instruction("JUMPIF", 1, a=2, d=2),
        _instruction("LOADN", 2, a=3, d=3),
        _instruction("JUMPBACK", 3, d=-4),
        _instruction("RETURN", 4, a=0, b=1),
    )
    analysis = analyze_control_flow(instructions, 5)
    plan = analyze_advanced_loops(analysis, instructions)

    region = plan.by_open_pc[0]
    assert region.kind == "infinite"
    assert plan.actions[1].kind == "break"
    assert 3 in plan.skipped_pcs


def _cycle_machine() -> tuple[LuauProto, tuple[DecodedInstruction, ...]]:
    constants = (
        LuauConstant("number", 0.0, 2),
        LuauConstant("number", 1.0, 2),
    )
    instructions = (
        _instruction("LOADK", 0, a=0, d=0),
        _instruction("JUMP", 1, d=0),
        _instruction("JUMPXEQKN", 2, a=0, d=4, aux=0),
        _instruction("JUMPXEQKN", 4, a=0, d=5, aux=1),
        _instruction("JUMPBACK", 6, d=-5),
        _instruction("LOADN", 7, a=1, d=10),
        _instruction("LOADK", 8, a=0, d=1),
        _instruction("JUMPBACK", 9, d=-8),
        _instruction("LOADN", 10, a=2, d=20),
        _instruction("LOADK", 11, a=0, d=0),
        _instruction("JUMPBACK", 12, d=-11),
    )
    return _proto(constants), instructions


def test_unflattens_constant_state_cycle_in_transition_order() -> None:
    proto, instructions = _cycle_machine()
    analysis = analyze_control_flow(instructions, 13)
    plan = recover_state_machines(proto, instructions, analysis)

    region = plan.at(0)
    assert region is not None
    assert region.kind == "cycle"
    assert [case.state for case in region.cases] == [0.0, 1.0]
    assert region.ordered_body_pcs == (7, 10)
    assert {0, 1, 2, 4, 6, 7, 8, 9, 10, 11, 12} <= region.skipped_pcs


def test_unflattens_linear_machine_with_terminal_case_outside_loop() -> None:
    constants = (
        LuauConstant("number", 0.0, 2),
        LuauConstant("number", 1.0, 2),
    )
    instructions = (
        _instruction("LOADK", 0, a=0, d=0),
        _instruction("JUMP", 1, d=0),
        _instruction("JUMPXEQKN", 2, a=0, d=4, aux=0),
        _instruction("JUMPXEQKN", 4, a=0, d=5, aux=1),
        _instruction("JUMPBACK", 6, d=-5),
        _instruction("LOADN", 7, a=1, d=10),
        _instruction("LOADK", 8, a=0, d=1),
        _instruction("JUMPBACK", 9, d=-8),
        _instruction("LOADN", 10, a=2, d=20),
        _instruction("RETURN", 11, a=2, b=2),
    )
    proto = _proto(constants)
    analysis = analyze_control_flow(instructions, 12)
    plan = recover_state_machines(proto, instructions, analysis)

    region = plan.at(0)
    assert region is not None
    assert region.kind == "linear"
    assert [case.state for case in region.cases] == [0.0, 1.0]
    assert region.ordered_body_pcs == (7, 10, 11)


def test_rejects_machine_when_state_escapes_case_logic() -> None:
    proto, original = _cycle_machine()
    instructions = tuple(
        _instruction("MOVE", 7, a=3, b=0) if instruction.pc == 7 else instruction
        for instruction in original
    )
    analysis = analyze_control_flow(instructions, 13)

    assert not recover_state_machines(proto, instructions, analysis).regions


def test_control_flow_options_can_disable_each_pass() -> None:
    instructions = (
        _instruction("JUMPIF", 0, a=0, d=2),
        _instruction("JUMPBACK", 1, d=-2),
        _instruction("RETURN", 3, a=0, b=1),
    )
    analysis = analyze_control_flow(instructions, 4)

    assert not analyze_advanced_loops(analysis, instructions, enabled=False).regions
    assert not recover_state_machines(_proto(()), instructions, analysis, enabled=False).regions
