from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from lunaux.backends.bytecode import (
    ClassShapeConstant,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
)
from lunaux.backends.opcodes import DecodedInstruction, decode_words
from lunaux.backends.ssa import SSAProgram, SSAValue, build_ssa

if TYPE_CHECKING:
    from lunaux.backends.module_analysis import ModuleAnalysis

ClassMethodKind = Literal[
    "constructor",
    "instance_method",
    "static_method",
    "metamethod",
]

ClassSourceKind = Literal["bytecode", "metatable"]

ClassValueDetails = tuple[
    DecodedInstruction,
    str,
    tuple[str, ...],
    tuple[str, ...],
]


@dataclass(frozen=True, slots=True)
class RecoveredClassMethod:
    name: str
    proto_id: int | None
    member_pc: int
    closure_pc: int | None
    kind: ClassMethodKind = "instance_method"
    parameter_names: tuple[tuple[int, str], ...] = ()
    parameter_types: tuple[tuple[int, str], ...] = ()
    return_type: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveredClass:
    pc: int
    register: int
    name: str
    superclass_register: int | None
    properties: tuple[str, ...]
    methods: tuple[RecoveredClassMethod, ...]
    source_kind: ClassSourceKind = "bytecode"
    superclass_name: str | None = None


@dataclass(frozen=True, slots=True)
class ClassRecoveryPlan:
    declarations: Mapping[int, RecoveredClass]
    skipped_instruction_pcs: frozenset[int]
    method_proto_ids: frozenset[int]

    @classmethod
    def empty(cls) -> ClassRecoveryPlan:
        return cls(
            MappingProxyType(dict[int, RecoveredClass]()),
            frozenset(),
            frozenset(),
        )

    def at(self, pc: int) -> RecoveredClass | None:
        return self.declarations.get(pc)


@dataclass(frozen=True, slots=True)
class _MetatableCandidate:
    instruction: DecodedInstruction
    value: SSAValue
    name: str


def _constant(proto: LuauProto, index: int) -> LuauConstant | None:
    return proto.constants[index] if 0 <= index < len(proto.constants) else None


def _constant_string(proto: LuauProto, index: int) -> str | None:
    constant = _constant(proto, index)
    if constant is None or constant.kind != "string":
        return None
    return constant.value if isinstance(constant.value, str) else None


def _shape(
    proto: LuauProto,
    instruction: DecodedInstruction,
) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    constant = _constant(proto, instruction.aux or 0)
    if (
        constant is None
        or constant.kind != "class_shape"
        or not isinstance(constant.value, ClassShapeConstant)
    ):
        return None
    value = constant.value
    class_name = _constant_string(proto, value.class_name_constant)
    if class_name is None:
        return None
    properties = tuple(
        _constant_string(proto, index) or f"property_{position + 1}"
        for position, index in enumerate(value.property_name_constants)
    )
    methods = tuple(
        _constant_string(proto, index) or f"method_{position + 1}"
        for position, index in enumerate(value.method_name_constants)
    )
    return class_name, properties, methods


def _canonical_value(
    instruction_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    value: SSAValue | None,
    seen: frozenset[SSAValue] = frozenset(),
) -> SSAValue | None:
    if value is None or value.origin_pc is None or value in seen:
        return value
    instruction = instruction_by_pc.get(value.origin_pc)
    if instruction is None or instruction.name != "MOVE":
        return value
    return _canonical_value(
        instruction_by_pc,
        program,
        program.value_at_use(instruction.pc, instruction.b),
        seen | frozenset({value}),
    )


def _closure_proto_id(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instruction_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    value: SSAValue | None,
) -> tuple[int | None, int | None, SSAValue | None]:
    canonical = _canonical_value(instruction_by_pc, program, value)
    if canonical is None or canonical.origin_pc is None:
        return None, None, canonical
    instruction = instruction_by_pc.get(canonical.origin_pc)
    if instruction is None:
        return None, canonical.origin_pc, canonical
    if instruction.name == "NEWCLOSURE":
        if 0 <= instruction.d < len(proto.child_proto_ids):
            child_id = proto.child_proto_ids[instruction.d]
            if 0 <= child_id < len(module.protos):
                return child_id, instruction.pc, canonical
    elif instruction.name == "DUPCLOSURE":
        constant = _constant(proto, instruction.d)
        if constant and constant.kind == "closure" and isinstance(constant.value, int):
            if 0 <= constant.value < len(module.protos):
                return constant.value, instruction.pc, canonical
    return None, instruction.pc, canonical


