from __future__ import annotations

import base64

from lunaux.backends.bytecode import (
    LocalInfo,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
    parse_bytecode,
)
from lunaux.backends.module_analysis import build_module_analysis
from lunaux.backends.opcodes import opcode_names
from lunaux.backends.proto_emission import build_proto_emission_plan
from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.backends.semantic_naming import build_semantic_name_plan
from lunaux.benchmark_engine import default_options

_REAL_V6_RECURSION = (
    "BgMBBXByaW50AAIEAQEAAAAKBAEBAB8AAwABAAAABAEBABYBAgAJAgAAKAMAABUCAgIj"
    "AQACFgECAAECAAAAAAAA8D8AAQAAAAQAAAECAApBAAAAQAAAAEYAAAAMAQIAAAAQQAYC"
    "AAAEAwIAFQICABUBAAEWAAEAAwYAAwEEAAAQQAEAAQAAAAE="
)
_REAL_V11_METHOD = (
    "CwMDBXZhbHVlA2FkZAVwcmludAACAwIAAAgACA8CAMwAAAAAIQICARACAMwAAAAADwIA"
    "zAAAAAAWAgIAAQMBAAIAAAAABgAAAQIAEUEAAAA2AAIAQAEDABABAL8EAAAADAEGAAAA"
    "UEAEBAIAFAIAvwQAAAAVAgMCBAUFABQDAL8EAAAAFQMDABUBAAEWAAEABwMBAgAAAAAA"
    "AAAACAEAAQAAAAYAAwIDAwQAAFBAAQABAAAAAAE="
)


