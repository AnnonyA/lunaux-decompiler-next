from __future__ import annotations

from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.compat_quality_dispatch import decompile_module
from lunaux.backends.multret_open_args_fix import install_open_argument_fix


def _abc(opcode: int, a: int, b: int, c: int) -> int:
    return opcode | (a << 8) | (b << 16) | (c << 24)


def _ad(opcode: int, a: int, d: int) -> int:
    return opcode | (a << 8) | ((d & 0xFFFF) << 16)


def test_legacy_open_call_keeps_dominating_fixed_argument() -> None:
    """CALL B=0 must keep fixed prefix slots across an optimized block split."""

    # Equivalent core shape to optimized v6 `select("#", ...)`:
    #   GETGLOBAL R0 select
    #   LOADK     R3 "#"
    #   MOVE      R1 R3
    #   JUMP      -> next block
    #   GETVARARGS R2 0
    #   CALL      R0 0 2
    # The dynamic CALL use edge does not enumerate R1, so recovery has to follow the
    # physical slot back through MOVE to the dominating scalar definition.
    proto = LuauProto(
        proto_id=0,
        max_stack_size=4,
        num_params=0,
        num_upvalues=0,
        is_vararg=True,
        flags=0,
        type_info=b"",
        code=(
            _abc(7, 0, 0, 0),
            0,
            _ad(5, 3, 1),
            _abc(6, 1, 3, 0),
            _ad(23, 0, 0),
            _abc(63, 2, 0, 0),
            _abc(21, 0, 0, 2),
            _abc(22, 0, 2, 0),
        ),
        constants=(
            LuauConstant("string", "select", 3),
            LuauConstant("string", "#", 3),
        ),
        child_proto_ids=(),
        line_defined=0,
        debug_name="main",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    module = LuauBytecodeModule(
        version=6,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )

    install_open_argument_fix()
    source = decompile_module(module, {}, "open-args")

    assert '("#", ...)' in source
