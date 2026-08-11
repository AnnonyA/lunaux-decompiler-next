from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from lunaux.backends.bytecode import LuauBytecodeModule, LuauProto
from lunaux.backends.callframe import CallFramePlan, plan_call_frames
from lunaux.backends.effects import is_transparent_instruction
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.roblox_recovery import (
    InlineCallbackPlan,
    closure_proto_id,
    plan_inline_callbacks,
)
from lunaux.backends.scopes import Binding, ScopeTree
from lunaux.backends.ssa import SSAInstruction, SSAProgram, SSAValue

if TYPE_CHECKING:
    from lunaux.backends.contextual_functions import FunctionContext
    from lunaux.backends.module_analysis import ModuleAnalysis

EmissionKind = Literal[
    "shared-proto",
    "local-function",
    "predeclared-assignment",
    "method-declaration",
    "inline-expression",
]


@dataclass(frozen=True, slots=True)
class CapturePlan:
    upvalue_index: int
    kind: Literal["value", "reference", "upvalue"]
    pc: int
    source_register: int
    source_value: SSAValue | None
    source_binding: Binding | None


@dataclass(frozen=True, slots=True)
class ProtoInstancePlan:
    parent_proto_id: int
    child_proto_id: int
    creation_pc: int
    closure_value: SSAValue
    alias_values: tuple[SSAValue, ...]
    alias_move_pcs: frozenset[int]
    captures: tuple[CapturePlan, ...]
    capture_pcs: frozenset[int]
    terminal_pc: int | None
    terminal_opcode: str | None
    terminal_register: int | None
    semantic_use_count: int
    emission_kind: EmissionKind
    binding_hint: str | None
    binding: Binding | None
    recursive: bool
    recursion_group: tuple[int, ...]
    method_name: str | None
    method_receiver: SSAValue | None
    rejection_reasons: tuple[str, ...]

    @property
    def is_owned(self) -> bool:
        return self.emission_kind != "shared-proto"


@dataclass(frozen=True, slots=True)
class ParentProtoEmissionPlan:
    proto_id: int
    instances: tuple[ProtoInstancePlan, ...]
    by_creation_pc: Mapping[int, ProtoInstancePlan]
    by_value: Mapping[SSAValue, ProtoInstancePlan]
    by_terminal_pc: Mapping[int, ProtoInstancePlan]
    skipped_pcs: frozenset[int]
    callback_plan: InlineCallbackPlan
    call_frames: CallFramePlan

    def at_creation(self, pc: int) -> ProtoInstancePlan | None:
        return self.by_creation_pc.get(pc)

    def for_value(self, value: SSAValue | None) -> ProtoInstancePlan | None:
        return self.by_value.get(value) if value is not None else None

    def at_terminal(self, pc: int) -> ProtoInstancePlan | None:
        return self.by_terminal_pc.get(pc)


@dataclass(frozen=True, slots=True)
class ProtoEmissionPlan:
    parents: Mapping[int, ParentProtoEmissionPlan]
    preemit_proto_ids: frozenset[int]
    owned_proto_ids: frozenset[int]
    rejection_counts: Mapping[str, int]

    def for_parent(self, proto_id: int) -> ParentProtoEmissionPlan:
        return self.parents[proto_id]


def _constant_string(proto: LuauProto, index: int | None) -> str | None:
    if index is None or not 0 <= index < len(proto.constants):
        return None
    constant = proto.constants[index]
    if constant.kind != "string" or not isinstance(constant.value, str):
        return None
    return constant.value


def _uses_for(
    program: SSAProgram,
    value: SSAValue,
) -> tuple[tuple[SSAInstruction, int], ...]:
    result: list[tuple[SSAInstruction, int]] = []
    for instruction in program.instructions.values():
        for use in instruction.uses:
            if use.value == value:
                result.append((instruction, use.register))
    return tuple(result)


