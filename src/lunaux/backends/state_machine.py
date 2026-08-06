from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, TypeAlias

from lunaux.backends.analysis import BasicBlock, ControlFlowAnalysis, NaturalLoop
from lunaux.backends.bytecode import LuauConstant, LuauProto
from lunaux.backends.opcodes import DecodedInstruction, get_jump_target

StateValue: TypeAlias = int | float
StateMachineKind = Literal["linear", "cycle"]

_IGNORED_OPS = frozenset({"NOP", "COVERAGE"})
_UNCONDITIONAL_JUMPS = frozenset({"JUMP", "JUMPBACK", "JUMPX"})
_CONTROL_FLOW_OPS = frozenset(
    {
        "JUMP",
        "JUMPBACK",
        "JUMPX",
        "JUMPIF",
        "JUMPIFNOT",
        "JUMPIFEQ",
        "JUMPIFLE",
        "JUMPIFLT",
        "JUMPIFNOTEQ",
        "JUMPIFNOTLE",
        "JUMPIFNOTLT",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "FORNPREP",
        "FORNLOOP",
        "FORGPREP",
        "FORGPREP_INEXT",
        "FORGPREP_NEXT",
        "FORGLOOP",
    }
)


@dataclass(frozen=True, slots=True)
class StateMachineCase:
    state: StateValue
    selector_pc: int
    block_start: int
    body_pcs: tuple[int, ...]
    transition_state: StateValue | None
    transition_pc: int | None
    terminal_pc: int | None


@dataclass(frozen=True, slots=True)
class StateMachineRegion:
    kind: StateMachineKind
    emit_pc: int
    dispatcher_header: int
    state_register: int
    initial_state: StateValue
    cases: tuple[StateMachineCase, ...]
    selector_pcs: frozenset[int]
    skipped_pcs: frozenset[int]
    exit_pc: int | None
    evidence: tuple[str, ...]

    @property
    def ordered_body_pcs(self) -> tuple[int, ...]:
        return tuple(pc for case in self.cases for pc in case.body_pcs)


@dataclass(frozen=True, slots=True)
class StateMachinePlan:
    regions: tuple[StateMachineRegion, ...]
    by_emit_pc: Mapping[int, StateMachineRegion]
    skipped_pcs: frozenset[int]
    structured_targets: frozenset[int]

    @classmethod
    def empty(cls) -> StateMachinePlan:
        return cls(
            regions=(),
            by_emit_pc=MappingProxyType({}),
            skipped_pcs=frozenset(),
            structured_targets=frozenset(),
        )

    def at(self, pc: int) -> StateMachineRegion | None:
        return self.by_emit_pc.get(pc)


@dataclass(frozen=True, slots=True)
class _Selector:
    pc: int
    register: int
    state: StateValue
    match_target: int
    miss_target: int


@dataclass(frozen=True, slots=True)
class _ParsedCase:
    case: StateMachineCase
    skipped_pcs: frozenset[int]
    exit_pc: int | None


def _constant(proto: LuauProto, index: int) -> LuauConstant | None:
    if 0 <= index < len(proto.constants):
        return proto.constants[index]
    return None


def _numeric_constant(proto: LuauProto, index: int) -> StateValue | None:
    constant = _constant(proto, index)
    if constant is None or constant.kind not in {"number", "integer"}:
        return None
    value = constant.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _constant_assignment(
    proto: LuauProto,
    instruction: DecodedInstruction,
    register: int,
) -> StateValue | None:
    if instruction.a != register:
        return None
    if instruction.name == "LOADN":
        return instruction.d
    if instruction.name == "LOADK":
        return _numeric_constant(proto, instruction.d)
    if instruction.name == "LOADKX":
        return _numeric_constant(proto, instruction.aux or 0)
    return None


def _branch_targets(
    analysis: ControlFlowAnalysis,
    block: BasicBlock,
) -> tuple[int | None, int | None]:
    terminator = block.terminator
    if terminator is None:
        return None, None
    target_pc = get_jump_target(terminator)
    taken = analysis.block_for_pc.get(target_pc) if target_pc is not None else None
    fallthrough = analysis.block_for_pc.get(terminator.pc + terminator.size)
    return taken, fallthrough


