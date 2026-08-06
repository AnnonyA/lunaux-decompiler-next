from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from lunaux.backends.bytecode import LuauBytecodeModule, LuauProto
from lunaux.backends.classes import ClassRecoveryPlan, RecoveredClassMethod
from lunaux.backends.opcodes import DecodedInstruction, decode_words
from lunaux.backends.roblox_recovery import InlineCallbackPlan, plan_inline_callbacks
from lunaux.backends.ssa import SSAProgram, SSAValue, build_ssa

FunctionKind = Literal[
    "constructor",
    "instance_method",
    "static_method",
    "metamethod",
    "callback",
    "field",
    "global",
    "returned",
]


@dataclass(frozen=True, slots=True)
class FunctionContext:
    proto_id: int
    name: str
    kind: FunctionKind
    owner_name: str | None
    parameter_names: Mapping[int, str]
    parameter_types: Mapping[int, str]
    return_type: str | None
    confidence: int
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FunctionContextPlan:
    by_proto: Mapping[int, FunctionContext]
    by_value: Mapping[SSAValue, FunctionContext]

    @classmethod
    def empty(cls) -> FunctionContextPlan:
        return cls(
            MappingProxyType(dict[int, FunctionContext]()),
            MappingProxyType(dict[SSAValue, FunctionContext]()),
        )

    def for_proto(self, proto_id: int) -> FunctionContext | None:
        return self.by_proto.get(proto_id)

    def for_value(self, value: SSAValue | None) -> FunctionContext | None:
        return self.by_value.get(value) if value is not None else None


_TYPE_PARAMETER_NAMES: dict[str, str] = {
    "BasePart": "otherPart",
    "boolean": "processed",
    "CFrame": "cframe",
    "Enum.ContextActionResult": "result",
    "Enum.HumanoidStateType": "state",
    "Enum.UserInputState": "inputState",
    "Enum.UserInputType": "inputType",
    "InputObject": "input",
    "Instance": "instance",
    "Model": "model",
    "number": "deltaTime",
    "Player": "player",
    "string": "name",
    "Vector2": "position",
    "Vector3": "position",
}

