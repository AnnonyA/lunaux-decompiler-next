from __future__ import annotations

from lunaux.backends.bytecode import LuauConstant, LuauProto
from lunaux.backends.flow_types import analyze_flow_types
from lunaux.backends.opcodes import decode_words, opcode_names
from lunaux.backends.ssa import build_ssa


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    return opcode_names().index(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, *, a: int = 0, d: int = 0) -> int:
    return opcode_names().index(name) | (a << 8) | ((d & 0xFFFF) << 16)


def test_nil_branch_refines_each_successor_independently() -> None:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=2,
        num_params=1,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=(
            _ad("JUMPXEQKNIL", a=0, d=4),
            0,
            _abc("GETTABLEKS", a=1, b=0),
            0,
            _abc("RETURN", a=0, b=1),
            _abc("RETURN", a=0, b=2),
        ),
        constants=(LuauConstant("string", "Name", 3),),
        child_proto_ids=(),
        line_defined=1,
        debug_name="flow",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    instructions = tuple(decode_words(proto.code))
    program = build_ssa(instructions, len(proto.code))
    entry = program.entry_values[0]
    analysis = analyze_flow_types(
        proto,
        instructions,
        program,
        {entry: "Instance?"},
    )

    assert analysis.type_at_use(2, 0) == "Instance"
    assert analysis.type_at_use(5, 0) == "nil"
    assert analysis.evidence_at_use(2, 0) == "nil check false branch"
