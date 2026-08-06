from __future__ import annotations

from lunaux.backends.bytecode import LocalInfo, LuauProto
from lunaux.backends.inlining import (
    parenthesize_inlined_expression,
    plan_expression_inlining,
)
from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.ssa import build_ssa


def _instruction(
    pc: int,
    name: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
    d: int = 0,
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
        d=d,
        e=0,
        aux=None,
    )


def _proto(*, locals_: tuple[LocalInfo, ...] = ()) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=8,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=(),
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


def test_plans_adjacent_single_use_temporary() -> None:
    instructions = [
        _instruction(0, "LOADN", a=0, d=42),
        _instruction(1, "RETURN", a=0, b=2),
    ]
    program = build_ssa(instructions, code_size=2)
    plan = plan_expression_inlining(program, _proto())
    value = program.value_defined_at(0, 0)

    assert value is not None
    assert plan.should_inline(value)
    assert plan.candidate_for_definition(0, 0) is not None


def test_allows_non_adjacent_use_across_pure_nop() -> None:
    instructions = [
        _instruction(0, "LOADN", a=0, d=42),
        _instruction(1, "NOP"),
        _instruction(2, "RETURN", a=0, b=2),
    ]
    program = build_ssa(instructions, code_size=3)
    value = program.value_defined_at(0, 0)

    assert value is not None
    assert plan_expression_inlining(program, _proto()).should_inline(value)


def test_rejects_non_adjacent_use_across_control_flow_block() -> None:
    instructions = [
        _instruction(0, "LOADN", a=0, d=42),
        _instruction(1, "JUMP", d=1),
        _instruction(2, "NOP"),
        _instruction(3, "RETURN", a=0, b=2),
    ]
    program = build_ssa(instructions, code_size=4)
    value = program.value_defined_at(0, 0)

    assert value is not None
    assert not plan_expression_inlining(program, _proto()).should_inline(value)


def test_rejects_duplicate_evaluation_in_one_consumer() -> None:
    instructions = [
        _instruction(0, "GETGLOBAL", a=0),
        _instruction(1, "ADD", a=1, b=0, c=0),
        _instruction(2, "RETURN", a=1, b=2),
    ]
    program = build_ssa(instructions, code_size=3)
    value = program.value_defined_at(0, 0)

    assert value is not None
    assert not plan_expression_inlining(program, _proto()).should_inline(value)


def test_preserves_named_debug_locals() -> None:
    instructions = [
        _instruction(0, "LOADN", a=0, d=42),
        _instruction(1, "RETURN", a=0, b=2),
    ]
    program = build_ssa(instructions, code_size=2)
    proto = _proto(locals_=(LocalInfo(name="answer", start_pc=0, end_pc=2, register=0),))
    value = program.value_defined_at(0, 0)

    assert value is not None
    assert not plan_expression_inlining(program, proto).should_inline(value)


def test_rejects_loadb_with_skip_control_flow() -> None:
    instructions = [
        _instruction(0, "LOADB", a=0, b=1, c=1),
        _instruction(1, "RETURN", a=0, b=2),
        _instruction(2, "RETURN", a=0, b=2),
    ]
    program = build_ssa(instructions, code_size=3)
    value = program.value_defined_at(0, 0)

    assert value is not None
    assert not plan_expression_inlining(program, _proto()).should_inline(value)


def test_parenthesizes_only_compound_expressions() -> None:
    assert parenthesize_inlined_expression("42") == "42"
    assert parenthesize_inlined_expression('"hello"') == '"hello"'
    assert parenthesize_inlined_expression("value") == "value"
    assert parenthesize_inlined_expression("a + b") == "(a + b)"
    assert parenthesize_inlined_expression("(a + b)") == "(a + b)"
