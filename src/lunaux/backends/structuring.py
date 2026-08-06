from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final, Literal

from lunaux.backends.analysis import (
    BasicBlock,
    BranchRegion,
    ControlFlowAnalysis,
    register_access,
)
from lunaux.backends.opcodes import DecodedInstruction, get_jump_target
from lunaux.backends.ssa import SSAPhi, SSAProgram, SSAValue

_CONDITIONAL_OPS: Final[frozenset[str]] = frozenset(
    {
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
    }
)
_IGNORED_OPS: Final[frozenset[str]] = frozenset({"NOP", "COVERAGE"})
_UNCONDITIONAL_JUMPS: Final[frozenset[str]] = frozenset({"JUMP", "JUMPBACK", "JUMPX"})
_PURE_PHI_VALUE_OPS: Final[frozenset[str]] = frozenset(
    {
        "LOADNIL",
        "LOADB",
        "LOADN",
        "LOADK",
        "LOADKX",
        "MOVE",
        "GETGLOBAL",
        "GETIMPORT",
        "GETUPVAL",
        "GETTABLE",
        "GETTABLEKS",
        "GETUDATAKS",
        "GETTABLEN",
        "ADD",
        "SUB",
        "MUL",
        "DIV",
        "MOD",
        "POW",
        "IDIV",
        "AND",
        "OR",
        "ADDK",
        "SUBK",
        "MULK",
        "DIVK",
        "MODK",
        "POWK",
        "IDIVK",
        "ANDK",
        "ORK",
        "SUBRK",
        "DIVRK",
        "NOT",
        "MINUS",
        "LENGTH",
        "CONCAT",
    }
)


@dataclass(frozen=True, slots=True)
class PhiIfAssignment:
    result: SSAValue
    then_value: SSAValue
    else_value: SSAValue


@dataclass(frozen=True, slots=True)
class PhiIfRegion:
    condition_pc: int
    condition_pcs: tuple[int, ...]
    condition_operator: Literal["and", "or"] | None
    join_pc: int
    then_block: int
    else_block: int
    assignments: tuple[PhiIfAssignment, ...]
    captured_values: frozenset[SSAValue]
    skipped_pcs: frozenset[int]


@dataclass(frozen=True, slots=True)
class BooleanChain:
    root_pc: int
    condition_pcs: tuple[int, ...]
    operator: Literal["and", "or"]
    body_start: int
    false_start: int
    join: int
    skipped_pcs: frozenset[int]

    @property
    def has_else(self) -> bool:
        return self.false_start != self.join


@dataclass(frozen=True, slots=True)
class StructuredRecoveryPlan:
    phi_regions: tuple[PhiIfRegion, ...]
    phi_by_header: Mapping[int, PhiIfRegion]
    phi_by_join: Mapping[int, tuple[PhiIfRegion, ...]]
    captured_phi_values: frozenset[SSAValue]
    boolean_chains: tuple[BooleanChain, ...]
    boolean_by_root: Mapping[int, BooleanChain]
    skipped_condition_pcs: frozenset[int]
    skipped_structuring_pcs: frozenset[int]


def _condition_only(block: BasicBlock) -> bool:
    terminator = block.terminator
    if terminator is None or terminator.name not in _CONDITIONAL_OPS:
        return False
    return all(
        instruction is terminator or instruction.name in _IGNORED_OPS
        for instruction in block.instructions
    )


def _side_definitions(
    block: BasicBlock,
    join: int,
) -> tuple[DecodedInstruction, ...] | None:
    definitions: list[DecodedInstruction] = []
    for instruction in block.instructions:
        if instruction.name in _IGNORED_OPS:
            continue
        if instruction.name in _UNCONDITIONAL_JUMPS:
            if instruction is not block.terminator or get_jump_target(instruction) != join:
                return None
            continue
        if instruction.name not in _PURE_PHI_VALUE_OPS:
            return None
        access = register_access(instruction)
        if len(access.definitions) != 1:
            return None
        if instruction.name == "LOADB" and instruction.c:
            return None
        definitions.append(instruction)
    return tuple(definitions)


def _definitions_by_value(
    program: SSAProgram,
    instructions: tuple[DecodedInstruction, ...],
) -> dict[SSAValue, DecodedInstruction] | None:
    result: dict[SSAValue, DecodedInstruction] = {}
    for instruction in instructions:
        definitions = register_access(instruction).definitions
        if len(definitions) != 1:
            return None
        register = next(iter(definitions))
        value = program.value_defined_at(instruction.pc, register)
        if value is None:
            return None
        result[value] = instruction
    return result


