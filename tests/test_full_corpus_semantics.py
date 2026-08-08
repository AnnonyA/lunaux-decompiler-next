from __future__ import annotations

from lunaux.backends.bytecode import LocalInfo, LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.compat_quality_dispatch import decompile_module
from lunaux.backends.full_corpus_semantics import install_full_corpus_semantics_fix


def _abc(opcode: int, a: int, b: int, c: int) -> int:
    return opcode | (a << 8) | (b << 16) | (c << 24)


def _ad(opcode: int, a: int, d: int) -> int:
    return opcode | (a << 8) | ((d & 0xFFFF) << 16)


def test_debug_local_name_starts_after_definition() -> None:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=2,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=(
            _ad(4, 0, 5),
            _abc(7, 1, 0, 0),
            0,
            _abc(21, 1, 2, 1),
            _abc(22, 0, 1, 0),
        ),
        constants=(LuauConstant("string", "print", 3),),
        child_proto_ids=(),
        line_defined=0,
        debug_name="main",
        line_info=(),
        locals=(LocalInfo("seed", 1, 5, 0),),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    module = LuauBytecodeModule(
        version=11,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )

    install_full_corpus_semantics_fix()
    source = decompile_module(module, {}, "debug-local")

    assert "local seed = 5" in source
    assert "print(seed)" in source
