from __future__ import annotations

import base64

from lunaux.backends.bytecode import (
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
    parse_bytecode,
)
from lunaux.backends.callframe import plan_call_frames
from lunaux.backends.module_analysis import build_module_analysis
from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.read_modify_write import StorageKind, plan_read_modify_write
from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.backends.scopes import build_scope_tree
from lunaux.backends.ssa import build_ssa
from lunaux.benchmark_engine import default_options

_REAL_V6_TABLES = (
    "BgMGBmNhc2UtMAROYW1lBVNjb3JlB0VuYWJsZWQFU3RhdHMFcHJpbnQAAQUAAAECACZBAAAA"
    "NQACAAIAAAAFAwAAEAMAugEAAAA2AwQABAQAABAEAyICAAAAAwQBABAEA/ADAAAAEAMAIQUAAAAE"
    "AQAABAIAADcAAQMBAAAADwEAIQUAAAAPAgEiAgAAABEDAAAhAgIDEAIBIgIAAAAMAQcAAABgQA8C"
    "ALoBAAAADwQAIQUAAAAPAwQiAgAAABEEAAEVAQQBFgABAAgDAQMCAwMDBAUCAgMDBQMGBAAAYEAAAQ"
    "AAAAA="
)


def _instruction(
    pc: int,
    name: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
    aux: int | None = None,
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
        d=0,
        e=0,
        aux=aux,
    )


def _proto(
    *,
    params: int = 3,
    constants: tuple[LuauConstant, ...] = (),
) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=8,
        num_params=params,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=(),
        constants=constants,
        child_proto_ids=(),
        line_defined=0,
        debug_name=None,
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )


def _field_program(*, call_barrier: bool = False, mismatched: bool = False):
    instructions = [_instruction(0, "GETTABLEKS", a=1, b=0, aux=0)]
    operation_pc = 2
    if call_barrier:
        instructions.append(_instruction(2, "CALL", a=4, b=1, c=1))
        operation_pc = 3
    instructions.extend(
        (
            _instruction(operation_pc, "ADD", a=3, b=1, c=2),
            _instruction(
                operation_pc + 1,
                "SETTABLEKS",
                a=3,
                b=0,
                aux=1 if mismatched else 0,
            ),
        )
    )
    return build_ssa(instructions, code_size=operation_pc + 3)


def test_real_v6_uses_stage3_callframe_and_nested_stage4_rmw() -> None:
    backend = ReconstructedBackend()
    bytecode = base64.b64decode(_REAL_V6_TABLES)

    outputs = {
        backend.decompile(bytecode, dict(default_options()), "tables-v6.luac") for _ in range(3)
    }

    assert outputs == {
        'local value = {Name = "case-0", Stats = {Score = 0, Enabled = true}, 0, 0}\n'
        "value.Stats.Score += value[1]\n"
        "print(value.Name, value.Stats.Score, value[2])\n"
    }


def test_real_v6_callframe_tracks_callee_and_arguments_by_ssa_value() -> None:
    module = parse_bytecode(base64.b64decode(_REAL_V6_TABLES))
    proto_analysis = build_module_analysis(module).for_proto(module.main_proto)
    frame = plan_call_frames(proto_analysis.ssa).at(36)

    assert frame is not None
    assert frame.callee is not None and frame.callee.origin_pc == 27
    assert tuple(value.origin_pc if value is not None else None for value in frame.arguments) == (
        29,
        33,
        35,
    )
    assert frame.result_count == 0
    assert not frame.is_open_result


def test_field_rmw_requires_exact_structural_location() -> None:
    proto = _proto(
        constants=(
            LuauConstant("string", "Score", 3),
            LuauConstant("string", "Other", 3),
        )
    )
    program = _field_program()
    candidate = plan_read_modify_write(program, proto, build_scope_tree(proto)).at_write(3)

    assert candidate is not None
    assert candidate.location.kind == StorageKind.FIELD
    assert candidate.operator == "+"
    assert candidate.location.base == program.value_at_use(0, 0)

    mismatch = _field_program(mismatched=True)
    assert (
        plan_read_modify_write(
            mismatch,
            proto,
            build_scope_tree(proto),
        ).at_write(3)
        is None
    )