def _capture_pcs(
    module: LuauBytecodeModule,
    instructions: Sequence[DecodedInstruction],
    instruction_index: Mapping[int, int],
    closure_pc: int | None,
    child_id: int | None,
) -> frozenset[int]:
    if closure_pc is None or child_id is None:
        return frozenset()
    index = instruction_index.get(closure_pc)
    if index is None:
        return frozenset()
    child = module.protos[child_id]
    result: set[int] = set()
    for offset in range(child.num_upvalues):
        position = index + 1 + offset
        if position >= len(instructions):
            return frozenset()
        capture = instructions[position]
        if capture.name != "CAPTURE":
            return frozenset()
        result.add(capture.pc)
    return frozenset(result)


def _local_name(proto: LuauProto, register: int, pc: int) -> str | None:
    candidates = [
        item
        for item in proto.locals
        if item.register == register and item.start_pc <= pc < item.end_pc and item.name
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.start_pc).name


def _literal_string(
    proto: LuauProto,
    instruction_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    value: SSAValue | None,
    seen: frozenset[SSAValue] = frozenset(),
) -> str | None:
    canonical = _canonical_value(instruction_by_pc, program, value, seen)
    if canonical is None or canonical.origin_pc is None:
        return None
    instruction = instruction_by_pc.get(canonical.origin_pc)
    if instruction is None:
        return None
    if instruction.name == "LOADK":
        return _constant_string(proto, instruction.d)
    if instruction.name == "LOADKX":
        return _constant_string(proto, instruction.aux or 0)
    return None


def _table_write(
    proto: LuauProto,
    instruction_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    instruction: DecodedInstruction,
) -> tuple[SSAValue | None, str | None, SSAValue | None]:
    if instruction.name in {"SETTABLEKS", "SETUDATAKS"}:
        index = (
            instruction.userdata_constant_index
            if instruction.name == "SETUDATAKS"
            else instruction.aux
        )
        key = _constant_string(proto, index if index is not None else -1)
        target = program.value_at_use(instruction.pc, instruction.b)
        source = program.value_at_use(instruction.pc, instruction.a)
        return target, key, source
    if instruction.name == "SETTABLE":
        target = program.value_at_use(instruction.pc, instruction.b)
        key = _literal_string(
            proto,
            instruction_by_pc,
            program,
            program.value_at_use(instruction.pc, instruction.c),
        )
        source = program.value_at_use(instruction.pc, instruction.a)
        return target, key, source
    return None, None, None


def _first_parameter_is_receiver(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction] | None = None,
) -> bool:
    if proto.num_params == 0:
        return False
    resolved_instructions = instructions if instructions is not None else decode_words(proto.code)
    for instruction in resolved_instructions:
        if instruction.name in {"GETTABLE", "GETTABLEKS", "GETUDATAKS", "GETTABLEN"}:
            if instruction.b == 0:
                return True
        elif instruction.name in {"SETTABLE", "SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
            if instruction.b == 0:
                return True
        elif instruction.name in {"NAMECALL", "NAMECALLUDATA"} and instruction.b == 0:
            return True
    return False


def _method_kind(
    name: str,
    child: LuauProto,
    instructions: Sequence[DecodedInstruction] | None = None,
) -> ClassMethodKind:
    if name in {"new", "create"}:
        return "constructor"
    if name.startswith("__"):
        return "metamethod"
    if _first_parameter_is_receiver(child, instructions):
        return "instance_method"
    return "static_method"


def _method_context(
    class_name: str,
    method_name: str,
    kind: ClassMethodKind,
    child: LuauProto,
) -> tuple[
    tuple[tuple[int, str], ...],
    tuple[tuple[int, str], ...],
    str | None,
]:
    parameter_names: dict[int, str] = {}
    parameter_types: dict[int, str] = {}
    if kind in {"instance_method", "metamethod"} and child.num_params:
        parameter_names[0] = "self"
        parameter_types[0] = class_name
    metamethod_names: dict[str, tuple[str, ...]] = {
        "__add": ("self", "other"),
        "__call": ("self",),
        "__concat": ("self", "other"),
        "__div": ("self", "other"),
        "__eq": ("self", "other"),
        "__idiv": ("self", "other"),
        "__index": ("self", "key"),
        "__le": ("self", "other"),
        "__len": ("self",),
        "__lt": ("self", "other"),
        "__mod": ("self", "other"),
        "__mul": ("self", "other"),
        "__newindex": ("self", "key", "value"),
        "__pow": ("self", "other"),
        "__sub": ("self", "other"),
        "__tostring": ("self",),
        "__unm": ("self",),
    }
    for index, name in enumerate(metamethod_names.get(method_name, ())):
        if index < child.num_params:
            parameter_names.setdefault(index, name)
    return_types = {
        "__eq": "boolean",
        "__le": "boolean",
        "__len": "number",
        "__lt": "boolean",
        "__tostring": "string",
    }
    return_type = class_name if kind == "constructor" else return_types.get(method_name)
    return (
        tuple(sorted(parameter_names.items())),
        tuple(sorted(parameter_types.items())),
        return_type,
    )


def _properties_from_method(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction] | None = None,
) -> frozenset[str]:
    properties: set[str] = set()
    resolved_instructions = instructions if instructions is not None else decode_words(proto.code)
    for instruction in resolved_instructions:
        if instruction.name in {"GETTABLEKS", "SETTABLEKS"} and instruction.b == 0:
            key = _constant_string(proto, instruction.aux if instruction.aux is not None else -1)
            if key and not key.startswith("__"):
                properties.add(key)
        elif instruction.name in {"GETUDATAKS", "SETUDATAKS"} and instruction.b == 0:
            key = _constant_string(
                proto,
                instruction.userdata_constant_index
                if instruction.userdata_constant_index is not None
                else -1,
            )
            if key and not key.startswith("__"):
                properties.add(key)
    return frozenset(properties)


