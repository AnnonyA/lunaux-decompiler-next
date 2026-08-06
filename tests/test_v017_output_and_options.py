from __future__ import annotations

from lunaux import __version__
from lunaux.backends import (
    AdvancedLoopPlan,
    StateMachinePlan,
    analyze_advanced_loops,
    recover_state_machines,
)
from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import opcode_names
from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.models import DecompileOptions


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, *, a: int = 0, d: int = 0) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(
    code: tuple[int, ...],
    constants: tuple[LuauConstant, ...] = (),
    *,
    params: int = 0,
    upvalues: int = 0,
    stack: int = 8,
) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=stack,
        num_params=params,
        num_upvalues=upvalues,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
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


def _module(proto: LuauProto) -> LuauBytecodeModule:
    return LuauBytecodeModule(
        version=13,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def test_lifter_emits_advanced_while_break_and_continue() -> None:
    proto = _proto(
        (
            _ad("JUMPIF", a=0, d=5),
            _ad("LOADN", a=2, d=1),
            _ad("JUMPIF", a=1, d=3),
            _ad("JUMPIF", a=2, d=-4),
            _ad("LOADN", a=3, d=5),
            _ad("JUMPBACK", d=-6),
            _abc("RETURN", a=0, b=1),
        ),
        params=2,
        stack=4,
    )

    output = decompile_module(_module(proto), {}, "advanced-while.luau")

    assert "while " in output
    assert "break" in output
    assert "continue" in output
    assert "jumpback to" not in output
    assert "jump to L" not in output


def test_lifter_emits_unflattened_cycle_in_state_order() -> None:
    constants = (
        LuauConstant("number", 0.0, 2),
        LuauConstant("number", 1.0, 2),
    )
    proto = _proto(
        (
            _ad("LOADK", a=0, d=0),
            _ad("JUMP", d=0),
            _ad("JUMPXEQKN", a=0, d=4),
            0,
            _ad("JUMPXEQKN", a=0, d=6),
            1,
            _ad("JUMPBACK", d=-5),
            _ad("LOADN", a=1, d=10),
            _abc("SETUPVAL", a=1, b=0),
            _ad("LOADK", a=0, d=1),
            _ad("JUMPBACK", d=-9),
            _ad("LOADN", a=2, d=20),
            _abc("SETUPVAL", a=2, b=0),
            _ad("LOADK", a=0, d=0),
            _ad("JUMPBACK", d=-13),
        ),
        constants,
        upvalues=1,
        stack=3,
    )

    output = decompile_module(_module(proto), {}, "flattened-cycle.luau")

    assert "-- unflattened state machine R0; initial=0" in output
    assert "while true do" in output
    first = output.index("upvalue_0 = 10")
    second = output.index("upvalue_0 = 20")
    assert first < second
    assert "jumpback to" not in output
    assert "JUMPXEQKN" not in output


def test_v017_options_versions_and_public_exports() -> None:
    options = DecompileOptions.model_validate(
        {
            "AdvancedLoops": False,
            "UnflattenStateMachines": False,
        }
    )

    assert options.advanced_loops is False
    assert options.unflatten_state_machines is False
    assert options.to_backend_dict()["AdvancedLoops"] is False
    assert options.to_backend_dict()["UnflattenStateMachines"] is False
    assert __version__ == "0.17.0"
    assert ReconstructedBackend().version == "0.17.0"
    assert AdvancedLoopPlan.empty().regions == ()
    assert StateMachinePlan.empty().regions == ()
    assert callable(analyze_advanced_loops)
    assert callable(recover_state_machines)
