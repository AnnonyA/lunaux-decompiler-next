from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from lunaux.backends.bytecode import LuauBytecodeModule, LuauProto
from lunaux.backends.opcodes import DecodedInstruction, decode_words
from lunaux.backends.roblox_api import callback_parameter_types
from lunaux.backends.ssa import SSAInstruction, SSAProgram, SSAValue, build_ssa

if TYPE_CHECKING:
    from lunaux.backends.module_analysis import ModuleAnalysis

_EVENT_METHODS: Final[frozenset[str]] = frozenset({"Connect", "ConnectParallel", "Once", "Wait"})
_METHOD_CALLBACK_ARGUMENTS: Final[dict[str, tuple[int, ...]]] = {
    "Connect": (0,),
    "ConnectParallel": (0,),
    "Once": (0,),
    "BindAction": (1,),
    "BindActionAtPriority": (1,),
    "BindToRenderStep": (2,),
    "Subscribe": (0,),
}
_FUNCTION_CALLBACK_ARGUMENTS: Final[dict[str, tuple[int, ...]]] = {
    "coroutine.create": (0,),
    "coroutine.wrap": (0,),
    "pcall": (0,),
    "table.sort": (1,),
    "task.defer": (0,),
    "task.delay": (1,),
    "task.spawn": (0,),
    "xpcall": (0,),
}
_FLOW_BARRIERS: Final[frozenset[str]] = frozenset(
    {"CALL", "CALLFB", "RETURN", "JUMP", "JUMPBACK", "JUMPX"}
)
_IDENTIFIER_CHUNK: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class InlineCallbackPlan:
    proto_by_value: Mapping[SSAValue, int]
    parameter_types_by_value: Mapping[SSAValue, tuple[str, ...]]
    capture_pcs: frozenset[int]

    @classmethod
    def empty(cls) -> InlineCallbackPlan:
        return cls(
            MappingProxyType(dict[SSAValue, int]()),
            MappingProxyType(dict[SSAValue, tuple[str, ...]]()),
            frozenset(),
        )


@dataclass(frozen=True, slots=True)
class RobloxModuleDependency:
    path: str
    name: str
    pc: int


@dataclass(frozen=True, slots=True)
class RobloxEventBinding:
    signal: str
    method: str
    pc: int

    @property
    def display(self) -> str:
        return f"{self.signal}:{self.method}"


@dataclass(frozen=True, slots=True)
class RobloxRecoveryReport:
    events: tuple[RobloxEventBinding, ...]
    dependencies: tuple[RobloxModuleDependency, ...]
    export_kind: Literal["table", "function", "module", "value"] | None


def closure_proto_id(
    proto: LuauProto,
    instruction: DecodedInstruction,
) -> int | None:
    if instruction.name == "NEWCLOSURE" and 0 <= instruction.d < len(proto.child_proto_ids):
        return proto.child_proto_ids[instruction.d]
    if instruction.name != "DUPCLOSURE":
        return None
    if not 0 <= instruction.d < len(proto.constants):
        return None
    constant = proto.constants[instruction.d]
    if constant.kind != "closure" or not isinstance(constant.value, int):
        return None
    return constant.value


def _constant_string(proto: LuauProto, index: int) -> str | None:
    if not 0 <= index < len(proto.constants):
        return None
    constant = proto.constants[index]
    if constant.kind != "string" or not isinstance(constant.value, str):
        return None
    return constant.value


def _import_path(proto: LuauProto, aux: int | None) -> tuple[str, ...]:
    if aux is None:
        return ()
    count = aux >> 30
    indices = ((aux >> 20) & 1023, (aux >> 10) & 1023, aux & 1023)
    names: list[str] = []
    for position in range(min(count, 3)):
        name = _constant_string(proto, indices[position])
        if name is None:
            return ()
        names.append(name)
    return tuple(names)


def _namecall_for_call(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    instruction: DecodedInstruction,
) -> tuple[DecodedInstruction, str] | None:
    previous_by_next_pc = {item.pc + item.size: item for item in instructions}
    candidate = previous_by_next_pc.get(instruction.pc)
    if (
        candidate is None
        or candidate.name not in {"NAMECALL", "NAMECALLUDATA"}
        or candidate.a != instruction.a
    ):
        candidate = None
        for item in reversed(instructions):
            if item.pc >= instruction.pc:
                continue
            if item.name in _FLOW_BARRIERS:
                break
            if item.name in {"NAMECALL", "NAMECALLUDATA"} and item.a == instruction.a:
                candidate = item
                break
    if candidate is None:
        return None
    index = (
        candidate.userdata_constant_index if candidate.name == "NAMECALLUDATA" else candidate.aux
    )
    method = _constant_string(proto, index if index is not None else -1)
    return (candidate, method) if method is not None else None


