from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from lunaux.backends.advanced_loops import AdvancedLoopPlan
from lunaux.backends.analysis import BasicBlock, ControlFlowAnalysis
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.state_machine import StateMachinePlan
from lunaux.backends.structuring import StructuredRecoveryPlan

RegionKind = Literal[
    "sequence",
    "if",
    "if-else",
    "if-elseif-else",
    "early-exit-guard",
    "short-circuit",
    "phi-expression",
    "while",
    "repeat",
    "infinite-loop",
    "state-machine",
    "raw-fallback",
]

_CONDITIONAL_OPS = frozenset(
    {
        "JUMPIF", "JUMPIFNOT", "JUMPIFEQ", "JUMPIFLE", "JUMPIFLT",
        "JUMPIFNOTEQ", "JUMPIFNOTLE", "JUMPIFNOTLT", "JUMPXEQKNIL",
        "JUMPXEQKB", "JUMPXEQKN", "JUMPXEQKS",
    }
)
_IGNORED_OPS = frozenset({"NOP", "COVERAGE"})
_EXIT_OPS = frozenset({"RETURN", "BREAK", "CLOSEUPVALS"})


@dataclass(frozen=True, slots=True)
class StructuredRegion:
    entry: int
    exit: int | None
    kind: RegionKind
    blocks: frozenset[int]
    condition_pc: int | None = None
    children: tuple[int, ...] = ()
    fallthrough: int | None = None
    break_target: int | None = None
    continue_target: int | None = None
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalCFGPlan:
    regions: tuple[StructuredRegion, ...]
    by_entry: Mapping[int, tuple[StructuredRegion, ...]]
    structured: StructuredRecoveryPlan
    advanced_loops: AdvancedLoopPlan
    state_machines: StateMachinePlan
    structured_targets: frozenset[int]
    rejection_counts: Mapping[str, int]

    def at(self, pc: int) -> tuple[StructuredRegion, ...]:
        return self.by_entry.get(pc, ())


def _condition_only(block: BasicBlock | None) -> bool:
    if block is None or block.terminator is None:
        return False
    if block.terminator.name not in _CONDITIONAL_OPS:
        return False
    return all(
        instruction is block.terminator or instruction.name in _IGNORED_OPS
        for instruction in block.instructions
    )


def _terminates_early(block: BasicBlock | None) -> bool:
    if block is None or block.terminator is None:
        return False
    return block.terminator.name in _EXIT_OPS or not block.successors


def _strong_components(
    analysis: ControlFlowAnalysis,
) -> tuple[frozenset[int], ...]:
    index = 0
    indices: dict[int, int] = {}
    lowlinks: dict[int, int] = {}
    stack: list[int] = []
    on_stack: set[int] = set()
    components: list[frozenset[int]] = []

    def visit(node: int) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for successor in sorted(analysis.block_by_start[node].successors):
            if successor not in analysis.reachable:
                continue
            if successor not in indices:
                visit(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[successor])
        if lowlinks[node] != indices[node]:
            return
        members: set[int] = set()
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            members.add(member)
            if member == node:
                break
        components.append(frozenset(members))

    for block in sorted(analysis.reachable):
        if block not in indices:
            visit(block)
    return tuple(components)


def _irreducible_regions(
    analysis: ControlFlowAnalysis,
) -> tuple[StructuredRegion, ...]:
    result: list[StructuredRegion] = []
    for component in _strong_components(analysis):
        cyclic = len(component) > 1 or any(
            block in analysis.block_by_start[block].successors for block in component
        )
        if not cyclic:
            continue
        entries = {
            block
            for block in component
            if analysis.block_by_start[block].predecessors - component
        }
        if len(entries) <= 1:
            continue
        result.append(
            StructuredRegion(
                entry=min(entries),
                exit=None,
                kind="raw-fallback",
                blocks=component,
                children=tuple(sorted(entries)),
                evidence=("multi-entry strongly connected component",),
            )
        )
    return tuple(result)