def _selector(
    proto: LuauProto,
    analysis: ControlFlowAnalysis,
    block_start: int,
) -> _Selector | None:
    block = analysis.block_by_start.get(block_start)
    if block is None or block.terminator is None:
        return None
    terminator = block.terminator
    if terminator.name != "JUMPXEQKN":
        return None
    if any(
        instruction is not terminator and instruction.name not in _IGNORED_OPS
        for instruction in block.instructions
    ):
        return None
    state = _numeric_constant(proto, (terminator.aux or 0) & 0xFFFFFF)
    if state is None:
        return None
    taken, fallthrough = _branch_targets(analysis, block)
    if taken is None or fallthrough is None:
        return None
    match_target = fallthrough if terminator.aux_not else taken
    miss_target = taken if terminator.aux_not else fallthrough
    return _Selector(
        pc=terminator.pc,
        register=terminator.a,
        state=state,
        match_target=match_target,
        miss_target=miss_target,
    )


def _trivial_jump_target(
    analysis: ControlFlowAnalysis,
    block_start: int,
) -> tuple[int | None, int | None]:
    block = analysis.block_by_start.get(block_start)
    if block is None or block.terminator is None:
        return None, None
    terminator = block.terminator
    if terminator.name not in _UNCONDITIONAL_JUMPS:
        return None, None
    if any(
        instruction is not terminator and instruction.name not in _IGNORED_OPS
        for instruction in block.instructions
    ):
        return None, None
    target_pc = get_jump_target(terminator)
    target = analysis.block_for_pc.get(target_pc) if target_pc is not None else None
    return target, terminator.pc


def _selector_chain(
    proto: LuauProto,
    analysis: ControlFlowAnalysis,
    header: int,
    loop_body: frozenset[int],
) -> tuple[tuple[_Selector, ...], frozenset[int]] | None:
    selectors: list[_Selector] = []
    skipped_fallback_pcs: set[int] = set()
    current = header
    visited: set[int] = set()
    register: int | None = None

    while current not in visited:
        visited.add(current)
        selector = _selector(proto, analysis, current)
        if selector is None:
            target, jump_pc = _trivial_jump_target(analysis, current)
            if target == header and jump_pc is not None:
                skipped_fallback_pcs.add(jump_pc)
                break
            return None
        if register is None:
            register = selector.register
        elif selector.register != register:
            return None
        if selector.match_target not in loop_body:
            return None
        if any(existing.state == selector.state for existing in selectors):
            return None
        selectors.append(selector)
        if selector.miss_target == header:
            break
        current = selector.miss_target
    else:
        return None

    if len(selectors) < 2:
        return None
    return tuple(selectors), frozenset(skipped_fallback_pcs)


def _initial_assignment(
    proto: LuauProto,
    analysis: ControlFlowAnalysis,
    loop_body: frozenset[int],
    header: int,
    state_register: int,
) -> tuple[DecodedInstruction, DecodedInstruction] | None:
    incoming = [
        predecessor
        for predecessor in analysis.block_by_start[header].predecessors
        if predecessor not in loop_body
    ]
    if len(incoming) != 1:
        return None
    block = analysis.block_by_start[incoming[0]]
    terminator = block.terminator
    if (
        terminator is None
        or terminator.name not in _UNCONDITIONAL_JUMPS
        or analysis.block_for_pc.get(get_jump_target(terminator) or -1) != header
    ):
        return None
    assignments = [
        instruction
        for instruction in block.instructions
        if _constant_assignment(proto, instruction, state_register) is not None
    ]
    if len(assignments) != 1:
        return None
    return assignments[0], terminator


