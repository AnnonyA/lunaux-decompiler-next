from __future__ import annotations

from lunaux.backends.analysis import analyze_control_flow
from lunaux.backends.bytecode import LuauProto
from lunaux.backends.inlining import plan_expression_inlining
from lunaux.backends.opcodes import decode_words, opcode_names
from lunaux.backends.ssa import build_ssa


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, a: int, b: int, c: int) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, a: int, d: int) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(code: tuple[int, ...]) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=16,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=(),
        child_proto_ids=(),
        line_defined=1,
        debug_name=None,
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )


def _plan(proto: LuauProto):
    instructions = tuple(decode_words(proto.code))
    analysis = analyze_control_flow(instructions, len(proto.code))
    ssa = build_ssa(instructions, len(proto.code), analysis=analysis)
    return ssa, plan_expression_inlining(ssa, proto)


def test_single_use_literal_can_cross_short_pure_gap() -> None:
    proto = _proto(
        (
            _ad("LOADN", 0, 2),
            _ad("LOADN", 3, 10),
            _abc("ADDK", 1, 0, 0),
            _abc("RETURN", 1, 2, 0),
        )
    )

    ssa, plan = _plan(proto)
    literal = ssa.value_defined_at(0, 0)

    assert plan.should_inline(literal)


def test_expression_is_not_moved_past_source_register_redefinition() -> None:
    proto = _proto(
        (
            _ad("LOADN", 0, 2),
            _abc("ADDK", 1, 0, 0),
            _ad("LOADN", 0, 9),
            _abc("RETURN", 1, 2, 0),
        )
    )

    ssa, plan = _plan(proto)
    expression = ssa.value_defined_at(1, 1)

    assert not plan.should_inline(expression)