def _literal_string(
    proto: LuauProto,
    instructions_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    value: SSAValue | None,
    seen: frozenset[SSAValue] = frozenset(),
) -> str | None:
    if value is None or value.origin_pc is None or value in seen:
        return None
    instruction = instructions_by_pc.get(value.origin_pc)
    if instruction is None:
        return None
    next_seen = seen | frozenset({value})
    if instruction.name == "LOADK":
        return _constant_string(proto, instruction.d)
    if instruction.name == "LOADKX":
        return _constant_string(proto, instruction.aux or 0)
    if instruction.name == "MOVE":
        return _literal_string(
            proto,
            instructions_by_pc,
            program,
            program.value_at_use(instruction.pc, instruction.b),
            next_seen,
        )
    return None


def ssa_value_path(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    value: SSAValue | None,
    seen: frozenset[SSAValue] = frozenset(),
) -> str | None:
    if value is None or value.origin_pc is None or value in seen:
        return None
    instructions_by_pc = {item.pc: item for item in instructions}
    instruction = instructions_by_pc.get(value.origin_pc)
    if instruction is None:
        return None
    next_seen = seen | frozenset({value})

    if instruction.name == "GETGLOBAL":
        index = instruction.aux if instruction.aux is not None else -1
        return _constant_string(proto, index)
    if instruction.name == "GETIMPORT":
        path = _import_path(proto, instruction.aux)
        return ".".join(path) if path else None
    if instruction.name in {"GETTABLEKS", "GETUDATAKS"}:
        base = program.value_at_use(instruction.pc, instruction.b)
        key_index = (
            instruction.userdata_constant_index
            if instruction.name == "GETUDATAKS"
            else instruction.aux
        )
        key = _constant_string(proto, key_index if key_index is not None else -1)
        prefix = ssa_value_path(proto, instructions, program, base, next_seen)
        if prefix and key:
            return f"{prefix}.{key}"
        return key
    if instruction.name == "MOVE":
        return ssa_value_path(
            proto,
            instructions,
            program,
            program.value_at_use(instruction.pc, instruction.b),
            next_seen,
        )
    if instruction.name in {"CALL", "CALLFB"}:
        namecall = _namecall_for_call(proto, instructions, instruction)
        if namecall is None or instruction.b <= 2:
            return None
        namecall_instruction, method = namecall
        if method not in {"FindFirstChild", "WaitForChild"}:
            return None
        base = program.value_at_use(
            namecall_instruction.pc,
            namecall_instruction.b,
        )
        prefix = ssa_value_path(proto, instructions, program, base, next_seen)
        literal = _literal_string(
            proto,
            instructions_by_pc,
            program,
            program.value_at_use(instruction.pc, instruction.a + 2),
        )
        if prefix and literal:
            return f"{prefix}.{literal}"
        return literal
    return None


def module_name_from_path(path: str | None) -> str | None:
    if not path:
        return None
    chunks = [str(chunk) for chunk in _IDENTIFIER_CHUNK.findall(path)]
    if not chunks:
        return None
    ignored = {"Parent", "Root", "script", "game", "workspace"}
    selected = next(
        (chunk for chunk in reversed(chunks) if chunk not in ignored),
        chunks[-1],
    )
    if selected.isupper():
        return selected.lower()
    return selected[0].lower() + selected[1:]


def _uses_for(
    program: SSAProgram,
    value: SSAValue,
) -> tuple[tuple[SSAInstruction, int], ...]:
    matches: list[tuple[SSAInstruction, int]] = []
    for instruction in program.instructions.values():
        for use in instruction.uses:
            if use.value == value:
                matches.append((instruction, use.register))
    return tuple(matches)


def _terminal_use(
    program: SSAProgram,
    value: SSAValue,
) -> tuple[SSAInstruction, int, tuple[SSAValue, ...]] | None:
    current = value
    chain = [value]
    visited: set[SSAValue] = set()
    while current not in visited:
        visited.add(current)
        uses = _uses_for(program, current)
        if len(uses) != 1:
            return None
        use_instruction, register = uses[0]
        instruction = use_instruction.instruction
        if instruction.name != "MOVE" or register != instruction.b:
            return use_instruction, register, tuple(chain)
        destination = program.value_defined_at(instruction.pc, instruction.a)
        if destination is None:
            return None
        current = destination
        chain.append(destination)
    return None