def build_canonical_cfg_plan(
    analysis: ControlFlowAnalysis,
    instructions: Sequence[DecodedInstruction],
    structured: StructuredRecoveryPlan,
    advanced_loops: AdvancedLoopPlan,
    state_machines: StateMachinePlan,
) -> CanonicalCFGPlan:
    del instructions  # The decoded stream is accepted to keep this planner extensible.
    regions: list[StructuredRegion] = []
    rejections: Counter[str] = Counter()
    claimed_headers: set[int] = set()

    for machine in state_machines.regions:
        blocks = {
            machine.dispatcher_header,
            *(case.block_start for case in machine.cases),
        }
        regions.append(
            StructuredRegion(
                entry=machine.emit_pc,
                exit=machine.exit_pc,
                kind="state-machine",
                blocks=frozenset(blocks),
                evidence=machine.evidence,
            )
        )
        claimed_headers.add(machine.dispatcher_header)

    for loop in advanced_loops.regions:
        regions.append(
            StructuredRegion(
                entry=loop.header,
                exit=loop.close_pc,
                kind=(
                    "while"
                    if loop.kind == "while"
                    else "repeat"
                    if loop.kind == "repeat"
                    else "infinite-loop"
                ),
                blocks=loop.body_blocks,
                condition_pc=loop.condition_pc,
                break_target=loop.close_pc,
                continue_target=loop.continue_target,
                evidence=("single-entry natural loop", "exact backedge targets"),
            )
        )
        claimed_headers.add(loop.header)

    for chain in structured.boolean_chains:
        blocks = {
            analysis.block_for_pc[pc]
            for pc in chain.condition_pcs
            if pc in analysis.block_for_pc
        }
        blocks.update({chain.body_start, chain.false_start})
        regions.append(
            StructuredRegion(
                entry=chain.root_pc,
                exit=chain.join,
                kind="short-circuit",
                blocks=frozenset(blocks),
                condition_pc=chain.root_pc,
                fallthrough=chain.body_start,
                evidence=(f"CFG-proven {chain.operator} chain",),
            )
        )
        claimed_headers.add(analysis.block_for_pc.get(chain.root_pc, chain.root_pc))

    for phi in structured.phi_regions:
        header = analysis.block_for_pc.get(phi.condition_pc, phi.condition_pc)
        regions.append(
            StructuredRegion(
                entry=phi.condition_pc,
                exit=phi.join_pc,
                kind="phi-expression",
                blocks=frozenset(
                    {header, phi.then_block, phi.else_block, phi.join_pc}
                ),
                condition_pc=phi.condition_pc,
                evidence=("SSA phi diamond with pure branch definitions",),
            )
        )
        claimed_headers.add(header)

    branch_by_header = {branch.header: branch for branch in analysis.branches}
    for branch in sorted(analysis.branches, key=lambda item: item.header):
        if branch.header in claimed_headers:
            continue
        branch_block = analysis.block_by_start.get(branch.header)
        if not _condition_only(branch_block):
            rejections["branch-header-not-condition-only"] += 1
            continue
        nested = branch_by_header.get(branch.taken) or branch_by_header.get(
            branch.fallthrough
        )
        true_chain = (
            nested is not None
            and branch.join is not None
            and nested.join == branch.join
            and _condition_only(analysis.block_by_start.get(nested.header))
            and analysis.postdominates(branch.join, nested.header)
        )
        fallthrough_block = analysis.block_by_start.get(branch.fallthrough)
        taken_block = analysis.block_by_start.get(branch.taken)
        children: tuple[int, ...]
        if true_chain and nested is not None:
            kind: RegionKind = "if-elseif-else"
            children = (nested.header,)
        elif _terminates_early(fallthrough_block) or _terminates_early(taken_block):
            kind = "early-exit-guard"
            children = ()
        elif branch.join is not None:
            kind = "if-else"
            children = ()
        else:
            kind = "if"
            children = ()
        blocks = {branch.header, branch.fallthrough, branch.taken}
        if branch.join is not None:
            blocks.add(branch.join)
        regions.append(
            StructuredRegion(
                entry=branch.header,
                exit=branch.join,
                kind=kind,
                blocks=frozenset(blocks),
                condition_pc=(
                    branch_block.terminator.pc
                    if branch_block is not None and branch_block.terminator is not None
                    else None
                ),
                children=children,
                fallthrough=branch.fallthrough,
                evidence=("dominator/postdominator branch region",)
                + (("nested condition shares join",) if true_chain else ()),
            )
        )

    irreducible = _irreducible_regions(analysis)
    regions.extend(irreducible)
    if irreducible:
        rejections["irreducible-multi-entry-scc"] += len(irreducible)

    regions.sort(key=lambda item: (item.entry, item.exit or 2**31, item.kind))
    grouped: dict[int, list[StructuredRegion]] = {}
    for region in regions:
        grouped.setdefault(region.entry, []).append(region)
    targets = set(advanced_loops.structured_targets)
    targets.update(state_machines.structured_targets)
    for region in regions:
        targets.update(region.blocks)
        if region.exit is not None:
            targets.add(region.exit)
    return CanonicalCFGPlan(
        regions=tuple(regions),
        by_entry=MappingProxyType(
            {entry: tuple(items) for entry, items in sorted(grouped.items())}
        ),
        structured=structured,
        advanced_loops=advanced_loops,
        state_machines=state_machines,
        structured_targets=frozenset(targets),
        rejection_counts=MappingProxyType(dict(sorted(rejections.items()))),
    )