def test_field_rmw_rejects_unknown_call_barrier() -> None:
    proto = _proto(constants=(LuauConstant("string", "Score", 3),))
    program = _field_program(call_barrier=True)

    assert (
        plan_read_modify_write(
            program,
            proto,
            build_scope_tree(proto),
        ).at_write(4)
        is None
    )


def test_indexed_rmw_requires_same_base_and_key_ssa_versions() -> None:
    exact = build_ssa(
        (
            _instruction(0, "GETTABLE", a=2, b=0, c=1),
            _instruction(1, "ADD", a=3, b=2, c=4),
            _instruction(2, "SETTABLE", a=3, b=0, c=1),
        ),
        code_size=3,
    )
    proto = _proto(params=5)
    candidate = plan_read_modify_write(exact, proto, build_scope_tree(proto)).at_write(2)

    assert candidate is not None
    assert candidate.location.kind == StorageKind.INDEX
    assert candidate.location.base == exact.value_at_use(0, 0)
    assert candidate.location.key_value == exact.value_at_use(0, 1)

    redefined_key = build_ssa(
        (
            _instruction(0, "GETTABLE", a=2, b=0, c=1),
            _instruction(1, "MOVE", a=1, b=5),
            _instruction(2, "ADD", a=3, b=2, c=4),
            _instruction(3, "SETTABLE", a=3, b=0, c=1),
        ),
        code_size=4,
    )
    redefined_proto = _proto(params=6)
    assert (
        plan_read_modify_write(
            redefined_key,
            redefined_proto,
            build_scope_tree(redefined_proto),
        ).at_write(3)
        is None
    )


def test_rmw_rejects_old_value_with_an_additional_use() -> None:
    program = build_ssa(
        (
            _instruction(0, "GETTABLEKS", a=1, b=0, aux=0),
            _instruction(2, "MOVE", a=5, b=1),
            _instruction(3, "ADD", a=3, b=1, c=2),
            _instruction(4, "SETTABLEKS", a=3, b=0, aux=0),
        ),
        code_size=6,
    )
    proto = _proto(constants=(LuauConstant("string", "Score", 3),))

    assert (
        plan_read_modify_write(
            program,
            proto,
            build_scope_tree(proto),
        ).at_write(4)
        is None
    )


def test_callframe_preserves_fixed_and_open_multret_shapes() -> None:
    fixed = build_ssa(
        (
            _instruction(0, "GETGLOBAL", a=0, aux=0),
            _instruction(2, "CALL", a=0, b=3, c=2),
        ),
        code_size=3,
    )
    fixed_frame = plan_call_frames(fixed).at(2)
    assert fixed_frame is not None
    assert fixed_frame.argument_registers == (1, 2)
    assert fixed_frame.result_registers == (0,)

    opened = build_ssa(
        (
            _instruction(0, "CALL", a=2, b=1, c=0),
            _instruction(1, "CALL", a=0, b=0, c=0),
        ),
        code_size=2,
    )
    open_frame = plan_call_frames(opened).at(1)
    assert open_frame is not None
    assert open_frame.open_argument is not None
    assert open_frame.open_argument.value.origin_pc == 0
    assert open_frame.is_open_result


def test_callframe_owns_namecall_receiver_across_argument_setup() -> None:
    program = build_ssa(
        (
            _instruction(0, "NAMECALL", a=1, b=0, aux=0),
            _instruction(2, "MOVE", a=3, b=4),
            _instruction(3, "CALL", a=1, b=3, c=1),
        ),
        code_size=4,
    )
    frame = plan_call_frames(program).at(3)

    assert frame is not None
    assert frame.namecall_pc == 0
    assert frame.receiver == program.value_at_use(0, 0)
    assert frame.argument_registers == (3,)
    assert frame.arguments == (program.value_at_use(3, 3),)


def test_real_fixture_is_a_serialized_module_not_a_synthetic_opcode_stream() -> None:
    module = parse_bytecode(base64.b64decode(_REAL_V6_TABLES))

    assert isinstance(module, LuauBytecodeModule)
    assert module.version == 6