_METAMETHOD_PARAMETER_NAMES: dict[str, tuple[str, ...]] = {
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

_METAMETHOD_RETURN_TYPES: dict[str, str] = {
    "__eq": "boolean",
    "__le": "boolean",
    "__len": "number",
    "__lt": "boolean",
    "__tostring": "string",
}


def parameter_names_for_types(types: Sequence[str]) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    result: list[str] = []
    for index, type_name in enumerate(types):
        normalized = type_name.removesuffix("?")
        base = _TYPE_PARAMETER_NAMES.get(normalized, f"arg{index + 1}")
        count = counts.get(base, 0) + 1
        counts[base] = count
        result.append(base if count == 1 else f"{base}{count}")
    return tuple(result)


def _context_from_class_method(
    class_name: str,
    method: RecoveredClassMethod,
) -> FunctionContext | None:
    if method.proto_id is None:
        return None
    parameter_names = dict(method.parameter_names)
    parameter_types = dict(method.parameter_types)
    if method.kind in {"instance_method", "metamethod"}:
        parameter_names.setdefault(0, "self")
        parameter_types.setdefault(0, class_name)
    if method.kind == "metamethod":
        for index, name in enumerate(_METAMETHOD_PARAMETER_NAMES.get(method.name, ())):
            parameter_names.setdefault(index, name)
    return_type = method.return_type
    if return_type is None and method.kind == "constructor":
        return_type = class_name
    if return_type is None and method.kind == "metamethod":
        return_type = _METAMETHOD_RETURN_TYPES.get(method.name)
    return FunctionContext(
        proto_id=method.proto_id,
        name=method.name,
        kind=method.kind,
        owner_name=class_name,
        parameter_names=MappingProxyType(parameter_names),
        parameter_types=MappingProxyType(parameter_types),
        return_type=return_type,
        confidence=96,
        evidence=("metatable/class member assignment",),
    )


def _constant_string(proto: LuauProto, index: int) -> str | None:
    if not 0 <= index < len(proto.constants):
        return None
    constant = proto.constants[index]
    if constant.kind != "string" or not isinstance(constant.value, str):
        return None
    return constant.value


def _canonical_value(
    instructions_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    value: SSAValue | None,
    seen: frozenset[SSAValue] = frozenset(),
) -> SSAValue | None:
    if value is None or value.origin_pc is None or value in seen:
        return value
    instruction = instructions_by_pc.get(value.origin_pc)
    if instruction is None or instruction.name != "MOVE":
        return value
    return _canonical_value(
        instructions_by_pc,
        program,
        program.value_at_use(instruction.pc, instruction.b),
        seen | frozenset({value}),
    )


def _closure_details(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    value: SSAValue | None,
) -> tuple[int, SSAValue] | None:
    canonical = _canonical_value(instructions_by_pc, program, value)
    if canonical is None or canonical.origin_pc is None:
        return None
    instruction = instructions_by_pc.get(canonical.origin_pc)
    if instruction is None:
        return None
    child_id: int | None = None
    if instruction.name == "NEWCLOSURE" and 0 <= instruction.d < len(proto.child_proto_ids):
        child_id = proto.child_proto_ids[instruction.d]
    elif instruction.name == "DUPCLOSURE" and 0 <= instruction.d < len(proto.constants):
        constant = proto.constants[instruction.d]
        if constant.kind == "closure" and isinstance(constant.value, int):
            child_id = constant.value
    if child_id is None or not 0 <= child_id < len(module.protos):
        return None
    return child_id, canonical


def _local_name(proto: LuauProto, register: int, pc: int) -> str | None:
    candidates = [
        item
        for item in proto.locals
        if item.register == register and item.start_pc <= pc < item.end_pc and item.name
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.start_pc).name


def _first_parameter_is_receiver(proto: LuauProto) -> bool:
    if proto.num_params == 0:
        return False
    for instruction in decode_words(proto.code):
        if instruction.name in {"GETTABLE", "GETTABLEKS", "GETUDATAKS", "GETTABLEN"}:
            if instruction.b == 0:
                return True
        elif instruction.name in {"SETTABLE", "SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
            if instruction.b == 0:
                return True
        elif instruction.name in {"NAMECALL", "NAMECALLUDATA"} and instruction.b == 0:
            return True
    return False


def _return_hint(name: str, kind: FunctionKind, owner_name: str | None) -> str | None:
    if kind == "constructor":
        return owner_name
    if kind == "metamethod":
        return _METAMETHOD_RETURN_TYPES.get(name)
    if name in {"compare", "lessThan", "predicate"}:
        return "boolean"
    if name in {"toString", "serialize"}:
        return "string"
    return None


def _make_context(
    module: LuauBytecodeModule,
    child_id: int,
    *,
    name: str,
    kind: FunctionKind,
    owner_name: str | None,
    confidence: int,
    evidence: str,
    parameter_types: Sequence[str] = (),
) -> FunctionContext:
    child = module.protos[child_id]
    names = parameter_names_for_types(parameter_types)
    parameter_name_map = {index: value for index, value in enumerate(names)}
    parameter_type_map = {
        index: value
        for index, value in enumerate(parameter_types)
        if index < child.num_params and not value.startswith("...")
    }
    if kind in {"instance_method", "metamethod"} and child.num_params:
        parameter_name_map[0] = "self"
        if owner_name:
            parameter_type_map.setdefault(0, owner_name)
    if kind == "metamethod":
        for index, value in enumerate(_METAMETHOD_PARAMETER_NAMES.get(name, ())):
            if index < child.num_params:
                parameter_name_map.setdefault(index, value)
    return FunctionContext(
        proto_id=child_id,
        name=name,
        kind=kind,
        owner_name=owner_name,
        parameter_names=MappingProxyType(parameter_name_map),
        parameter_types=MappingProxyType(parameter_type_map),
        return_type=_return_hint(name, kind, owner_name),
        confidence=confidence,
        evidence=(evidence,),
    )


def _merge_contexts(left: FunctionContext, right: FunctionContext) -> FunctionContext:
    primary, secondary = (left, right) if left.confidence >= right.confidence else (right, left)
    parameter_names = dict(secondary.parameter_names)
    parameter_names.update(primary.parameter_names)
    parameter_types = dict(secondary.parameter_types)
    for index, type_name in primary.parameter_types.items():
        existing = parameter_types.get(index)
        if existing is None or existing == type_name:
            parameter_types[index] = type_name
    evidence = tuple(dict.fromkeys((*primary.evidence, *secondary.evidence)))
    return FunctionContext(
        proto_id=primary.proto_id,
        name=primary.name,
        kind=primary.kind,
        owner_name=primary.owner_name or secondary.owner_name,
        parameter_names=MappingProxyType(parameter_names),
        parameter_types=MappingProxyType(parameter_types),
        return_type=primary.return_type or secondary.return_type,
        confidence=primary.confidence,
        evidence=evidence,
    )


def plan_contextual_functions(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    class_plan: ClassRecoveryPlan,
    *,
    callback_plan: InlineCallbackPlan | None = None,
    enabled: bool = True,
) -> FunctionContextPlan:
    if not enabled:
        return FunctionContextPlan.empty()
    instructions_by_pc = {instruction.pc: instruction for instruction in instructions}
    by_proto: dict[int, FunctionContext] = {}
    by_value: dict[SSAValue, FunctionContext] = {}

    def add(context: FunctionContext, value: SSAValue | None = None) -> None:
        existing = by_proto.get(context.proto_id)
        by_proto[context.proto_id] = (
            context if existing is None else _merge_contexts(existing, context)
        )
        if value is not None:
            current = by_value.get(value)
            by_value[value] = context if current is None else _merge_contexts(current, context)

    for declaration in class_plan.declarations.values():
        for method in declaration.methods:
            context = _context_from_class_method(declaration.name, method)
            if context is not None:
                add(context)

    for instruction in instructions:
        if instruction.name in {"SETTABLEKS", "SETUDATAKS"}:
            details = _closure_details(
                module,
                proto,
                instructions_by_pc,
                program,
                program.value_at_use(instruction.pc, instruction.a),
            )
            if details is None:
                continue
            child_id, value = details
            key_index = (
                instruction.userdata_constant_index
                if instruction.name == "SETUDATAKS"
                else instruction.aux
            )
            key = _constant_string(proto, key_index if key_index is not None else -1)
            if key is None:
                continue
            owner_name = _local_name(proto, instruction.b, instruction.pc)
            child = module.protos[child_id]
            kind: FunctionKind = (
                "instance_method" if _first_parameter_is_receiver(child) else "field"
            )
            if key in {"new", "create"}:
                kind = "constructor"
            elif key.startswith("__"):
                kind = "metamethod"
            add(
                _make_context(
                    module,
                    child_id,
                    name=key,
                    kind=kind,
                    owner_name=owner_name,
                    confidence=78,
                    evidence="function assigned to named table field",
                ),
                value,
            )
        elif instruction.name == "SETGLOBAL":
            details = _closure_details(
                module,
                proto,
                instructions_by_pc,
                program,
                program.value_at_use(instruction.pc, instruction.a),
            )
            if details is None:
                continue
            child_id, value = details
            key = _constant_string(proto, instruction.aux if instruction.aux is not None else -1)
            if key is None:
                continue
            add(
                _make_context(
                    module,
                    child_id,
                    name=key,
                    kind="global",
                    owner_name=None,
                    confidence=86,
                    evidence="function assigned to global",
                ),
                value,
            )
        elif instruction.name == "RETURN" and instruction.b > 1:
            for register in range(instruction.a, instruction.a + instruction.b - 1):
                details = _closure_details(
                    module,
                    proto,
                    instructions_by_pc,
                    program,
                    program.value_at_use(instruction.pc, register),
                )
                if details is None:
                    continue
                child_id, value = details
                debug_name = module.protos[child_id].debug_name or "returnedFunction"
                add(
                    _make_context(
                        module,
                        child_id,
                        name=debug_name,
                        kind="returned",
                        owner_name=None,
                        confidence=62,
                        evidence="function returned from prototype",
                    ),
                    value,
                )

    resolved_callback_plan = callback_plan or plan_inline_callbacks(
        module,
        proto,
        instructions,
        program,
        enabled=True,
    )
    for value, child_id in resolved_callback_plan.proto_by_value.items():
        types = resolved_callback_plan.parameter_types_by_value.get(value, ())
        child = module.protos[child_id]
        name = child.debug_name or "callback"
        add(
            _make_context(
                module,
                child_id,
                name=name,
                kind="callback",
                owner_name=None,
                confidence=82 if types else 66,
                evidence="recognized callback sink",
                parameter_types=types,
            ),
            value,
        )

    return FunctionContextPlan(
        MappingProxyType(by_proto),
        MappingProxyType(by_value),
    )


def collect_module_function_contexts(
    module: LuauBytecodeModule,
    *,
    recover_metatable_classes: bool = True,
    enabled: bool = True,
) -> Mapping[int, FunctionContext]:
    if not enabled:
        return MappingProxyType(dict[int, FunctionContext]())
    from lunaux.backends.classes import recover_classes

    contexts: dict[int, FunctionContext] = {}
    for proto in module.protos:
        instructions = tuple(decode_words(proto.code))
        program = build_ssa(instructions, len(proto.code))
        class_plan = recover_classes(
            module,
            proto,
            instructions,
            program,
            recover_metatable_classes=recover_metatable_classes,
        )
        plan = plan_contextual_functions(
            module,
            proto,
            instructions,
            program,
            class_plan,
            enabled=True,
        )
        for proto_id, context in plan.by_proto.items():
            current = contexts.get(proto_id)
            contexts[proto_id] = context if current is None else _merge_contexts(current, context)
    return MappingProxyType(contexts)