def _phi_regions(program: SSAProgram) -> tuple[PhiIfRegion, ...]:
    analysis = program.analysis
    phis_by_block: dict[int, list[SSAPhi]] = defaultdict(list)
    for phi in program.phis:
        phis_by_block[phi.block].append(phi)

    regions: list[PhiIfRegion] = []
    for branch in analysis.branches:
        join = branch.join
        header = analysis.block_by_start.get(branch.header)
        then_block = analysis.block_by_start.get(branch.fallthrough)
        else_block = analysis.block_by_start.get(branch.taken)
        join_block = analysis.block_by_start.get(join) if join is not None else None
        if (
            join is None
            or header is None
            or then_block is None
            or else_block is None
            or join_block is None
            or header.terminator is None
            or header.terminator.name not in _CONDITIONAL_OPS
        ):
            continue
        if branch.fallthrough not in join_block.predecessors:
            continue
        if branch.taken not in join_block.predecessors:
            continue

        then_definitions = _side_definitions(then_block, join)
        else_definitions = _side_definitions(else_block, join)
        if then_definitions is None or else_definitions is None:
            continue
        then_by_value = _definitions_by_value(program, then_definitions)
        else_by_value = _definitions_by_value(program, else_definitions)
        if then_by_value is None or else_by_value is None:
            continue

        assignments: list[PhiIfAssignment] = []
        captured: set[SSAValue] = set()
        used_definition_pcs: set[int] = set()
        for phi in phis_by_block.get(join, []):
            then_value = phi.operands.get(branch.fallthrough)
            else_value = phi.operands.get(branch.taken)
            if then_value is None or else_value is None:
                continue
            then_instruction = then_by_value.get(then_value)
            else_instruction = else_by_value.get(else_value)
            if then_instruction is None or else_instruction is None:
                continue
            assignments.append(
                PhiIfAssignment(
                    result=phi.result,
                    then_value=then_value,
                    else_value=else_value,
                )
            )
            captured.update({then_value, else_value})
            used_definition_pcs.update({then_instruction.pc, else_instruction.pc})

        all_definition_pcs = {
            instruction.pc for instruction in (*then_definitions, *else_definitions)
        }
        if not assignments or used_definition_pcs != all_definition_pcs:
            continue

        skipped_pcs = set(all_definition_pcs)
        for block in (then_block, else_block):
            terminator = block.terminator
            if (
                terminator is not None
                and terminator.name in _UNCONDITIONAL_JUMPS
                and get_jump_target(terminator) == join
            ):
                skipped_pcs.add(terminator.pc)
        condition_pc = header.terminator.pc
        regions.append(
            PhiIfRegion(
                condition_pc=condition_pc,
                condition_pcs=(condition_pc,),
                condition_operator=None,
                join_pc=join,
                then_block=branch.fallthrough,
                else_block=branch.taken,
                assignments=tuple(assignments),
                captured_values=frozenset(captured),
                skipped_pcs=frozenset(skipped_pcs),
            )
        )
    return tuple(sorted(regions, key=lambda item: (item.condition_pc, item.join_pc)))


def _follow_trivial_jump(
    analysis: ControlFlowAnalysis,
    block_start: int,
) -> tuple[int, frozenset[int]]:
    block = analysis.block_by_start.get(block_start)
    if block is None or block.terminator is None:
        return block_start, frozenset()
    terminator = block.terminator
    if terminator.name not in _UNCONDITIONAL_JUMPS:
        return block_start, frozenset()
    if not all(
        instruction is terminator or instruction.name in _IGNORED_OPS
        for instruction in block.instructions
    ):
        return block_start, frozenset()
    target = get_jump_target(terminator)
    if target is None or target not in analysis.block_by_start:
        return block_start, frozenset()
    return target, frozenset({terminator.pc})


def _condition_pcs(
    analysis: ControlFlowAnalysis,
    conditions: list[BranchRegion],
) -> tuple[int, ...] | None:
    result: list[int] = []
    for condition in conditions:
        terminator = analysis.block_by_start[condition.header].terminator
        if terminator is None:
            return None
        result.append(terminator.pc)
    return tuple(result)


def _and_chain(
    analysis: ControlFlowAnalysis,
    root: BranchRegion,
    branch_by_header: Mapping[int, BranchRegion],
) -> BooleanChain | None:
    conditions = [root]
    failure = root.taken
    current = root
    visited_headers = {root.header}
    while True:
        candidate = branch_by_header.get(current.fallthrough)
        if candidate is None or candidate.header in visited_headers or candidate.taken != failure:
            break
        visited_headers.add(candidate.header)
        block = analysis.block_by_start[candidate.header]
        reachable_predecessors = block.predecessors & analysis.reachable
        if len(reachable_predecessors) != 1 or not _condition_only(block):
            break
        conditions.append(candidate)
        current = candidate
    if len(conditions) < 2:
        return None
    condition_pcs = _condition_pcs(analysis, conditions)
    if condition_pcs is None:
        return None
    body_start = current.fallthrough
    join = root.join if root.join is not None else failure
    if body_start <= max(condition_pcs):
        return None
    return BooleanChain(
        root_pc=condition_pcs[0],
        condition_pcs=condition_pcs,
        operator="and",
        body_start=body_start,
        false_start=failure,
        join=join,
        skipped_pcs=frozenset(condition_pcs[1:]),
    )


