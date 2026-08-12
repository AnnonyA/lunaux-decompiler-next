from __future__ import annotations

from lunaux.backends.analysis import analyze_control_flow
from lunaux.backends.bytecode import (
    ClassShapeConstant,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
    TypedLocalInfo,
)
from lunaux.backends.classes import recover_classes
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import decode_words, opcode_names
from lunaux.backends.ssa import build_ssa
from lunaux.backends.symbols import build_symbol_recovery


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, a: int, b: int, c: int) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, a: int, d: int) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(
    *,
    proto_id: int,
    code: tuple[int, ...],
    constants: tuple[LuauConstant, ...] = (),
    child_proto_ids: tuple[int, ...] = (),
    num_params: int = 0,
    typed_locals: tuple[TypedLocalInfo, ...] = (),
    debug_name: str | None = None,
) -> LuauProto:
    return LuauProto(
        proto_id=proto_id,
        max_stack_size=16,
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
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
        typed_locals=typed_locals,
    )


def _module(*protos: LuauProto, main: int = 0, version: int = 9) -> LuauBytecodeModule:
    return LuauBytecodeModule(
        version=version,
        types_version=3,
        strings=(),
        protos=tuple(protos),
        main_proto_id=main,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def _analyze(module: LuauBytecodeModule, proto: LuauProto):
    instructions = tuple(decode_words(proto.code))
    analysis = analyze_control_flow(instructions, len(proto.code))
    ssa = build_ssa(instructions, len(proto.code), analysis=analysis)
    recovery = build_symbol_recovery(module, proto, instructions, ssa)
    return instructions, ssa, recovery


def test_semantic_naming_ignores_unreachable_trailing_return() -> None:
    proto = _proto(
        proto_id=0,
        code=(
            _ad("JUMPBACK", 0, -1),
            _abc("RETURN", 0, 1, 0),
        ),
    )
    module = _module(proto)
    instructions, ssa, _ = _analyze(module, proto)

    assert [instruction.pc for instruction in instructions] == [0, 1]
    assert ssa.instruction_at(0) is not None
    assert ssa.instruction_at(1) is None
    assert decompile_module(module, {}, "unreachable-return.luac")


def test_getservice_recovers_service_name_and_type() -> None:
    constants = (
        LuauConstant("string", "game", 3),
        LuauConstant("string", "GetService", 3),
        LuauConstant("string", "Players", 3),
    )
    code = (
        _abc("GETGLOBAL", 0, 0, 0),
        0,
        _abc("NAMECALL", 1, 0, 0),
        1,
        _ad("LOADK", 3, 2),
        _abc("CALL", 1, 3, 2),
        _abc("RETURN", 1, 2, 0),
    )
    proto = _proto(proto_id=0, code=code, constants=constants)
    module = _module(proto)

    _, _, recovery = _analyze(module, proto)
    call_pc = 5

    assert recovery.name_at_definition(call_pc, 1) == "Players"
    assert recovery.type_at_definition(call_pc, 1) == "Players"
    assert recovery.return_type == "Players"


def test_parameter_names_use_numbered_native_type_families() -> None:
    code = (_abc("RETURN", 0, 2, 0),)
    typed = tuple(
        TypedLocalInfo(type_tag=tag, register=register, start_pc=0, end_pc=1)
        for register, tag in enumerate((2, 1, 3, 15, 8, 9))
    )
    proto = _proto(
        proto_id=0,
        code=code,
        num_params=6,
        typed_locals=typed,
    )
    module = _module(proto)

    _, _, recovery = _analyze(module, proto)

    assert recovery.entry_names == {
        0: "num1",
        1: "bool1",
        2: "str1",
        3: "arg1",
        4: "vec1",
        5: "buf1",
    }
    assert recovery.return_type == "number"


def test_class_shape_and_method_are_recovered_as_standard_luau() -> None:
    constants = (
        LuauConstant("string", "Point", 3),
        LuauConstant("string", "x", 3),
        LuauConstant("string", "length", 3),
        LuauConstant(
            "class_shape",
            ClassShapeConstant(
                class_name_constant=0,
                property_name_constants=(1,),
                method_name_constants=(2,),
            ),
            10,
        ),
    )
    child = _proto(
        proto_id=1,
        code=(_abc("RETURN", 0, 1, 0),),
        num_params=1,
        debug_name="length_impl",
    )
    parent = _proto(
        proto_id=0,
        code=(
            _ad("NEWCLOSURE", 1, 0),
            _abc("NEWCLASS", 0, 0xFF, 0),
            3,
            _abc("NEWCLASSMEMBER", 0, 0, 1),
            2,
            _abc("RETURN", 0, 1, 0),
        ),
        constants=constants,
        child_proto_ids=(1,),
    )
    module = _module(parent, child, version=100)
    instructions = tuple(decode_words(parent.code))
    analysis = analyze_control_flow(instructions, len(parent.code))
    ssa = build_ssa(instructions, len(parent.code), analysis=analysis)

    plan = recover_classes(module, parent, instructions, ssa)

    declaration = plan.at(1)
    assert declaration is not None
    assert declaration.name == "Point"
    assert declaration.properties == ("x",)
    assert declaration.methods[0].name == "length"
    assert declaration.methods[0].proto_id == 1

    source = decompile_module(
        module,
        {
            "SmartVariableNames": True,
            "InferTypes": True,
            "RecoverClasses": True,
        },
        "classes.luau",
    )
    assert "local Point = {}" in source
    assert "class Point" not in source
    assert "public x" not in source
    assert "function Point.length(arg1)" in source
