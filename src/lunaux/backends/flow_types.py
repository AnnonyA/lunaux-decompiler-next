from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from lunaux.backends.analysis import ControlFlowAnalysis, analyze_control_flow
from lunaux.backends.bytecode import LuauProto
from lunaux.backends.opcodes import DecodedInstruction, get_jump_target
from lunaux.backends.ssa import SSAProgram, SSAValue
from lunaux.backends.type_inference import merge_types


@dataclass(frozen=True, slots=True)
class FlowTypeFact:
    value: SSAValue
    type_name: str
    block: int
    source_pc: int
    evidence: str


@dataclass(frozen=True, slots=True)
class FlowTypeAnalysis:
    use_types: Mapping[tuple[int, int], str]
    use_evidence: Mapping[tuple[int, int], str]
    facts: tuple[FlowTypeFact, ...]

    @classmethod
    def empty(cls) -> FlowTypeAnalysis:
        return cls(
            MappingProxyType(dict[tuple[int, int], str]()),
            MappingProxyType(dict[tuple[int, int], str]()),
            (),
        )

    def type_at_use(self, pc: int, register: int) -> str | None:
        return self.use_types.get((pc, register))

    def evidence_at_use(self, pc: int, register: int) -> str | None:
        return self.use_evidence.get((pc, register))

    def report_lines(self, *, limit: int = 32) -> tuple[str, ...]:
        lines: list[str] = []
        for fact in self.facts:
            lines.append(
                f"use@L{fact.source_pc:04d} {fact.value.name}: {fact.type_name} [{fact.evidence}]"
            )
            if len(lines) >= limit:
                break
        return tuple(lines)


@dataclass(frozen=True, slots=True)
class _EnvFact:
    type_name: str
    evidence: str
    source_pc: int


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
    result: list[str] = []
    for index in indices[: min(count, 3)]:
        value = _constant_string(proto, index)
        if value is None:
            return ()
        result.append(value)
    return tuple(result)


def _value_path(
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
    visited = seen | frozenset({value})
    if instruction.name == "GETGLOBAL":
        return _constant_string(proto, instruction.aux if instruction.aux is not None else -1)
    if instruction.name == "GETIMPORT":
        path = _import_path(proto, instruction.aux)
        return ".".join(path) if path else None
    if instruction.name in {"GETTABLEKS", "GETUDATAKS"}:
        key_index = (
            instruction.userdata_constant_index
            if instruction.name == "GETUDATAKS"
            else instruction.aux
        )
        key = _constant_string(proto, key_index if key_index is not None else -1)
        prefix = _value_path(
            proto,
            instructions_by_pc,
            program,
            program.value_at_use(instruction.pc, instruction.b),
            visited,
        )
        if prefix and key:
            return f"{prefix}.{key}"
        return key
    if instruction.name == "MOVE":
        return _value_path(
            proto,
            instructions_by_pc,
            program,
            program.value_at_use(instruction.pc, instruction.b),
            visited,
        )
    return None


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
            seen | frozenset({value}),
        )
    return None


def _previous_namecall(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    call: DecodedInstruction,
) -> tuple[DecodedInstruction, str] | None:
    previous_by_next = {item.pc + item.size: item for item in instructions}
    candidate = previous_by_next.get(call.pc)
    if candidate is None or candidate.name not in {"NAMECALL", "NAMECALLUDATA"}:
        return None
    if candidate.a != call.a:
        return None
    index = (
        candidate.userdata_constant_index if candidate.name == "NAMECALLUDATA" else candidate.aux
    )
    method = _constant_string(proto, index if index is not None else -1)
    return (candidate, method) if method is not None else None


def _call_origin(
    instructions_by_pc: Mapping[int, DecodedInstruction],
    value: SSAValue | None,
) -> DecodedInstruction | None:
    if value is None or value.origin_pc is None:
        return None
    instruction = instructions_by_pc.get(value.origin_pc)
    if instruction is None or instruction.name not in {"CALL", "CALLFB"}:
        return None
    return instruction


