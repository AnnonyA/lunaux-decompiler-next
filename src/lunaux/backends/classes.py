from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from lunaux.backends.bytecode import (
    ClassShapeConstant,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
)
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAProgram, SSAValue

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


@dataclass(frozen=True, slots=True)
class RecoveredClass:
    pc: int
    register: int
    name: str
    superclass_register: int | None
    properties: tuple[str, ...]
    methods: tuple[RecoveredClassMethod, ...]


@dataclass(frozen=True, slots=True)
class ClassRecoveryPlan:
    declarations: Mapping[int, RecoveredClass]
    skipped_instruction_pcs: frozenset[int]
    method_proto_ids: frozenset[int]

    def at(self, pc: int) -> RecoveredClass | None:
        return self.declarations.get(pc)


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


def _closure_proto_id(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instruction_by_pc: Mapping[int, DecodedInstruction],
    value: SSAValue | None,
) -> tuple[int | None, int | None]:
    if value is None or value.origin_pc is None:
        return None, None
    instruction = instruction_by_pc.get(value.origin_pc)
    if instruction is None:
        return None, value.origin_pc
    if instruction.name == "NEWCLOSURE":
        if 0 <= instruction.d < len(proto.child_proto_ids):
            child_id = proto.child_proto_ids[instruction.d]
            if 0 <= child_id < len(module.protos):
                return child_id, instruction.pc
    elif instruction.name == "DUPCLOSURE":
        constant = _constant(proto, instruction.d)
        if constant and constant.kind == "closure" and isinstance(constant.value, int):
            if 0 <= constant.value < len(module.protos):
                return constant.value, instruction.pc
    return None, instruction.pc


def recover_classes(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
) -> ClassRecoveryPlan:
    instruction_by_pc = {instruction.pc: instruction for instruction in instructions}
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
        class_value = program.value_at_use(instruction.pc, instruction.a)
        if class_value not in class_values:
            continue
        key_index = instruction.aux if instruction.aux is not None else -1
        key = _constant_string(proto, key_index) or f"member_{instruction.pc}"
        source_value = program.value_at_use(instruction.pc, instruction.c)
        child_id, closure_pc = _closure_proto_id(
            module,
            proto,
            instruction_by_pc,
            source_value,
        )
        methods_by_class[class_value].append(
            RecoveredClassMethod(
                name=key,
                proto_id=child_id,
                member_pc=instruction.pc,
                closure_pc=closure_pc,
            )
        )
        skipped.add(instruction.pc)
        if child_id is not None:
            method_proto_ids.add(child_id)
        if (
            closure_pc is not None
            and source_value is not None
            and program.uses_of(source_value) == 1
        ):
            skipped.add(closure_pc)

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
        )

    return ClassRecoveryPlan(
        declarations=MappingProxyType(declarations),
        skipped_instruction_pcs=frozenset(skipped),
        method_proto_ids=frozenset(method_proto_ids),
    )