def _terminal_use(
    program: SSAProgram,
    value: SSAValue,
) -> tuple[SSAInstruction, int, tuple[SSAValue, ...], frozenset[int]] | None:
    current = value
    values = [value]
    move_pcs: set[int] = set()
    visited: set[SSAValue] = set()
    while current not in visited:
        visited.add(current)
        uses = _uses_for(program, current)
        if len(uses) != 1:
            return None
        use_instruction, register = uses[0]
        instruction = use_instruction.instruction
        if instruction.name != "MOVE" or register != instruction.b:
            return use_instruction, register, tuple(values), frozenset(move_pcs)
        destination = program.value_defined_at(instruction.pc, instruction.a)
        if destination is None:
            return None
        move_pcs.add(instruction.pc)
        current = destination
        values.append(destination)
    return None


def _binding_at_definition(
    scope_tree: ScopeTree,
    instructions_by_pc: Mapping[int, DecodedInstruction],
    value: SSAValue,
    first_use_by_value: Mapping[SSAValue, int],
    definition_pcs_by_register: Mapping[int, tuple[int, ...]],
    register: int,
    pc: int,
) -> Binding | None:
    direct = scope_tree.binding_for_register(register, pc)
    if direct is not None:
        return direct
    instruction = instructions_by_pc.get(pc)
    end_pc = pc + (instruction.size if instruction is not None else 1)
    end_pc = first_use_by_value.get(value, end_pc)
    candidates = [
        binding
        for scope in scope_tree.scopes.values()
        for binding in scope.bindings
        if binding.register == register
        and pc < binding.start_pc <= end_pc
        and not any(
            pc < definition_pc < binding.start_pc
            for definition_pc in definition_pcs_by_register.get(register, ())
        )
    ]
    return min(
        candidates,
        key=lambda item: (item.start_pc, item.end_pc, item.name),
        default=None,
    )


def _captures(
    module: LuauBytecodeModule,
    parent: LuauProto,
    child_id: int,
    creation: DecodedInstruction,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    scope_tree: ScopeTree,
) -> tuple[CapturePlan, ...] | None:
    child = module.protos[child_id]
    positions = {instruction.pc: index for index, instruction in enumerate(instructions)}
    start = positions[creation.pc] + 1
    result: list[CapturePlan] = []
    kinds: dict[int, Literal["value", "reference", "upvalue"]] = {
        0: "value",
        1: "reference",
        2: "upvalue",
    }
    for upvalue_index in range(child.num_upvalues):
        position = start + upvalue_index
        if position >= len(instructions):
            return None
        capture = instructions[position]
        if capture.name != "CAPTURE" or capture.a not in kinds:
            return None
        source_value = (
            None
            if capture.a == 2
            else program.value_at_use(capture.pc, capture.b)
        )
        source_binding = (
            scope_tree.binding_for_register(capture.b, capture.pc)
            if capture.a == 1
            else None
        )
        result.append(
            CapturePlan(
                upvalue_index=upvalue_index,
                kind=kinds[capture.a],
                pc=capture.pc,
                source_register=capture.b,
                source_value=source_value,
                source_binding=source_binding,
            )
        )
    return tuple(result)


def _canonical_move(program: SSAProgram, value: SSAValue | None) -> SSAValue | None:
    current = value
    seen: set[SSAValue] = set()
    while current is not None and current not in seen and current.origin_pc is not None:
        seen.add(current)
        instruction = program.instructions.get(current.origin_pc)
        if instruction is None or instruction.instruction.name != "MOVE":
            break
        current = program.value_at_use(current.origin_pc, instruction.instruction.b)
    return current


def _receiver_is_structural(
    child_program: SSAProgram,
    child: LuauProto,
) -> bool:
    if child.num_params == 0:
        return False
    receiver = child_program.entry_values.get(0)
    if receiver is None:
        return False
    structural_ops = {
        "GETTABLE",
        "GETTABLEKS",
        "GETUDATAKS",
        "GETTABLEN",
        "SETTABLE",
        "SETTABLEKS",
        "SETUDATAKS",
        "SETTABLEN",
        "NAMECALL",
        "NAMECALLUDATA",
    }
    return any(
        instruction.instruction.name in structural_ops
        and any(use.value == receiver for use in instruction.uses)
        for instruction in child_program.instructions.values()
    )