def _table_or_return_sink(
    instruction: DecodedInstruction,
    register: int,
) -> bool:
    if instruction.name in {
        "SETTABLE",
        "SETTABLEKS",
        "SETUDATAKS",
        "SETTABLEN",
    }:
        return register == instruction.a
    if instruction.name == "SETLIST" and instruction.c > 1:
        return register in range(instruction.b, instruction.b + instruction.c - 1)
    if instruction.name == "RETURN":
        if instruction.b == 0:
            return False
        return register in range(instruction.a, instruction.a + max(0, instruction.b - 1))
    return False


def _callback_sink(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    instruction: DecodedInstruction,
    register: int,
) -> bool:
    if instruction.name not in {"CALL", "CALLFB"} or instruction.b == 0:
        return False
    namecall = _namecall_for_call(proto, instructions, instruction)
    if namecall is not None:
        _, method = namecall
        positions = _METHOD_CALLBACK_ARGUMENTS.get(method, ())
        return register in {instruction.a + 2 + position for position in positions}
    function_value = program.value_at_use(instruction.pc, instruction.a)
    path = ssa_value_path(proto, instructions, program, function_value)
    positions = _FUNCTION_CALLBACK_ARGUMENTS.get(path or "", ())
    return register in {instruction.a + 1 + position for position in positions}


def _callback_parameter_types_for_sink(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    instruction: DecodedInstruction,
    register: int,
) -> tuple[str, ...] | None:
    if instruction.name not in {"CALL", "CALLFB"} or instruction.b == 0:
        return None
    namecall = _namecall_for_call(proto, instructions, instruction)
    if namecall is not None:
        namecall_instruction, method = namecall
        positions = _METHOD_CALLBACK_ARGUMENTS.get(method, ())
        if register not in {instruction.a + 2 + position for position in positions}:
            return None
        receiver = program.value_at_use(
            namecall_instruction.pc,
            namecall_instruction.b,
        )
        receiver_path = ssa_value_path(proto, instructions, program, receiver)
        return callback_parameter_types(
            method_name=method,
            receiver_path=receiver_path,
        )
    function_value = program.value_at_use(instruction.pc, instruction.a)
    path = ssa_value_path(proto, instructions, program, function_value)
    positions = _FUNCTION_CALLBACK_ARGUMENTS.get(path or "", ())
    if register not in {instruction.a + 1 + position for position in positions}:
        return None
    return callback_parameter_types(function_path=path)


def plan_inline_callbacks(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    *,
    enabled: bool,
) -> InlineCallbackPlan:
    if not enabled:
        return InlineCallbackPlan.empty()

    instruction_index = {instruction.pc: index for index, instruction in enumerate(instructions)}
    proto_by_value: dict[SSAValue, int] = {}
    parameter_types_by_value: dict[SSAValue, tuple[str, ...]] = {}
    capture_pcs: set[int] = set()

    for instruction in instructions:
        child_id = closure_proto_id(proto, instruction)
        if child_id is None or not 0 <= child_id < len(module.protos):
            continue
        value = program.value_defined_at(instruction.pc, instruction.a)
        if value is None:
            continue
        terminal = _terminal_use(program, value)
        if terminal is None:
            continue
        use_instruction, register, chain = terminal
        sink = use_instruction.instruction
        callback_types = _callback_parameter_types_for_sink(
            proto,
            instructions,
            program,
            sink,
            register,
        )
        if not (
            _table_or_return_sink(sink, register)
            or _callback_sink(proto, instructions, program, sink, register)
        ):
            continue

        child = module.protos[child_id]
        captures: list[int] = []
        cursor = instruction_index[instruction.pc] + 1
        valid = True
        for _ in range(child.num_upvalues):
            if cursor >= len(instructions) or instructions[cursor].name != "CAPTURE":
                valid = False
                break
            captures.append(instructions[cursor].pc)
            cursor += 1
        if not valid:
            continue

        for item in chain:
            proto_by_value[item] = child_id
            if callback_types:
                parameter_types_by_value[item] = callback_types
        capture_pcs.update(captures)

    return InlineCallbackPlan(
        MappingProxyType(dict(proto_by_value)),
        MappingProxyType(dict(parameter_types_by_value)),
        frozenset(capture_pcs),
    )