def _without_nil(type_name: str | None) -> str | None:
    if not type_name or type_name in {"any", "nil"}:
        return None
    if type_name.endswith("?"):
        return type_name[:-1]
    parts = [part.strip() for part in type_name.split(" | ")]
    remaining = [part for part in parts if part != "nil"]
    if not remaining or len(remaining) == len(parts):
        return type_name if len(parts) == 1 else None
    return merge_types(remaining)


def _merge_environments(
    environments: Sequence[Mapping[SSAValue, _EnvFact]],
) -> dict[SSAValue, _EnvFact]:
    if not environments:
        return {}
    common = set(environments[0])
    for environment in environments[1:]:
        common.intersection_update(environment)
    result: dict[SSAValue, _EnvFact] = {}
    for value in common:
        facts = [environment[value] for environment in environments]
        merged_type = merge_types(fact.type_name for fact in facts)
        if merged_type is None:
            continue
        evidence = facts[0].evidence
        if any(fact.evidence != evidence for fact in facts[1:]):
            evidence = "merged flow refinements"
        result[value] = _EnvFact(
            merged_type,
            evidence,
            min(fact.source_pc for fact in facts),
        )
    return result


def _successor_blocks(
    analysis: ControlFlowAnalysis,
    instruction: DecodedInstruction,
) -> tuple[int | None, int | None]:
    target_pc = get_jump_target(instruction)
    fallthrough_pc = instruction.pc + instruction.size
    taken = analysis.block_for_pc.get(target_pc) if target_pc is not None else None
    fallthrough = analysis.block_for_pc.get(fallthrough_pc)
    return fallthrough, taken


def _set_fact(
    environment: dict[SSAValue, _EnvFact],
    value: SSAValue | None,
    type_name: str | None,
    source_pc: int,
    evidence: str,
) -> None:
    if value is None or type_name is None or type_name == "any":
        return
    environment[value] = _EnvFact(type_name, evidence, source_pc)


def _truthy_fact(
    value: SSAValue | None,
    base_types: Mapping[SSAValue, str],
    source_pc: int,
) -> tuple[SSAValue, _EnvFact] | None:
    if value is None:
        return None
    narrowed = _without_nil(base_types.get(value))
    if narrowed is None:
        return None
    return value, _EnvFact(narrowed, "truthy branch removes nil", source_pc)


def _predicate_target(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    instructions_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    condition_value: SSAValue | None,
) -> tuple[SSAValue, str, str] | None:
    call = _call_origin(instructions_by_pc, condition_value)
    if call is None:
        return None
    namecall = _previous_namecall(proto, instructions, call)
    if namecall is not None:
        namecall_instruction, method = namecall
        if method == "IsA" and call.b > 2:
            receiver = program.value_at_use(
                namecall_instruction.pc,
                namecall_instruction.b,
            )
            class_name = _literal_string(
                proto,
                instructions_by_pc,
                program,
                program.value_at_use(call.pc, call.a + 2),
            )
            if receiver is not None and class_name:
                return receiver, class_name, f'IsA("{class_name}") true branch'
    function = program.value_at_use(call.pc, call.a)
    path = _value_path(proto, instructions_by_pc, program, function)
    if path not in {"assert"} or call.b <= 1:
        return None
    argument = program.value_at_use(call.pc, call.a + 1)
    if argument is None:
        return None
    return argument, "truthy", "asserted value"


def _apply_post_instruction_refinement(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    instructions_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    base_types: Mapping[SSAValue, str],
    instruction: DecodedInstruction,
    environment: dict[SSAValue, _EnvFact],
) -> None:
    if instruction.name not in {"CALL", "CALLFB"}:
        return
    function = program.value_at_use(instruction.pc, instruction.a)
    path = _value_path(proto, instructions_by_pc, program, function)
    if path != "assert" or instruction.b <= 1:
        return
    argument = program.value_at_use(instruction.pc, instruction.a + 1)
    narrowed = _without_nil(base_types.get(argument)) if argument is not None else None
    _set_fact(environment, argument, narrowed, instruction.pc, "assert removes nil")


