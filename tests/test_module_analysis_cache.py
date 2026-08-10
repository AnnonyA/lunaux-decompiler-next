from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

import lunaux.backends.classes as classes_backend
import lunaux.backends.contextual_functions as contextual_backend
import lunaux.backends.lifter as lifter_backend
import lunaux.backends.module_analysis as module_analysis_backend
import lunaux.backends.roblox_recovery as roblox_backend
from lunaux.backends.bytecode import LuauBytecodeModule, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.module_analysis import SymbolAnalysisConfig, build_module_analysis
from lunaux.backends.opcodes import opcode_names
from lunaux.backends.symbols import build_symbol_recovery as original_symbol_recovery


def _abc(name: str, a: int = 0, b: int = 0, c: int = 0) -> int:
    return opcode_names().index(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, a: int = 0, d: int = 0) -> int:
    return opcode_names().index(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(
    proto_id: int,
    code: tuple[int, ...],
    *,
    children: tuple[int, ...] = (),
) -> LuauProto:
    return LuauProto(
        proto_id=proto_id,
        max_stack_size=2,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=(),
        child_proto_ids=children,
        line_defined=1,
        debug_name=None,
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )


@pytest.fixture
def module_with_child() -> LuauBytecodeModule:
    child = _proto(0, (_abc("RETURN", a=0, b=1),))
    main = _proto(
        1,
        (
            _ad("NEWCLOSURE", a=0, d=0),
            _abc("RETURN", a=0, b=1),
        ),
        children=(0,),
    )
    return LuauBytecodeModule(
        version=12,
        types_version=3,
        strings=(),
        protos=(child, main),
        main_proto_id=1,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def test_core_analysis_is_built_once_per_proto(
    monkeypatch: pytest.MonkeyPatch,
    module_with_child: LuauBytecodeModule,
) -> None:
    counts: Counter[str] = Counter()
    for name in ("decode_words", "analyze_control_flow", "build_ssa", "build_scope_tree"):
        original = getattr(module_analysis_backend, name)

        def wrapped(
            *args: object,
            __name: str = name,
            __original: object = original,
            **kwargs: object,
        ) -> object:
            counts[__name] += 1
            return __original(*args, **kwargs)  # type: ignore[operator]

        monkeypatch.setattr(module_analysis_backend, name, wrapped)

    def unexpected_legacy_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("decompile_module used a legacy analysis constructor")

    for backend in (classes_backend, contextual_backend, roblox_backend):
        monkeypatch.setattr(backend, "decode_words", unexpected_legacy_call)
        monkeypatch.setattr(backend, "build_ssa", unexpected_legacy_call)
    for name in ("decode_words", "analyze_control_flow", "build_ssa", "build_scope_tree"):
        monkeypatch.setattr(lifter_backend, name, unexpected_legacy_call)

    decompile_module(module_with_child, {}, "cache-test")
    expected = len(module_with_child.protos)
    assert counts == Counter(
        decode_words=expected,
        analyze_control_flow=expected,
        build_ssa=expected,
        build_scope_tree=expected,
    )


def test_symbol_recovery_is_keyed_by_proto_and_config(
    monkeypatch: pytest.MonkeyPatch,
    module_with_child: LuauBytecodeModule,
) -> None:
    analysis = build_module_analysis(module_with_child)
    proto = module_with_child.main_proto
    config = SymbolAnalysisConfig(True, True, True)
    calls = 0

    def wrapped(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original_symbol_recovery(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(module_analysis_backend, "build_symbol_recovery", wrapped)
    first = analysis.symbols_for(proto, config)
    second = analysis.symbols_for(proto, config)
    assert first is second
    assert calls == 1


def test_cache_compatibility_is_structural_not_object_identity(
    module_with_child: LuauBytecodeModule,
) -> None:
    analysis = build_module_analysis(module_with_child)
    structurally_equal = replace(module_with_child)
    analysis.require_module(structurally_equal)
    assert analysis.for_proto(structurally_equal.main_proto).ssa is not None