def _parse_case(
    proto: LuauProto,
    analysis: ControlFlowAnalysis,
    selector: _Selector,
    dispatcher_header: int,
    loop_body: frozenset[int],
) -> _ParsedCase | None:
    block = analysis.block_by_start.get(selector.match_target)
    if block is None or block.start_pc == dispatcher_header or block.terminator is None:
        return None
    if block.start_pc not in loop_body:
        return None

    instructions = [
        instruction for instruction in block.instructions if instruction.name not in _IGNORED_OPS
    ]
    if not instructions:
        return None
    terminator = block.terminator
    for instruction in instructions[:-1]:
        if instruction.name in _CONTROL_FLOW_OPS:
            return None

    if terminator.name == "RETURN":
        return _ParsedCase(
            case=StateMachineCase(
                state=selector.state,
                selector_pc=selector.pc,
                block_start=block.start_pc,
                body_pcs=tuple(instruction.pc for instruction in instructions),
                transition_state=None,
                transition_pc=None,
                terminal_pc=terminator.pc,
            ),
            skipped_pcs=frozenset(),
            exit_pc=None,
        )

    if terminator.name not in _UNCONDITIONAL_JUMPS:
        return None
    target_pc = get_jump_target(terminator)
    target = analysis.block_for_pc.get(target_pc) if target_pc is not None else None
    if target is None:
        return None

    state_assignments = [
        instruction
        for instruction in instructions[:-1]
        if _constant_assignment(proto, instruction, selector.register) is not None
    ]
    if target == dispatcher_header:
        if len(state_assignments) != 1:
            return None
        transition_instruction = state_assignments[0]
        transition = _constant_assignment(
            proto,
            transition_instruction,
            selector.register,
        )
        if transition is None:
            return None
        body_pcs = tuple(
            instruction.pc
            for instruction in instructions[:-1]
            if instruction is not transition_instruction
        )
        return _ParsedCase(
            case=StateMachineCase(
                state=selector.state,
                selector_pc=selector.pc,
                block_start=block.start_pc,
                body_pcs=body_pcs,
                transition_state=transition,
                transition_pc=transition_instruction.pc,
                terminal_pc=None,
            ),
            skipped_pcs=frozenset({transition_instruction.pc, terminator.pc}),
            exit_pc=None,
        )

    if target not in loop_body and not state_assignments:
        return _ParsedCase(
            case=StateMachineCase(
                state=selector.state,
                selector_pc=selector.pc,
                block_start=block.start_pc,
                body_pcs=tuple(instruction.pc for instruction in instructions[:-1]),
                transition_state=None,
                transition_pc=None,
                terminal_pc=terminator.pc,
            ),
            skipped_pcs=frozenset({terminator.pc}),
            exit_pc=target,
        )
    return None


def _ordered_cases(
    initial_state: StateValue,
    cases: Mapping[StateValue, StateMachineCase],
) -> tuple[StateMachineKind, tuple[StateMachineCase, ...]] | None:
    ordered: list[StateMachineCase] = []
    visited: set[StateValue] = set()
    current = initial_state

    while current not in visited:
        case = cases.get(current)
        if case is None:
            return None
        visited.add(current)
        ordered.append(case)
        if case.transition_state is None:
            if len(visited) != len(cases):
                return None
            return "linear", tuple(ordered)
        current = case.transition_state

    if current != initial_state or len(visited) != len(cases):
        return None
    if any(case.terminal_pc is not None for case in ordered):
        return None
    return "cycle", tuple(ordered)


def _exclusive_state_register(
    analysis: ControlFlowAnalysis,
    loop_body: frozenset[int],
    register: int,
    selector_pcs: frozenset[int],
    transition_pcs: frozenset[int],
) -> bool:
    for block_start in loop_body:
        for instruction in analysis.block_by_start[block_start].instructions:
            access = analysis.register_accesses.get(instruction.pc)
            if access is None:
                continue
            if register in access.uses and instruction.pc not in selector_pcs:
                return False
            if register in access.definitions and instruction.pc not in transition_pcs:
                return False
    return True


def _group_loops(loops: Sequence[NaturalLoop]) -> tuple[NaturalLoop, ...]:
    by_header: dict[int, list[NaturalLoop]] = defaultdict(list)
    for loop in loops:
        by_header[loop.header].append(loop)
    result: list[NaturalLoop] = []
    for header, members in sorted(by_header.items()):
        body = frozenset(block for member in members for block in member.body)
        exits = frozenset(edge for member in members for edge in member.exits)
        result.append(
            NaturalLoop(
                header=header,
                latch=max(member.latch for member in members),
                body=body,
                exits=exits,
            )
        )
    return tuple(result)