def _abc(name: str, a: int = 0, b: int = 0, c: int = 0) -> int:
    return opcode_names().index(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, a: int = 0, d: int = 0) -> int:
    return opcode_names().index(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(
    proto_id: int,
    code: tuple[int, ...],
    *,
    params: int = 0,
    upvalues: int = 0,
    constants: tuple[LuauConstant, ...] = (),
    children: tuple[int, ...] = (),
    locals_: tuple[LocalInfo, ...] = (),
    debug_name: str | None = None,
) -> LuauProto:
    return LuauProto(
        proto_id=proto_id,
        max_stack_size=8,
        num_params=params,
        num_upvalues=upvalues,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=constants,
        child_proto_ids=children,
        line_defined=0,
        debug_name=debug_name,
        line_info=(),
        locals=locals_,
        upvalue_names=tuple(None for _ in range(upvalues)),
        feedback_pcs=(),
        cost=None,
    )


def _module(*protos: LuauProto, main: int) -> LuauBytecodeModule:
    return LuauBytecodeModule(
        version=11,
        types_version=3,
        strings=(),
        protos=protos,
        main_proto_id=main,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def _plan(module: LuauBytecodeModule):
    return build_proto_emission_plan(
        module,
        build_module_analysis(module),
        {},
        inline_callbacks=True,
    )


def test_real_recursion_is_owned_once_and_emitted_as_local_function() -> None:
    module = parse_bytecode(base64.b64decode(_REAL_V6_RECURSION))
    plan = _plan(module)
    instance = plan.for_parent(module.main_proto_id).at_creation(1)

    assert instance is not None
    assert instance.closure_value.name == "R0.1"
    assert instance.recursive
    assert instance.emission_kind == "local-function"
    assert instance.child_proto_id not in plan.preemit_proto_ids

    output = ReconstructedBackend().decompile(
        base64.b64decode(_REAL_V6_RECURSION),
        dict(default_options()),
        "recursion.luac",
    )
    assert output.count("local function") == 1
    assert "local function recursiveFunction(value)" in output
    assert "recursiveFunction(value - 1)" in output


def test_real_method_requires_receiver_and_matching_namecall_evidence() -> None:
    module = parse_bytecode(base64.b64decode(_REAL_V11_METHOD))
    plan = _plan(module)
    instance = plan.for_parent(module.main_proto_id).at_creation(2)

    assert instance is not None
    assert instance.emission_kind == "method-declaration"
    assert instance.method_name == "add"
    assert instance.terminal_pc == 3

    output = ReconstructedBackend().decompile(
        base64.b64decode(_REAL_V11_METHOD),
        dict(default_options()),
        "method.luac",
    )
    assert "local data = {value = 0}" in output
    assert "function data:add(amount)" in output
    assert "add = function" not in output


def test_semantic_parameter_names_use_exact_function_role_and_ssa() -> None:
    module = parse_bytecode(base64.b64decode(_REAL_V11_METHOD))
    analysis = build_module_analysis(module)
    child = module.protos[0]
    facts = analysis.for_proto(child)
    plan = build_semantic_name_plan(
        child,
        facts.instructions,
        facts.ssa,
        facts.scope_tree,
        None,
        parameter_overrides={0: "self", 1: "arg2"},
        function_role="method",
    )

    assert plan.entry_names == {0: "self", 1: "amount"}


def test_semantic_parameter_conflicts_are_deterministic_and_scope_safe() -> None:
    module = parse_bytecode(base64.b64decode(_REAL_V11_METHOD))
    analysis = build_module_analysis(module)
    child = module.protos[0]
    facts = analysis.for_proto(child)
    plan = build_semantic_name_plan(
        child,
        facts.instructions,
        facts.ssa,
        facts.scope_tree,
        None,
        parameter_overrides={0: "self", 1: "self"},
        function_role="method",
    )

    assert plan.entry_names == {0: "self", 1: "self2"}


def test_multi_use_closure_remains_shared_and_is_not_duplicated() -> None:
    child = _proto(0, (_abc("RETURN", b=1),))
    parent = _proto(
        1,
        (
            _ad("DUPCLOSURE", a=0, d=0),
            _abc("MOVE", a=1, b=0),
            _abc("MOVE", a=2, b=0),
            _abc("RETURN", b=1),
        ),
        constants=(LuauConstant("closure", 0, 6),),
    )
    plan = _plan(_module(child, parent, main=1))
    instance = plan.for_parent(1).at_creation(0)

    assert instance is not None
    assert instance.emission_kind == "shared-proto"
    assert "not-single-use" in instance.rejection_reasons
    assert 0 in plan.preemit_proto_ids


def test_single_use_closure_argument_is_owned_by_exact_call_frame() -> None:
    child = _proto(0, (_abc("RETURN", b=1),))
    parent = _proto(
        1,
        (
            _ad("DUPCLOSURE", a=1, d=0),
            _abc("CALL", a=0, b=2, c=1),
            _abc("RETURN", b=1),
        ),
        params=1,
        constants=(LuauConstant("closure", 0, 6),),
    )
    plan = _plan(_module(child, parent, main=1))
    instance = plan.for_parent(1).at_creation(0)

    assert instance is not None
    assert instance.terminal_pc == 1
    assert instance.terminal_register == 1
    assert instance.emission_kind == "inline-expression"
    assert instance.child_proto_id in plan.owned_proto_ids
    assert instance.child_proto_id not in plan.preemit_proto_ids


def test_same_proto_instantiated_twice_has_two_distinct_ssa_owners() -> None:
    child = _proto(0, (_abc("RETURN", b=1),))
    parent = _proto(
        1,
        (
            _ad("DUPCLOSURE", a=0, d=0),
            _abc("SETGLOBAL", a=0),
            1,
            _ad("DUPCLOSURE", a=0, d=0),
            _abc("SETGLOBAL", a=0),
            2,
            _abc("RETURN", b=1),
        ),
        constants=(
            LuauConstant("closure", 0, 6),
            LuauConstant("string", "first", 3),
            LuauConstant("string", "second", 3),
        ),
    )
    instances = _plan(_module(child, parent, main=1)).for_parent(1).instances

    assert len(instances) == 2
    assert instances[0].closure_value != instances[1].closure_value
    assert instances[0].creation_pc != instances[1].creation_pc


def test_debug_name_self_does_not_cause_method_or_recursion_inference() -> None:
    child = _proto(
        0,
        (_abc("RETURN", b=1),),
        params=1,
        locals_=(LocalInfo("self", 0, 1, 0),),
        debug_name="methodLike",
    )
    parent = _proto(
        1,
        (
            _ad("DUPCLOSURE", a=1, d=0),
            _abc("RETURN", a=1, b=2),
        ),
        constants=(LuauConstant("closure", 0, 6),),
    )
    instance = _plan(_module(child, parent, main=1)).for_parent(1).at_creation(0)

    assert instance is not None
    assert not instance.recursive
    assert instance.emission_kind == "inline-expression"


def test_mutual_recursion_uses_one_predeclared_scc() -> None:
    even_child = _proto(0, (_abc("RETURN", b=1),), upvalues=1)
    odd_child = _proto(1, (_abc("RETURN", b=1),), upvalues=1)
    parent = _proto(
        2,
        (
            _ad("DUPCLOSURE", a=0, d=0),
            _abc("CAPTURE", a=1, b=1),
            _ad("DUPCLOSURE", a=1, d=1),
            _abc("CAPTURE", a=1, b=0),
            _abc("RETURN", b=1),
        ),
        constants=(
            LuauConstant("closure", 0, 6),
            LuauConstant("closure", 1, 6),
        ),
        locals_=(
            LocalInfo("even", 0, 5, 0),
            LocalInfo("odd", 0, 5, 1),
        ),
    )
    instances = _plan(_module(even_child, odd_child, parent, main=2)).for_parent(2).instances

    assert len(instances) == 2
    assert {instance.emission_kind for instance in instances} == {
        "predeclared-assignment"
    }
    assert {instance.recursion_group for instance in instances} == {(0, 2)}


def test_physical_register_reuse_keeps_proto_instances_separate() -> None:
    first = _proto(0, (_abc("RETURN", b=1),))
    second = _proto(1, (_abc("RETURN", b=1),))
    parent = _proto(
        2,
        (
            _ad("DUPCLOSURE", a=0, d=0),
            _abc("SETGLOBAL", a=0),
            2,
            _ad("DUPCLOSURE", a=0, d=1),
            _abc("SETGLOBAL", a=0),
            3,
            _abc("RETURN", b=1),
        ),
        constants=(
            LuauConstant("closure", 0, 6),
            LuauConstant("closure", 1, 6),
            LuauConstant("string", "first", 3),
            LuauConstant("string", "second", 3),
        ),
    )
    instances = _plan(_module(first, second, parent, main=2)).for_parent(2).instances

    assert tuple(instance.child_proto_id for instance in instances) == (0, 1)
    assert instances[0].closure_value != instances[1].closure_value