def _candidate_name(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    instruction_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    creation: DecodedInstruction,
    value: SSAValue,
    ordinal: int,
) -> str:
    debug_name = _local_name(proto, creation.a, creation.pc)
    if debug_name:
        return debug_name
    for instruction in instructions:
        if instruction.name == "SETGLOBAL":
            source = _canonical_value(
                instruction_by_pc,
                program,
                program.value_at_use(instruction.pc, instruction.a),
            )
            if source == value:
                name = _constant_string(
                    proto,
                    instruction.aux if instruction.aux is not None else -1,
                )
                if name:
                    return name
        if instruction.name in {"SETTABLEKS", "SETUDATAKS"}:
            source = _canonical_value(
                instruction_by_pc,
                program,
                program.value_at_use(instruction.pc, instruction.a),
            )
            if source == value:
                index = (
                    instruction.userdata_constant_index
                    if instruction.name == "SETUDATAKS"
                    else instruction.aux
                )
                name = _constant_string(proto, index if index is not None else -1)
                if name and name not in {"__index", "__newindex"}:
                    return name
    return f"Class{ordinal}"


def _superclass_name(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    instruction_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    class_value: SSAValue,
) -> str | None:
    previous_by_next = {item.pc + item.size: item for item in instructions}
    for instruction in instructions:
        if instruction.name not in {"CALL", "CALLFB"} or instruction.b < 3:
            continue
        function = _canonical_value(
            instruction_by_pc,
            program,
            program.value_at_use(instruction.pc, instruction.a),
        )
        if function is None or function.origin_pc is None:
            continue
        function_instruction = instruction_by_pc.get(function.origin_pc)
        if function_instruction is None:
            continue
        function_name: str | None = None
        if function_instruction.name == "GETGLOBAL":
            function_name = _constant_string(
                proto,
                function_instruction.aux if function_instruction.aux is not None else -1,
            )
        elif function_instruction.name in {"MOVE"}:
            continue
        if function_name != "setmetatable":
            previous = previous_by_next.get(instruction.pc)
            if previous is not None and previous.name in {"NAMECALL", "NAMECALLUDATA"}:
                continue
            continue
        first = _canonical_value(
            instruction_by_pc,
            program,
            program.value_at_use(instruction.pc, instruction.a + 1),
        )
        if first != class_value:
            continue
        register = instruction.a + 2
        return _local_name(proto, register, instruction.pc)
    return None