def _branch_environments(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    instructions_by_pc: Mapping[int, DecodedInstruction],
    program: SSAProgram,
    base_types: Mapping[SSAValue, str],
    analysis: ControlFlowAnalysis,
    instruction: DecodedInstruction,
    environment: Mapping[SSAValue, _EnvFact],
) -> dict[int, dict[SSAValue, _EnvFact]]:
    fallthrough, taken = _successor_blocks(analysis, instruction)
    result: dict[int, dict[SSAValue, _EnvFact]] = {}
    if fallthrough is not None:
        result[fallthrough] = dict(environment)
    if taken is not None:
        result[taken] = dict(environment)
    if fallthrough is None or taken is None:
        return result

    if instruction.name == "JUMPXEQKNIL":
        nil_value = program.value_at_use(instruction.pc, instruction.a)
        equality_block = fallthrough if instruction.aux_not else taken
        non_nil_block = taken if instruction.aux_not else fallthrough
        _set_fact(
            result[equality_block],
            nil_value,
            "nil",
            instruction.pc,
            "nil equality branch",
        )
        narrowed = _without_nil(base_types.get(nil_value)) if nil_value is not None else None
        _set_fact(
            result[non_nil_block],
            nil_value,
            narrowed,
            instruction.pc,
            "nil check false branch",
        )
        return result

    if instruction.name in {"JUMPIFEQ", "JUMPIFNOTEQ"}:
        rhs_register = (instruction.aux or 0) & 0xFF
        left = program.value_at_use(instruction.pc, instruction.a)
        right = program.value_at_use(instruction.pc, rhs_register)
        left_origin = (
            instructions_by_pc.get(left.origin_pc) if left and left.origin_pc is not None else None
        )
        right_origin = (
            instructions_by_pc.get(right.origin_pc)
            if right and right.origin_pc is not None
            else None
        )
        value: SSAValue | None = None
        if left_origin is not None and left_origin.name == "LOADNIL":
            value = right
        elif right_origin is not None and right_origin.name == "LOADNIL":
            value = left
        if value is not None:
            equality_block = taken if instruction.name == "JUMPIFEQ" else fallthrough
            non_nil_block = fallthrough if instruction.name == "JUMPIFEQ" else taken
            _set_fact(result[equality_block], value, "nil", instruction.pc, "nil equality branch")
            _set_fact(
                result[non_nil_block],
                value,
                _without_nil(base_types.get(value)),
                instruction.pc,
                "nil comparison false branch",
            )
        return result

    if instruction.name == "JUMPXEQKS":
        condition_value = program.value_at_use(instruction.pc, instruction.a)
        call = _call_origin(instructions_by_pc, condition_value)
        literal = _constant_string(proto, (instruction.aux or 0) & 0xFFFFFF)
        if call is not None and literal:
            function = program.value_at_use(call.pc, call.a)
            path = _value_path(proto, instructions_by_pc, program, function)
            if path in {"type", "typeof"} and call.b > 1:
                argument = program.value_at_use(call.pc, call.a + 1)
                equality_block = fallthrough if instruction.aux_not else taken
                _set_fact(
                    result[equality_block],
                    argument,
                    literal,
                    instruction.pc,
                    f'{path}(value) == "{literal}"',
                )
        return result

    if instruction.name in {"JUMPIF", "JUMPIFNOT"}:
        condition_value = program.value_at_use(instruction.pc, instruction.a)
        truth_block = taken if instruction.name == "JUMPIF" else fallthrough
        predicate = _predicate_target(
            proto,
            instructions,
            instructions_by_pc,
            program,
            condition_value,
        )
        if predicate is not None:
            value, target_type, evidence = predicate
            if target_type == "truthy":
                narrowed = _without_nil(base_types.get(value))
                _set_fact(result[truth_block], value, narrowed, instruction.pc, evidence)
            else:
                _set_fact(result[truth_block], value, target_type, instruction.pc, evidence)
        else:
            truthy = _truthy_fact(condition_value, base_types, instruction.pc)
            if truthy is not None:
                value, fact = truthy
                result[truth_block][value] = fact
        return result

    return result


