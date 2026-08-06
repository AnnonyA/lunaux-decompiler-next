from __future__ import annotations

from lunaux.backends.bytecode import LuauConstant, LuauProto
from lunaux.backends.flow_types import FlowTypeAnalysis, analyze_flow_types
from lunaux.backends.opcodes import decode_words, opcode_names
from lunaux.backends.ssa import build_ssa


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    return opcode_names().index(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, *, a: int = 0, d: int = 0) -> int:
    return opcode_names().index(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(
    code: tuple[int, ...],
    constants: tuple[LuauConstant, ...] = (),
    *,
    params: int = 1,
    stack: int = 4,
) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=stack,
        num_params=params,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=constants,
        child_proto_ids=(),
        line_defined=1,
        debug_name="flow",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )


def _analyze(proto: LuauProto, base_types: dict[int, str]) -> FlowTypeAnalysis:
    instructions = tuple(decode_words(proto.code))
    program = build_ssa(instructions, len(proto.code))
    types = {program.entry_values[register]: value for register, value in base_types.items()}
    return analyze_flow_types(proto, instructions, program, types)


def test_nil_branch_refines_each_successor_independently() -> None:
    proto = _proto(
        (
            _ad("JUMPXEQKNIL", a=0, d=4),
            0,
            _abc("GETTABLEKS", a=1, b=0),
            0,
            _abc("RETURN", a=0, b=1),
            _abc("RETURN", a=0, b=2),
        ),
        (LuauConstant("string", "Name", 3),),
        stack=2,
    )
    analysis = _analyze(proto, {0: "Instance?"})

    assert analysis.type_at_use(2, 0) == "Instance"
    assert analysis.type_at_use(5, 0) == "nil"
    assert analysis.evidence_at_use(2, 0) == "nil check false branch"


def test_typeof_refines_original_value_through_move_argument() -> None:
    proto = _proto(
        (
            _abc("GETGLOBAL", a=1),
            0,
            _abc("MOVE", a=2, b=0),
            _abc("CALL", a=1, b=2, c=2),
            _ad("JUMPXEQKS", a=1, d=4),
            1,
            _abc("GETTABLEKS", a=1, b=0),
            2,
            _abc("RETURN", a=0, b=1),
            _abc("RETURN", a=0, b=2),
        ),
        (
            LuauConstant("string", "typeof", 3),
            LuauConstant("string", "Instance", 3),
            LuauConstant("string", "Name", 3),
        ),
        stack=3,
    )
    analysis = _analyze(proto, {0: "any"})

    assert analysis.type_at_use(9, 0) == "Instance"
    assert analysis.type_at_use(6, 0) is None
    assert analysis.evidence_at_use(9, 0) == 'typeof(value) == "Instance"'


def test_isa_refines_receiver_only_on_true_edge() -> None:
    proto = _proto(
        (
            _ad("LOADK", a=3, d=1),
            _abc("NAMECALL", a=1, b=0),
            0,
            _abc("CALL", a=1, b=3, c=2),
            _ad("JUMPIF", a=1, d=1),
            _abc("RETURN", a=0, b=2),
            _abc("RETURN", a=0, b=2),
        ),
        (
            LuauConstant("string", "IsA", 3),
            LuauConstant("string", "BasePart", 3),
        ),
        stack=4,
    )
    analysis = _analyze(proto, {0: "Instance"})

    assert analysis.type_at_use(6, 0) == "BasePart"
    assert analysis.type_at_use(5, 0) is None
    assert analysis.evidence_at_use(6, 0) == 'IsA("BasePart") true branch'


def test_assert_removes_nil_for_following_uses() -> None:
    proto = _proto(
        (
            _abc("GETGLOBAL", a=0),
            0,
            _abc("CALL", a=0, b=2, c=2),
            _abc("GETTABLEKS", a=0, b=1),
            1,
            _abc("RETURN", a=1, b=2),
        ),
        (
            LuauConstant("string", "assert", 3),
            LuauConstant("string", "Name", 3),
        ),
        params=2,
        stack=2,
    )
    analysis = _analyze(proto, {1: "Instance?"})

    assert analysis.type_at_use(3, 1) == "Instance"
    assert analysis.type_at_use(5, 1) == "Instance"
    assert analysis.evidence_at_use(3, 1) == "assert removes nil"


def test_join_discards_fact_missing_from_one_predecessor() -> None:
    proto = _proto(
        (
            _ad("JUMPIF", a=0, d=2),
            _ad("JUMP", d=3),
            _abc("NOP"),
            _abc("MOVE", a=1, b=0),
            _ad("JUMP", d=0),
            _abc("GETTABLEKS", a=1, b=0),
            0,
            _abc("RETURN", a=0, b=2),
        ),
        (LuauConstant("string", "Name", 3),),
        stack=2,
    )
    analysis = _analyze(proto, {0: "Instance?"})

    assert analysis.type_at_use(3, 0) == "Instance"
    assert analysis.type_at_use(5, 0) is None