def _recover_bytecode_classes(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    instruction_by_pc: Mapping[int, DecodedInstruction],
    instruction_index: Mapping[int, int],
    module_analysis: ModuleAnalysis | None,
) -> tuple[dict[int, RecoveredClass], set[int], set[int]]:
    class_values: dict[SSAValue, ClassValueDetails] = {}
    for instruction in instructions:
        if instruction.name != "NEWCLASS":
            continue
        details = _shape(proto, instruction)
        value = program.value_defined_at(instruction.pc, instruction.a)
        if details is None or value is None:
            continue
        class_values[value] = (instruction, *details)

    methods_by_class: dict[SSAValue, list[RecoveredClassMethod]] = {
        value: [] for value in class_values
    }
    skipped: set[int] = set()
    method_proto_ids: set[int] = set()
    for instruction in instructions:
        if instruction.name != "NEWCLASSMEMBER":
            continue
        class_value = _canonical_value(
            instruction_by_pc,
            program,
            program.value_at_use(instruction.pc, instruction.a),
        )
        if class_value not in class_values:
            continue
        key_index = instruction.aux if instruction.aux is not None else -1
        key = _constant_string(proto, key_index) or f"member_{instruction.pc}"
        source_value = program.value_at_use(instruction.pc, instruction.c)
        child_id, closure_pc, canonical_source = _closure_proto_id(
            module,
            proto,
            instruction_by_pc,
            program,
            source_value,
        )
        kind: ClassMethodKind = "instance_method"
        parameter_names: tuple[tuple[int, str], ...] = ()
        parameter_types: tuple[tuple[int, str], ...] = ()
        return_type: str | None = None
        if child_id is not None:
            child = module.protos[child_id]
            child_instructions = (
                module_analysis.for_proto(child).instructions
                if module_analysis is not None
                else None
            )
            kind = _method_kind(key, child, child_instructions)
            class_name = class_values[class_value][1]
            parameter_names, parameter_types, return_type = _method_context(
                class_name,
                key,
                kind,
                child,
            )
        methods_by_class[class_value].append(
            RecoveredClassMethod(
                name=key,
                proto_id=child_id,
                member_pc=instruction.pc,
                closure_pc=closure_pc,
                kind=kind,
                parameter_names=parameter_names,
                parameter_types=parameter_types,
                return_type=return_type,
            )
        )
        skipped.add(instruction.pc)
        if child_id is not None:
            method_proto_ids.add(child_id)
        if (
            closure_pc is not None
            and canonical_source is not None
            and program.uses_of(canonical_source) == 1
        ):
            skipped.add(closure_pc)
            skipped.update(
                _capture_pcs(
                    module,
                    instructions,
                    instruction_index,
                    closure_pc,
                    child_id,
                )
            )

    declarations: dict[int, RecoveredClass] = {}
    for class_value, class_details in class_values.items():
        instruction, class_name, properties, shape_methods = class_details
        recovered_methods = methods_by_class[class_value]
        recovered_names = {method.name for method in recovered_methods}
        for method_name in shape_methods:
            if method_name not in recovered_names:
                recovered_methods.append(
                    RecoveredClassMethod(
                        name=method_name,
                        proto_id=None,
                        member_pc=instruction.pc,
                        closure_pc=None,
                    )
                )
        declarations[instruction.pc] = RecoveredClass(
            pc=instruction.pc,
            register=instruction.a,
            name=class_name,
            superclass_register=None if instruction.b == 0xFF else instruction.b,
            properties=properties,
            methods=tuple(recovered_methods),
            source_kind="bytecode",
        )
    return declarations, skipped, method_proto_ids