def analyze_flow_types(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    base_types: Mapping[SSAValue, str],
    *,
    analysis: ControlFlowAnalysis | None = None,
    enabled: bool = True,
) -> FlowTypeAnalysis:
    if not enabled or not instructions:
        return FlowTypeAnalysis.empty()
    resolved_analysis = analysis or analyze_control_flow(tuple(instructions), len(proto.code))
    instructions_by_pc = {instruction.pc: instruction for instruction in instructions}
    block_in: dict[int, dict[SSAValue, _EnvFact]] = {resolved_analysis.entry: {}}
    edge_out: dict[tuple[int, int], dict[SSAValue, _EnvFact]] = {}
    queue: deque[int] = deque([resolved_analysis.entry])
    queued = {resolved_analysis.entry}

    while queue:
        block_start = queue.popleft()
        queued.discard(block_start)
        block = resolved_analysis.block_by_start[block_start]
        environment = dict(block_in.get(block_start, {}))
        for instruction in block.instructions:
            _apply_post_instruction_refinement(
                proto,
                instructions,
                instructions_by_pc,
                program,
                base_types,
                instruction,
                environment,
            )
        terminator = block.terminator
        outgoing = (
            _branch_environments(
                proto,
                instructions,
                instructions_by_pc,
                program,
                base_types,
                resolved_analysis,
                terminator,
                environment,
            )
            if terminator is not None
            else {successor: dict(environment) for successor in block.successors}
        )
        for successor in block.successors:
            new_edge = outgoing.get(successor, dict(environment))
            edge_key = (block_start, successor)
            if edge_out.get(edge_key) == new_edge:
                continue
            edge_out[edge_key] = new_edge
            incoming = [
                edge_out[(predecessor, successor)]
                for predecessor in resolved_analysis.block_by_start[successor].predecessors
                if (predecessor, successor) in edge_out
            ]
            merged = _merge_environments(incoming)
            if block_in.get(successor) != merged:
                block_in[successor] = merged
                if successor not in queued:
                    queue.append(successor)
                    queued.add(successor)

    use_types: dict[tuple[int, int], str] = {}
    use_evidence: dict[tuple[int, int], str] = {}
    fact_rows: list[FlowTypeFact] = []
    seen_rows: set[tuple[SSAValue, str, int, str]] = set()
    for block in resolved_analysis.blocks:
        environment = dict(block_in.get(block.start_pc, {}))
        for instruction in block.instructions:
            ssa_instruction = program.instruction_at(instruction.pc)
            if ssa_instruction is not None:
                for use in ssa_instruction.uses:
                    fact = environment.get(use.value)
                    if fact is None:
                        continue
                    key = (instruction.pc, use.register)
                    use_types[key] = fact.type_name
                    use_evidence[key] = fact.evidence
                    row_key = (use.value, fact.type_name, fact.source_pc, fact.evidence)
                    if row_key not in seen_rows:
                        seen_rows.add(row_key)
                        fact_rows.append(
                            FlowTypeFact(
                                use.value,
                                fact.type_name,
                                block.start_pc,
                                fact.source_pc,
                                fact.evidence,
                            )
                        )
            _apply_post_instruction_refinement(
                proto,
                instructions,
                instructions_by_pc,
                program,
                base_types,
                instruction,
                environment,
            )

    fact_rows.sort(key=lambda item: (item.source_pc, item.block, item.value))
    return FlowTypeAnalysis(
        MappingProxyType(use_types),
        MappingProxyType(use_evidence),
        tuple(fact_rows),
    )