def _stable_method_base(program: SSAProgram, value: SSAValue | None) -> bool:
    canonical = _canonical_move(program, value)
    if canonical is None or canonical.origin_pc is None:
        return canonical is not None and canonical.kind == "entry"
    instruction = program.instructions.get(canonical.origin_pc)
    return instruction is not None and instruction.instruction.name in {
        "NEWTABLE",
        "DUPTABLE",
        "GETGLOBAL",
        "GETIMPORT",
        "GETUPVAL",
        "GETTABLEKS",
        "GETUDATAKS",
    }


def _matching_namecall(
    proto: LuauProto,
    program: SSAProgram,
    store_pc: int,
    receiver: SSAValue | None,
    method_name: str,
) -> bool:
    canonical_receiver = _canonical_move(program, receiver)
    for pc in sorted(program.instructions):
        if pc <= store_pc:
            continue
        instruction = program.instructions[pc].instruction
        if instruction.name not in {"NAMECALL", "NAMECALLUDATA"}:
            continue
        key_index = (
            instruction.userdata_constant_index
            if instruction.name == "NAMECALLUDATA"
            else instruction.aux
        )
        if _constant_string(proto, key_index) != method_name:
            continue
        candidate = _canonical_move(program, program.value_at_use(pc, instruction.b))
        if candidate == canonical_receiver:
            return True
    return False


def _transparent_gap(
    program: SSAProgram,
    creation_pc: int,
    terminal_pc: int,
    allowed_pcs: frozenset[int],
) -> bool:
    creation_block = program.analysis.block_for_pc.get(creation_pc)
    if creation_block is None or creation_block != program.analysis.block_for_pc.get(terminal_pc):
        return False
    for pc in sorted(program.instructions):
        if not creation_pc < pc < terminal_pc or pc in allowed_pcs:
            continue
        if not is_transparent_instruction(program.instructions[pc].instruction):
            return False
    return True