def _recover_region(
    proto: LuauProto,
    analysis: ControlFlowAnalysis,
    loop: NaturalLoop,
) -> StateMachineRegion | None:
    chain = _selector_chain(proto, analysis, loop.header, loop.body)
    if chain is None:
        return None
    selectors, fallback_pcs = chain
    state_register = selectors[0].register
    initial = _initial_assignment(
        proto,
        analysis,
        loop.body,
        loop.header,
        state_register,
    )
    if initial is None:
        return None
    initial_instruction, initial_jump = initial
    initial_state = _constant_assignment(proto, initial_instruction, state_register)
    if initial_state is None:
        return None

    parsed_cases: list[_ParsedCase] = []
    case_blocks: set[int] = set()
    for selector in selectors:
        parsed = _parse_case(proto, analysis, selector, loop.header, loop.body)
        if parsed is None or parsed.case.block_start in case_blocks:
            return None
        parsed_cases.append(parsed)
        case_blocks.add(parsed.case.block_start)

    cases_by_state = {parsed.case.state: parsed.case for parsed in parsed_cases}
    ordered = _ordered_cases(initial_state, cases_by_state)
    if ordered is None:
        return None
    kind, ordered_cases = ordered

    selector_pcs = frozenset(selector.pc for selector in selectors)
    transition_pcs = frozenset(
        case.transition_pc
        for case in ordered_cases
        if case.transition_pc is not None
    )
    if not _exclusive_state_register(
        analysis,
        loop.body,
        state_register,
        selector_pcs,
        transition_pcs,
    ):
        return None

    exit_targets = {parsed.exit_pc for parsed in parsed_cases if parsed.exit_pc is not None}
    if len(exit_targets) > 1:
        return None
    exit_pc = next(iter(exit_targets)) if exit_targets else None
    if exit_pc is not None:
        machine_max_pc = max(
            instruction.pc
            for block_start in loop.body
            for instruction in analysis.block_by_start[block_start].instructions
        )
        if exit_pc <= machine_max_pc:
            return None

    body_pcs = {
        pc
        for parsed in parsed_cases
        for pc in parsed.case.body_pcs
    }
    skipped = {
        initial_instruction.pc,
        initial_jump.pc,
        *selector_pcs,
        *fallback_pcs,
        *body_pcs,
    }
    for parsed in parsed_cases:
        skipped.update(parsed.skipped_pcs)

    evidence = (
        f"state register R{state_register}",
        f"constant initial state {initial_state}",
        f"{len(ordered_cases)} constant selector cases",
        "exclusive constant state transitions",
        "deterministic simple cycle" if kind == "cycle" else "deterministic linear chain",
    )
    return StateMachineRegion(
        kind=kind,
        emit_pc=initial_instruction.pc,
        dispatcher_header=loop.header,
        state_register=state_register,
        initial_state=initial_state,
        cases=ordered_cases,
        selector_pcs=selector_pcs,
        skipped_pcs=frozenset(skipped),
        exit_pc=exit_pc,
        evidence=evidence,
    )


def recover_state_machines(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    analysis: ControlFlowAnalysis,
    *,
    enabled: bool = True,
) -> StateMachinePlan:
    del instructions
    if not enabled:
        return StateMachinePlan.empty()

    candidates = [
        region
        for loop in _group_loops(analysis.loops)
        if (region := _recover_region(proto, analysis, loop)) is not None
    ]
    claimed: set[int] = set()
    regions: list[StateMachineRegion] = []
    for region in sorted(candidates, key=lambda item: item.emit_pc):
        if claimed & region.skipped_pcs:
            continue
        claimed.update(region.skipped_pcs)
        regions.append(region)

    structured_targets = {
        target
        for region in regions
        for target in (region.dispatcher_header, region.exit_pc)
        if target is not None
    }
    return StateMachinePlan(
        regions=tuple(regions),
        by_emit_pc=MappingProxyType({region.emit_pc: region for region in regions}),
        skipped_pcs=frozenset(claimed),
        structured_targets=frozenset(structured_targets),
    )
