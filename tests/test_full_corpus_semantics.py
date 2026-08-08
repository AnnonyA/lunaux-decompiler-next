from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from lunaux.backends.analysis import RegisterAccess
from lunaux.backends.bytecode import LocalInfo, LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.compat_quality_dispatch import decompile_module
from lunaux.backends.full_corpus_semantics import (
    _numeric_for_visible_register,
    _safe_inline_simple_aliases,
    install_full_corpus_semantics_fix,
)
from lunaux.backends.opcodes import DecodedInstruction


def _abc(opcode: int, a: int, b: int, c: int) -> int:
    return opcode | (a << 8) | (b << 16) | (c << 24)


def _ad(opcode: int, a: int, d: int) -> int:
    return opcode | (a << 8) | ((d & 0xFFFF) << 16)


def _instruction(pc: int, name: str, *, a: int = 0) -> DecodedInstruction:
    return DecodedInstruction(
        pc=pc,
        word=0,
        opcode=0,
        name=name,
        a=a,
        b=0,
        c=0,
        d=0,
        e=0,
    )


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
            _ad(4, 1, 5),
            _abc(7, 0, 0, 0),
            0,
            _abc(21, 0, 2, 1),
            _abc(22, 0, 1, 0),
        ),
        constants=(LuauConstant("string", "print", 3),),
        child_proto_ids=(),
        line_defined=0,
        debug_name="main",
        line_info=(),
        locals=(LocalInfo("seed", 1, 5, 1),),
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


def test_field_alias_inlining_preserves_property_tokens() -> None:
    lines = [
        "local Stats = record.Stats",
        "Stats.Score = Stats.Score + record[1]",
        'print(Stats.Score, record.Stats.Score, "Stats")',
    ]

    assert _safe_inline_simple_aliases(lines) == [
        "record.Stats.Score = record.Stats.Score + record[1]",
        'print(record.Stats.Score, record.Stats.Score, "Stats")',
    ]


def test_numeric_for_uses_internal_index_when_nominal_register_is_reused() -> None:
    prep = _instruction(3, "FORNPREP", a=0)
    body_reuse = _instruction(4, "LOADN", a=3)
    body_read = _instruction(5, "ADD", a=4)
    loop = _instruction(6, "FORNLOOP", a=0)
    lifter = cast(
        Any,
        SimpleNamespace(
            instructions=(prep, body_reuse, body_read, loop),
            analysis=SimpleNamespace(
                register_accesses={
                    3: RegisterAccess(frozenset({3}), frozenset({0, 1, 2})),
                    4: RegisterAccess(frozenset({3}), frozenset()),
                    5: RegisterAccess(frozenset({4}), frozenset({2, 3})),
                    6: RegisterAccess(frozenset({0, 1, 2, 3}), frozenset({0, 1, 2, 3})),
                }
            ),
        ),
    )

    assert _numeric_for_visible_register(lifter, prep, 7) == (2, 5)


def test_numeric_for_prefers_nominal_variable_when_its_incoming_value_is_used() -> None:
    prep = _instruction(3, "FORNPREP", a=0)
    body_read = _instruction(4, "ADD", a=4)
    body_redefine = _instruction(5, "LOADN", a=3)
    loop = _instruction(6, "FORNLOOP", a=0)
    lifter = cast(
        Any,
        SimpleNamespace(
            instructions=(prep, body_read, body_redefine, loop),
            analysis=SimpleNamespace(
                register_accesses={
                    3: RegisterAccess(frozenset({3}), frozenset({0, 1, 2})),
                    4: RegisterAccess(frozenset({4}), frozenset({3})),
                    5: RegisterAccess(frozenset({3}), frozenset()),
                    6: RegisterAccess(frozenset({0, 1, 2, 3}), frozenset({0, 1, 2, 3})),
                }
            ),
        ),
    )

    assert _numeric_for_visible_register(lifter, prep, 7) == (3, 4)