def _recover_metatable_classes(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    instruction_by_pc: Mapping[int, DecodedInstruction],
    instruction_index: Mapping[int, int],
    module_analysis: ModuleAnalysis | None,
) -> tuple[dict[int, RecoveredClass], set[int], set[int]]:
    candidates: list[_MetatableCandidate] = []
    for instruction in instructions:
        if instruction.name not in {"NEWTABLE", "DUPTABLE"}:
            continue
        value = program.value_defined_at(instruction.pc, instruction.a)
        if value is None:
            continue
        candidates.append(
            _MetatableCandidate(
                instruction=instruction,
                value=value,
                name=_candidate_name(
                    proto,
                    instructions,
                    instruction_by_pc,
                    program,
                    instruction,
                    value,
                    len(candidates) + 1,
                ),
            )
        )

    declarations: dict[int, RecoveredClass] = {}
    skipped: set[int] = set()
    method_proto_ids: set[int] = set()
    for candidate in candidates:
        self_index_pc: int | None = None
        recovered_methods: list[RecoveredClassMethod] = []
        properties: set[str] = set()
        local_skipped: set[int] = set()
        local_method_ids: set[int] = set()
        unsafe_dynamic_member = False

        for instruction in instructions:
            target, key, source = _table_write(
                proto,
                instruction_by_pc,
                program,
                instruction,
            )
            canonical_target = _canonical_value(instruction_by_pc, program, target)
            if canonical_target != candidate.value:
                continue
            if key is None:
                if instruction.name == "SETTABLE":
                    unsafe_dynamic_member = True
                continue
            canonical_source = _canonical_value(instruction_by_pc, program, source)
            if key == "__index" and canonical_source == candidate.value:
                self_index_pc = instruction.pc
                local_skipped.add(instruction.pc)
                continue
            child_id, closure_pc, closure_value = _closure_proto_id(
                module,
                proto,
                instruction_by_pc,
                program,
                source,
            )
            if child_id is None:
                continue
            child = module.protos[child_id]
            child_instructions = (
                module_analysis.for_proto(child).instructions
                if module_analysis is not None
                else None
            )
            kind = _method_kind(key, child, child_instructions)
            parameter_names, parameter_types, return_type = _method_context(
                candidate.name,
                key,
                kind,
                child,
            )
            recovered_methods.append(
                RecoveredClassMethod(
                    name=key,
                    proto_id=child_id,
                    member_pc=instruction.pc,
                    closure_pc=closure_pc,
                    kind=kind,
                    parameter_names=parameter_names,
                    parameter_types=parameter_types,
                    return_type=return_type,
                )
            )
            properties.update(_properties_from_method(child, child_instructions))
            local_skipped.add(instruction.pc)
            local_method_ids.add(child_id)
            if (
                closure_pc is not None
                and closure_value is not None
                and program.uses_of(closure_value) == 1
            ):
                local_skipped.add(closure_pc)
                local_skipped.update(
                    _capture_pcs(
                        module,
                        instructions,
                        instruction_index,
                        closure_pc,
                        child_id,
                    )
                )

        if (
            self_index_pc is None
            or not recovered_methods
            or unsafe_dynamic_member
            or not any(
                method.kind in {"constructor", "instance_method", "metamethod"}
                for method in recovered_methods
            )
        ):
            continue

        method_proto_ids.update(local_method_ids)
        declarations[candidate.instruction.pc] = RecoveredClass(
            pc=candidate.instruction.pc,
            register=candidate.instruction.a,
            name=candidate.name,
            superclass_register=None,
            superclass_name=_superclass_name(
                proto,
                instructions,
                instruction_by_pc,
                program,
                candidate.value,
            ),
            properties=tuple(sorted(properties)),
            methods=tuple(sorted(recovered_methods, key=lambda item: item.member_pc)),
            source_kind="metatable",
        )
        skipped.update(local_skipped)
    return declarations, skipped, method_proto_ids


def recover_classes(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    *,
    recover_metatable_classes: bool = True,
    module_analysis: ModuleAnalysis | None = None,
) -> ClassRecoveryPlan:
    if not instructions:
        return ClassRecoveryPlan.empty()
    instruction_by_pc = {instruction.pc: instruction for instruction in instructions}
    instruction_index = {instruction.pc: index for index, instruction in enumerate(instructions)}
    declarations, skipped, method_proto_ids = _recover_bytecode_classes(
        module,
        proto,
        instructions,
        program,
        instruction_by_pc,
        instruction_index,
        module_analysis,
    )
    if recover_metatable_classes:
        metatable_declarations, metatable_skipped, metatable_method_ids = (
            _recover_metatable_classes(
                module,
                proto,
                instructions,
                program,
                instruction_by_pc,
                instruction_index,
                module_analysis,
            )
        )
        for pc, declaration in metatable_declarations.items():
            declarations.setdefault(pc, declaration)
        skipped.update(metatable_skipped)
        method_proto_ids.update(metatable_method_ids)
    return ClassRecoveryPlan(
        declarations=MappingProxyType(declarations),
        skipped_instruction_pcs=frozenset(skipped),
        method_proto_ids=frozenset(method_proto_ids),
    )


def collect_class_method_proto_ids(
    module: LuauBytecodeModule,
    *,
    recover_metatable_classes: bool = True,
    module_analysis: ModuleAnalysis | None = None,
) -> frozenset[int]:
    if module_analysis is not None:
        module_analysis.require_module(module)
    result: set[int] = set()
    for proto in module.protos:
        if module_analysis is None:
            instructions = tuple(decode_words(proto.code))
            program = build_ssa(instructions, len(proto.code))
        else:
            analyzed = module_analysis.for_proto(proto)
            instructions = analyzed.instructions
            program = analyzed.ssa
        plan = recover_classes(
            module,
            proto,
            instructions,
            program,
            recover_metatable_classes=recover_metatable_classes,
            module_analysis=module_analysis,
        )
        result.update(plan.method_proto_ids)
    return frozenset(result)