def _or_chain(
    analysis: ControlFlowAnalysis,
    root: BranchRegion,
    branch_by_header: Mapping[int, BranchRegion],
) -> BooleanChain | None:
    success, skipped = _follow_trivial_jump(analysis, root.fallthrough)
    conditions = [root]
    skipped_pcs = set(skipped)
    current = root
    visited_headers = {root.header}
    while True:
        candidate = branch_by_header.get(current.taken)
        if candidate is None or candidate.header in visited_headers:
            break
        visited_headers.add(candidate.header)
        block = analysis.block_by_start[candidate.header]
        reachable_predecessors = block.predecessors & analysis.reachable
        if len(reachable_predecessors) != 1 or not _condition_only(block):
            break
        candidate_success, candidate_skipped = _follow_trivial_jump(
            analysis,
            candidate.fallthrough,
        )
        if candidate_success != success:
            break
        conditions.append(candidate)
        skipped_pcs.update(candidate_skipped)
        current = candidate
    if len(conditions) < 2:
        return None
    condition_pcs = _condition_pcs(analysis, conditions)
    if condition_pcs is None:
        return None
    if success <= max(condition_pcs):
        return None
    failure = current.taken
    join = root.join if root.join is not None else failure
    skipped_pcs.update(condition_pcs[1:])
    return BooleanChain(
        root_pc=condition_pcs[0],
        condition_pcs=condition_pcs,
        operator="or",
        body_start=success,
        false_start=failure,
        join=join,
        skipped_pcs=frozenset(skipped_pcs),
    )


def _boolean_chains(
    analysis: ControlFlowAnalysis,
) -> tuple[BooleanChain, ...]:
    branch_by_header = {branch.header: branch for branch in analysis.branches}
    chains: list[BooleanChain] = []
    claimed: set[int] = set()
    for root in analysis.branches:
        block = analysis.block_by_start[root.header]
        terminator = block.terminator
        if terminator is None or terminator.pc in claimed:
            continue
        chain = _and_chain(analysis, root, branch_by_header)
        if chain is None:
            chain = _or_chain(analysis, root, branch_by_header)
        if chain is None or any(pc in claimed for pc in chain.condition_pcs):
            continue
        chains.append(chain)
        claimed.update(chain.condition_pcs)
    return tuple(sorted(chains, key=lambda item: item.root_pc))


def _merge_phi_condition_chains(
    phi_regions: tuple[PhiIfRegion, ...],
    boolean_chains: tuple[BooleanChain, ...],
) -> tuple[tuple[PhiIfRegion, ...], tuple[BooleanChain, ...]]:
    consumed_roots: set[int] = set()
    merged_regions: list[PhiIfRegion] = []
    for region in phi_regions:
        matching = next(
            (
                chain
                for chain in boolean_chains
                if chain.condition_pcs[-1] == region.condition_pc
                and chain.body_start == region.then_block
                and chain.false_start == region.else_block
                and chain.join == region.join_pc
            ),
            None,
        )
        if matching is None:
            merged_regions.append(region)
            continue
        consumed_roots.add(matching.root_pc)
        merged_regions.append(
            replace(
                region,
                condition_pc=matching.root_pc,
                condition_pcs=matching.condition_pcs,
                condition_operator=matching.operator,
                skipped_pcs=region.skipped_pcs | matching.skipped_pcs,
            )
        )
    remaining_chains = tuple(
        chain for chain in boolean_chains if chain.root_pc not in consumed_roots
    )
    return tuple(merged_regions), remaining_chains


def build_structured_recovery(program: SSAProgram) -> StructuredRecoveryPlan:
    phi_regions = _phi_regions(program)
    boolean_chains = _boolean_chains(program.analysis)
    phi_regions, boolean_chains = _merge_phi_condition_chains(
        phi_regions,
        boolean_chains,
    )

    phi_by_join: dict[int, list[PhiIfRegion]] = defaultdict(list)
    captured_values: set[SSAValue] = set()
    skipped_structuring_pcs: set[int] = set()
    for region in phi_regions:
        phi_by_join[region.join_pc].append(region)
        captured_values.update(region.captured_values)
        skipped_structuring_pcs.update(region.skipped_pcs)

    skipped_condition_pcs: set[int] = set()
    for chain in boolean_chains:
        skipped_condition_pcs.update(chain.condition_pcs[1:])
        skipped_structuring_pcs.update(chain.skipped_pcs)

    return StructuredRecoveryPlan(
        phi_regions=phi_regions,
        phi_by_header=MappingProxyType({region.condition_pc: region for region in phi_regions}),
        phi_by_join=MappingProxyType(
            {
                join: tuple(sorted(regions, key=lambda item: item.condition_pc))
                for join, regions in sorted(phi_by_join.items())
            }
        ),
        captured_phi_values=frozenset(captured_values),
        boolean_chains=boolean_chains,
        boolean_by_root=MappingProxyType({chain.root_pc: chain for chain in boolean_chains}),
        skipped_condition_pcs=frozenset(skipped_condition_pcs),
        skipped_structuring_pcs=frozenset(skipped_structuring_pcs),
    )