def _strongly_connected_components(
    nodes: Sequence[int],
    edges: Mapping[int, frozenset[int]],
) -> tuple[tuple[int, ...], ...]:
    index = 0
    stack: list[int] = []
    on_stack: set[int] = set()
    indices: dict[int, int] = {}
    lowlinks: dict[int, int] = {}
    result: list[tuple[int, ...]] = []

    def visit(node: int) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(edges.get(node, frozenset())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[int] = []
        while stack:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        result.append(tuple(sorted(component)))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return tuple(sorted(result, key=lambda item: item[0]))


def _plan_parent(
    module: LuauBytecodeModule,
    parent: LuauProto,
    module_analysis: ModuleAnalysis,
    contexts: Mapping[int, FunctionContext],
    *,
    inline_callbacks: bool,
) -> ParentProtoEmissionPlan:
    analyzed = module_analysis.for_proto(parent)
    instructions = analyzed.instructions
    program = analyzed.ssa
    scope_tree = analyzed.scope_tree
    instructions_by_pc = {instruction.pc: instruction for instruction in instructions}
    first_use_by_value: dict[SSAValue, int] = {}
    definition_pcs_by_register: dict[int, list[int]] = defaultdict(list)
    for ssa_instruction in sorted(program.instructions.values(), key=lambda item: item.pc):
        for use in ssa_instruction.uses:
            first_use_by_value.setdefault(use.value, ssa_instruction.pc)
        for definition in ssa_instruction.definitions:
            definition_pcs_by_register[definition.register].append(ssa_instruction.pc)
    frozen_definition_pcs = {
        register: tuple(pcs)
        for register, pcs in definition_pcs_by_register.items()
    }
    callback_plan = plan_inline_callbacks(
        module,
        parent,
        instructions,
        program,
        enabled=inline_callbacks,
    )
    call_frames = plan_call_frames(program)
    instances: list[ProtoInstancePlan] = []
    rejection_counts: Counter[str] = Counter()

    for instruction in instructions:
        child_id = closure_proto_id(parent, instruction)
        if child_id is None or not 0 <= child_id < len(module.protos):
            continue
        closure_value = program.value_defined_at(instruction.pc, instruction.a)
        if closure_value is None:
            continue
        capture_plan = _captures(
            module,
            parent,
            child_id,
            instruction,
            instructions,
            program,
            scope_tree,
        )
        reasons: list[str] = []
        if capture_plan is None:
            capture_plan = ()
            reasons.append("invalid-capture-layout")
        capture_pcs = frozenset(capture.pc for capture in capture_plan)
        terminal = _terminal_use(program, closure_value)
        terminal_instruction: SSAInstruction | None
        terminal_register: int | None
        aliases: tuple[SSAValue, ...]
        alias_move_pcs: frozenset[int]
        if terminal is None:
            terminal_instruction = None
            terminal_register = None
            aliases = (closure_value,)
            alias_move_pcs = frozenset()
            reasons.append("not-single-use")
        else:
            terminal_instruction, terminal_register, aliases, alias_move_pcs = terminal
        binding = _binding_at_definition(
            scope_tree,
            instructions_by_pc,
            closure_value,
            first_use_by_value,
            frozen_definition_pcs,
            instruction.a,
            instruction.pc,
        )
        context = contexts.get(child_id)
        binding_hint = (
            binding.name
            if binding is not None
            else module.protos[child_id].debug_name
            or (context.name if context is not None else None)
        )
        recursive = any(
            capture.kind in {"value", "reference"}
            and capture.source_value == closure_value
            for capture in capture_plan
        )
        kind: EmissionKind = "shared-proto"
        method_name: str | None = None
        method_receiver: SSAValue | None = None

        if terminal_instruction is not None:
            sink = terminal_instruction.instruction
            if (
                sink.name in {"SETTABLEKS", "SETUDATAKS"}
                and terminal_register == sink.a
            ):
                key_index = (
                    sink.userdata_constant_index
                    if sink.name == "SETUDATAKS"
                    else sink.aux
                )
                candidate_name = _constant_string(parent, key_index)
                receiver = program.value_at_use(sink.pc, sink.b)
                child = module.protos[child_id]
                child_program = module_analysis.for_proto(child).ssa
                allowed = capture_pcs | alias_move_pcs
                if candidate_name is None:
                    reasons.append("method-key-not-identifier")
                elif not _receiver_is_structural(child_program, child):
                    reasons.append("first-parameter-not-structural-receiver")
                elif not _stable_method_base(program, receiver):
                    reasons.append("unstable-method-base")
                elif not _matching_namecall(parent, program, sink.pc, receiver, candidate_name):
                    reasons.append("no-matching-namecall-evidence")
                elif not _transparent_gap(
                    program,
                    instruction.pc,
                    sink.pc,
                    allowed,
                ):
                    reasons.append("method-creation-barrier")
                elif recursive:
                    reasons.append("recursive-field-requires-explicit-binding")
                else:
                    kind = "method-declaration"
                    method_name = candidate_name
                    method_receiver = receiver

        if kind == "shared-proto" and recursive:
            kind = "local-function"
        elif kind == "shared-proto" and any(
            value in callback_plan.proto_by_value for value in aliases
        ):
            kind = "inline-expression"
        elif (
            kind == "shared-proto"
            and binding_hint is not None
            and (context is None or context.kind != "global")
        ):
            kind = "local-function"
        elif (
            kind == "shared-proto"
            and terminal_instruction is not None
            and terminal_instruction.instruction.name in {"CALL", "CALLFB"}
            and terminal_register == terminal_instruction.instruction.a
            and not alias_move_pcs
        ):
            kind = "local-function"

        for reason in reasons:
            rejection_counts[reason] += 1
        instances.append(
            ProtoInstancePlan(
                parent_proto_id=parent.proto_id,
                child_proto_id=child_id,
                creation_pc=instruction.pc,
                closure_value=closure_value,
                alias_values=aliases,
                alias_move_pcs=alias_move_pcs,
                captures=tuple(capture_plan),
                capture_pcs=capture_pcs,
                terminal_pc=(
                    terminal_instruction.pc if terminal_instruction is not None else None
                ),
                terminal_opcode=(
                    terminal_instruction.instruction.name
                    if terminal_instruction is not None
                    else None
                ),
                terminal_register=terminal_register,
                semantic_use_count=sum(program.uses_of(value) for value in aliases),
                emission_kind=kind,
                binding_hint=binding_hint,
                binding=binding,
                recursive=recursive,
                recursion_group=(instruction.pc,) if recursive else (),
                method_name=method_name,
                method_receiver=method_receiver,
                rejection_reasons=tuple(reasons),
            )
        )

    binding_owner = {
        instance.binding: instance.creation_pc
        for instance in instances
        if instance.binding is not None
    }
    edges: dict[int, set[int]] = defaultdict(set)
    by_pc = {instance.creation_pc: instance for instance in instances}
    for instance in instances:
        for capture in instance.captures:
            target = (
                binding_owner.get(capture.source_binding)
                if capture.source_binding is not None
                else None
            )
            if target is not None:
                edges[instance.creation_pc].add(target)
    components = _strongly_connected_components(
        tuple(by_pc),
        {pc: frozenset(targets) for pc, targets in edges.items()},
    )
    group_by_pc = {
        pc: component
        for component in components
        if len(component) > 1
        for pc in component
    }
    if group_by_pc:
        instances = [
            replace(
                instance,
                emission_kind="predeclared-assignment",
                recursive=True,
                recursion_group=group_by_pc[instance.creation_pc],
            )
            if instance.creation_pc in group_by_pc
            else instance
            for instance in instances
        ]

    instances.sort(key=lambda item: item.creation_pc)
    by_creation = {instance.creation_pc: instance for instance in instances}
    by_value = {
        value: instance
        for instance in instances
        for value in instance.alias_values
    }
    by_terminal = {
        instance.terminal_pc: instance
        for instance in instances
        if instance.terminal_pc is not None
        and instance.emission_kind == "method-declaration"
    }
    skipped_pcs = {
        pc
        for instance in instances
        if instance.is_owned
        for pc in (
            *instance.capture_pcs,
            *(
                instance.alias_move_pcs
                if instance.emission_kind == "method-declaration"
                else frozenset()
            ),
        )
    }
    return ParentProtoEmissionPlan(
        proto_id=parent.proto_id,
        instances=tuple(instances),
        by_creation_pc=MappingProxyType(by_creation),
        by_value=MappingProxyType(by_value),
        by_terminal_pc=MappingProxyType(by_terminal),
        skipped_pcs=frozenset(skipped_pcs),
        callback_plan=callback_plan,
        call_frames=call_frames,
    )


def build_proto_emission_plan(
    module: LuauBytecodeModule,
    module_analysis: ModuleAnalysis,
    contexts: Mapping[int, FunctionContext],
    *,
    inline_callbacks: bool,
) -> ProtoEmissionPlan:
    module_analysis.require_module(module)
    parents = {
        proto.proto_id: _plan_parent(
            module,
            proto,
            module_analysis,
            contexts,
            inline_callbacks=inline_callbacks,
        )
        for proto in module.protos
    }
    references: Counter[int] = Counter()
    owned: Counter[int] = Counter()
    rejection_counts: Counter[str] = Counter()
    for parent in parents.values():
        for instance in parent.instances:
            references[instance.child_proto_id] += 1
            if instance.is_owned:
                owned[instance.child_proto_id] += 1
            rejection_counts.update(instance.rejection_reasons)
    owned_proto_ids = frozenset(
        proto_id
        for proto_id, count in references.items()
        if count > 0 and owned[proto_id] == count
    )
    preemit_proto_ids = frozenset(
        proto.proto_id
        for proto in module.protos
        if proto.proto_id != module.main_proto_id and proto.proto_id not in owned_proto_ids
    )
    return ProtoEmissionPlan(
        parents=MappingProxyType(parents),
        preemit_proto_ids=preemit_proto_ids,
        owned_proto_ids=owned_proto_ids,
        rejection_counts=MappingProxyType(dict(sorted(rejection_counts.items()))),
    )


__all__ = [
    "CapturePlan",
    "EmissionKind",
    "ParentProtoEmissionPlan",
    "ProtoEmissionPlan",
    "ProtoInstancePlan",
    "build_proto_emission_plan",
]