def collect_inline_only_proto_ids(
    module: LuauBytecodeModule,
    *,
    enabled: bool,
    module_analysis: ModuleAnalysis | None = None,
) -> frozenset[int]:
    if not enabled:
        return frozenset()
    if module_analysis is not None:
        module_analysis.require_module(module)
    references: Counter[int] = Counter()
    inline_references: Counter[int] = Counter()
    for proto in module.protos:
        if module_analysis is None:
            instructions = tuple(decode_words(proto.code))
            program = build_ssa(instructions, len(proto.code))
        else:
            analyzed = module_analysis.for_proto(proto)
            instructions = analyzed.instructions
            program = analyzed.ssa
        plan = plan_inline_callbacks(
            module,
            proto,
            instructions,
            program,
            enabled=True,
        )
        for instruction in instructions:
            child_id = closure_proto_id(proto, instruction)
            if child_id is None:
                continue
            references[child_id] += 1
            value = program.value_defined_at(instruction.pc, instruction.a)
            if value is not None and value in plan.proto_by_value:
                inline_references[child_id] += 1
    return frozenset(
        proto_id
        for proto_id, count in references.items()
        if count > 0 and inline_references[proto_id] == count
    )


def _export_kind(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
) -> Literal["table", "function", "module", "value"] | None:
    kinds: set[Literal["table", "function", "module", "value"]] = set()
    instructions_by_pc = {item.pc: item for item in instructions}

    def origin(
        value: SSAValue | None, seen: frozenset[SSAValue] = frozenset()
    ) -> DecodedInstruction | None:
        if value is None or value.origin_pc is None or value in seen:
            return None
        instruction = instructions_by_pc.get(value.origin_pc)
        if instruction is None:
            return None
        if instruction.name == "MOVE":
            return origin(
                program.value_at_use(instruction.pc, instruction.b),
                seen | frozenset({value}),
            )
        return instruction

    for instruction in instructions:
        if instruction.name != "RETURN" or instruction.b in {0, 1}:
            continue
        value = program.value_at_use(instruction.pc, instruction.a)
        source = origin(value)
        if source is None:
            continue
        if source.name in {"NEWTABLE", "DUPTABLE"}:
            kinds.add("table")
        elif source.name in {"NEWCLOSURE", "DUPCLOSURE"}:
            kinds.add("function")
        elif source.name in {"CALL", "CALLFB"}:
            function_path = ssa_value_path(
                proto,
                instructions,
                program,
                program.value_at_use(source.pc, source.a),
            )
            kinds.add("module" if function_path == "require" else "value")
        else:
            kinds.add("value")
    return next(iter(kinds)) if len(kinds) == 1 else None


def analyze_roblox_recovery(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
) -> RobloxRecoveryReport:
    events: list[RobloxEventBinding] = []
    dependencies: list[RobloxModuleDependency] = []

    for instruction in instructions:
        if instruction.name not in {"CALL", "CALLFB"}:
            continue
        namecall = _namecall_for_call(proto, instructions, instruction)
        if namecall is not None:
            namecall_instruction, method = namecall
            if method in _EVENT_METHODS:
                base = program.value_at_use(
                    namecall_instruction.pc,
                    namecall_instruction.b,
                )
                signal = ssa_value_path(proto, instructions, program, base)
                events.append(
                    RobloxEventBinding(
                        signal or f"R{namecall_instruction.b}",
                        method,
                        instruction.pc,
                    )
                )

        function_path = ssa_value_path(
            proto,
            instructions,
            program,
            program.value_at_use(instruction.pc, instruction.a),
        )
        if function_path != "require" or instruction.b <= 1:
            continue
        dependency_path = ssa_value_path(
            proto,
            instructions,
            program,
            program.value_at_use(instruction.pc, instruction.a + 1),
        )
        if dependency_path is None:
            dependency_path = "<dynamic>"
        dependencies.append(
            RobloxModuleDependency(
                dependency_path,
                module_name_from_path(dependency_path) or "module",
                instruction.pc,
            )
        )

    unique_events = {(item.signal, item.method): item for item in events}
    unique_dependencies = {item.path: item for item in dependencies}
    return RobloxRecoveryReport(
        tuple(unique_events[key] for key in sorted(unique_events)),
        tuple(unique_dependencies[key] for key in sorted(unique_dependencies)),
        _export_kind(proto, instructions, program),
    )
