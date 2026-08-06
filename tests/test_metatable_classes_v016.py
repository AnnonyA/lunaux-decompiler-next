from __future__ import annotations

from lunaux.backends.analysis import analyze_control_flow
from lunaux.backends.bytecode import (
    LocalInfo,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
)
from lunaux.backends.classes import recover_classes
from lunaux.backends.contextual_functions import (
    parameter_names_for_types,
    plan_contextual_functions,
)
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import decode_words, opcode_names
from lunaux.backends.ssa import build_ssa


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, a: int = 0, b: int = 0, c: int = 0) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, a: int = 0, d: int = 0) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(
    *,
    proto_id: int,
    code: tuple[int, ...],
    constants: tuple[LuauConstant, ...] = (),
    child_proto_ids: tuple[int, ...] = (),
    num_params: int = 0,
    debug_name: str | None = None,
    locals: tuple[LocalInfo, ...] = (),
) -> LuauProto:
    return LuauProto(
        proto_id=proto_id,
        max_stack_size=8,
        num_params=num_params,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=constants,
        child_proto_ids=child_proto_ids,
        line_defined=1,
        debug_name=debug_name,
        line_info=(),
        locals=locals,
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )


def _module(*protos: LuauProto) -> LuauBytecodeModule:
    return LuauBytecodeModule(
        version=9,
        types_version=3,
        strings=(),
        protos=tuple(protos),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def _class_fixture() -> tuple[LuauBytecodeModule, LuauProto]:
    constants = (
        LuauConstant("string", "__index", 3),
        LuauConstant("string", "new", 3),
        LuauConstant("string", "getX", 3),
        LuauConstant("string", "x", 3),
        LuauConstant("string", "__tostring", 3),
        LuauConstant("string", "Point", 3),
    )
    constructor = _proto(
        proto_id=1,
        code=(_abc("RETURN", 0, 1, 0),),
        num_params=1,
        debug_name="new_impl",
    )
    getter = _proto(
        proto_id=2,
        code=(
            _abc("GETTABLEKS", 1, 0, 0),
            3,
            _abc("RETURN", 1, 2, 0),
        ),
        constants=constants,
        num_params=1,
        debug_name="get_x_impl",
    )
    tostring = _proto(
        proto_id=3,
        code=(
            _ad("LOADK", 1, 5),
            _abc("RETURN", 1, 2, 0),
        ),
        constants=constants,
        num_params=1,
        debug_name="to_string_impl",
    )
    parent = _proto(
        proto_id=0,
        code=(
            _abc("NEWTABLE", 0, 0, 0),
            0,
            _abc("SETTABLEKS", 0, 0, 0),
            0,
            _ad("NEWCLOSURE", 1, 0),
            _abc("SETTABLEKS", 1, 0, 0),
            1,
            _ad("NEWCLOSURE", 1, 1),
            _abc("SETTABLEKS", 1, 0, 0),
            2,
            _ad("NEWCLOSURE", 1, 2),
            _abc("SETTABLEKS", 1, 0, 0),
            4,
            _abc("RETURN", 0, 2, 0),
        ),
        constants=constants,
        child_proto_ids=(1, 2, 3),
        locals=(LocalInfo("Point", 0, 14, 0),),
    )
    return _module(parent, constructor, getter, tostring), parent


def _analyze(module: LuauBytecodeModule, proto: LuauProto):
    instructions = tuple(decode_words(proto.code))
    analysis = analyze_control_flow(instructions, len(proto.code))
    program = build_ssa(instructions, len(proto.code), analysis=analysis)
    plan = recover_classes(module, proto, instructions, program)
    return instructions, program, plan


def test_recovers_metatable_class_members_and_context() -> None:
    module, parent = _class_fixture()
    instructions, program, plan = _analyze(module, parent)

    declaration = plan.at(0)
    assert declaration is not None
    assert declaration.source_kind == "metatable"
    assert declaration.name == "Point"
    assert declaration.properties == ("x",)
    assert [method.kind for method in declaration.methods] == [
        "constructor",
        "instance_method",
        "metamethod",
    ]
    assert plan.method_proto_ids == frozenset({1, 2, 3})
    assert {2, 4, 5, 7, 8, 10, 11}.issubset(plan.skipped_instruction_pcs)

    contexts = plan_contextual_functions(
        module,
        parent,
        instructions,
        program,
        plan,
    )
    constructor = contexts.for_proto(1)
    getter = contexts.for_proto(2)
    tostring = contexts.for_proto(3)
    assert constructor is not None and constructor.return_type == "Point"
    assert getter is not None and getter.parameter_names[0] == "self"
    assert getter.parameter_types[0] == "Point"
    assert tostring is not None and tostring.return_type == "string"


def test_decompiler_emits_one_contextual_class_declaration() -> None:
    module, _parent = _class_fixture()

    source = decompile_module(
        module,
        {
            "RecoverClasses": True,
            "RecoverMetatableClasses": True,
            "ContextualFunctions": True,
            "SmartVariableNames": True,
            "InferTypes": True,
        },
        "point.luau",
    )

    assert source.count("class Point") == 1
    assert "-- recovered from metatable __index pattern" in source
    assert "public x" in source
    assert "function new(arg1): Point" in source
    assert "function getX(self: Point)" in source
    assert "function __tostring(self: Point): string" in source
    assert "Point.__index = Point" not in source
    assert "local new_impl" not in source
    assert "return Point" in source


def test_dynamic_class_member_prevents_metatable_folding() -> None:
    constants = (
        LuauConstant("string", "__index", 3),
        LuauConstant("string", "method", 3),
    )
    child = _proto(
        proto_id=1,
        code=(_abc("RETURN", 0, 1, 0),),
        num_params=1,
    )
    parent = _proto(
        proto_id=0,
        code=(
            _abc("NEWTABLE", 0, 0, 0),
            0,
            _abc("SETTABLEKS", 0, 0, 0),
            0,
            _ad("NEWCLOSURE", 1, 0),
            _abc("SETTABLEKS", 1, 0, 0),
            1,
            _abc("SETTABLE", 1, 0, 2),
            _abc("RETURN", 0, 2, 0),
        ),
        constants=constants,
        child_proto_ids=(1,),
        num_params=3,
    )
    module = _module(parent, child)
    _instructions, _program, plan = _analyze(module, parent)

    assert plan.declarations == {}
    assert plan.method_proto_ids == frozenset()


def test_contextual_parameter_names_are_stable_and_unique() -> None:
    assert parameter_names_for_types(
        ("InputObject", "boolean", "number", "number", "Player")
    ) == ("input", "processed", "deltaTime", "deltaTime2", "player")
