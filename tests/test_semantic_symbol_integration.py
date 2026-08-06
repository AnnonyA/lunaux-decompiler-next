from __future__ import annotations

from lunaux.backends.analysis import analyze_control_flow
from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.opcodes import decode_words, opcode_names
from lunaux.backends.ssa import build_ssa
from lunaux.backends.symbols import build_symbol_recovery


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, a: int, b: int, c: int) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, a: int, d: int) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(code: tuple[int, ...], constants: tuple[LuauConstant, ...]) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=16,
        num_params=0,
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


def _recover(proto: LuauProto):
    module = LuauBytecodeModule(
        version=13,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )
    instructions = tuple(decode_words(proto.code))
    analysis = analyze_control_flow(instructions, len(proto.code))
    ssa = build_ssa(instructions, len(proto.code), analysis=analysis)
    return build_symbol_recovery(module, proto, instructions, ssa)


def test_instance_new_pattern_flows_into_recovered_symbol() -> None:
    constants = (
        LuauConstant("string", "Instance", 3),
        LuauConstant("string", "new", 3),
        LuauConstant("string", "Part", 3),
    )
    proto = _proto(
        (
            _abc("GETGLOBAL", 0, 0, 0),
            0,
            _abc("GETTABLEKS", 0, 0, 0),
            1,
            _ad("LOADK", 1, 2),
            _abc("CALL", 0, 2, 2),
            _abc("RETURN", 0, 2, 0),
        ),
        constants,
    )

    recovery = _recover(proto)

    assert recovery.name_at_definition(5, 0) == "part"
    assert recovery.type_at_definition(5, 0) == "Part"
    assert recovery.return_type == "Part"


def test_gettagged_pattern_produces_semantic_collection_name() -> None:
    constants = (
        LuauConstant("string", "CollectionService", 3),
        LuauConstant("string", "GetTagged", 3),
        LuauConstant("string", "Enemy", 3),
    )
    proto = _proto(
        (
            _abc("GETGLOBAL", 0, 0, 0),
            0,
            _abc("NAMECALL", 1, 0, 0),
            1,
            _ad("LOADK", 3, 2),
            _abc("CALL", 1, 3, 2),
            _abc("RETURN", 1, 2, 0),
        ),
        constants,
    )

    recovery = _recover(proto)

    assert recovery.name_at_definition(5, 1) == "taggedEnemies"
    assert recovery.type_at_definition(5, 1) == "{Instance}"
