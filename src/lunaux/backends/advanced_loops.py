from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from lunaux.backends.analysis import BasicBlock, ControlFlowAnalysis, NaturalLoop
from lunaux.backends.opcodes import DecodedInstruction, get_jump_target

LoopKind = Literal["while", "repeat", "infinite"]
LoopActionKind = Literal["break", "continue"]
LoopActionEdge = Literal["always", "taken", "fallthrough"]

_CONDITIONAL_OPS = frozenset(
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
_UNCONDITIONAL_JUMPS = frozenset({"JUMP", "JUMPBACK", "JUMPX"})
_FOR_OPS = frozenset(
    {
        "FORNPREP",
        "FORNLOOP",
        "FORGPREP",
        "FORGPREP_INEXT",
        "FORGPREP_NEXT",
        "FORGLOOP",
    }
)


@dataclass(frozen=True, slots=True)
class LoopJumpAction:
    pc: int
    kind: LoopActionKind
    edge: LoopActionEdge
    target: int
    loop_header: int


@dataclass(frozen=True, slots=True)
class AdvancedLoopRegion:
    kind: LoopKind
    header: int
    body_start: int
    close_pc: int
    condition_pc: int | None
    condition_block: int | None
    continue_target: int
    body_blocks: frozenset[int]
    latch_blocks: frozenset[int]
    backedge_pcs: frozenset[int]
    break_pcs: frozenset[int]
    continue_pcs: frozenset[int]
    depth: int

    @property
    def open_pc(self) -> int:
        return self.header


@dataclass(frozen=True, slots=True)
class AdvancedLoopPlan:
    regions: tuple[AdvancedLoopRegion, ...]
    by_open_pc: Mapping[int, AdvancedLoopRegion]
    repeat_by_condition_pc: Mapping[int, AdvancedLoopRegion]
    actions: Mapping[int, LoopJumpAction]
    skipped_pcs: frozenset[int]
    structured_targets: frozenset[int]

    @classmethod
    def empty(cls) -> AdvancedLoopPlan:
        return cls(
            regions=(),
            by_open_pc=MappingProxyType({}),
            repeat_by_condition_pc=MappingProxyType({}),
            actions=MappingProxyType({}),
            skipped_pcs=frozenset(),
            structured_targets=frozenset(),
        )

    def action_at(self, pc: int) -> LoopJumpAction | None:
        return self.actions.get(pc)


def _group_loops(loops: Sequence[NaturalLoop]) -> tuple[NaturalLoop, ...]:
    by_header: dict[int, list[NaturalLoop]] = defaultdict(list)
    for loop in loops:
        by_header[loop.header].append(loop)

    merged: list[NaturalLoop] = []
    for header, members in sorted(by_header.items()):
        body: set[int] = set()
        exits: set[tuple[int, int]] = set()
        for member in members:
            body.update(member.body)
            exits.update(member.exits)
        latch = max(member.latch for member in members)
        merged.append(
            NaturalLoop(
                header=header,
                latch=latch,
                body=frozenset(body),
                exits=frozenset(exits),
            )
        )
    return tuple(merged)


def _has_single_entry(
    analysis: ControlFlowAnalysis,
    body: frozenset[int],
    header: int,
) -> bool:
    for block_start in body:
        block = analysis.block_by_start[block_start]
        outside = block.predecessors - body
        if outside and block_start != header:
            return False
    return True


def _contains_for_loop(
    analysis: ControlFlowAnalysis,
    body: frozenset[int],
) -> bool:
    return any(
        instruction.name in _FOR_OPS
        for block_start in body
        for instruction in analysis.block_by_start[block_start].instructions
    )


def _branch_edges(
    analysis: ControlFlowAnalysis,
    block: BasicBlock,
) -> tuple[int | None, int | None]:
    terminator = block.terminator
    if terminator is None:
        return None, None
    target_pc = get_jump_target(terminator)
    taken = analysis.block_for_pc.get(target_pc) if target_pc is not None else None
    fallthrough_pc = terminator.pc + terminator.size
    fallthrough = analysis.block_for_pc.get(fallthrough_pc)
    return taken, fallthrough


def _edge_kind(
    analysis: ControlFlowAnalysis,
    source: int,
    target: int,
) -> LoopActionEdge | None:
    block = analysis.block_by_start[source]
    terminator = block.terminator
    if terminator is None:
        return None
    if terminator.name in _UNCONDITIONAL_JUMPS:
        return "always" if get_jump_target(terminator) == target else None
    if terminator.name not in _CONDITIONAL_OPS:
        return None
    taken, fallthrough = _branch_edges(analysis, block)
    if taken == target:
        return "taken"
    if fallthrough == target:
        return "fallthrough"
    return None


def _terminator_pc(
    analysis: ControlFlowAnalysis,
    block_start: int,
) -> int | None:
    terminator = analysis.block_by_start[block_start].terminator
    return terminator.pc if terminator is not None else None


def _latch_blocks(
    analysis: ControlFlowAnalysis,
    body: frozenset[int],
    header: int,
) -> frozenset[int]:
    return frozenset(
        source for source in body if header in analysis.block_by_start[source].successors
    )


def _canonical_exit(loop: NaturalLoop) -> int | None:
    targets = {target for _source, target in loop.exits}
    return next(iter(targets)) if len(targets) == 1 else None


def _depth(region: AdvancedLoopRegion, regions: Sequence[AdvancedLoopRegion]) -> int:
    return sum(
        1
        for outer in regions
        if outer is not region
        and region.body_blocks < outer.body_blocks
        and region.header in outer.body_blocks
    )


def _classify_region(
    analysis: ControlFlowAnalysis,
    loop: NaturalLoop,
) -> AdvancedLoopRegion | None:
    body = loop.body
    header = loop.header
    if not _has_single_entry(analysis, body, header):
        return None
    if _contains_for_loop(analysis, body):
        return None

    close_pc = _canonical_exit(loop)
    latch_blocks = _latch_blocks(analysis, body, header)
    if not latch_blocks:
        return None

    header_block = analysis.block_by_start[header]
    header_terminator = header_block.terminator
    condition_pc: int | None = None
    condition_block: int | None = None
    body_start = header
    continue_target = header
    kind: LoopKind

    if header_terminator is not None and header_terminator.name in _CONDITIONAL_OPS:
        taken, fallthrough = _branch_edges(analysis, header_block)
        inside = [target for target in (taken, fallthrough) if target in body and target != header]
        outside = [
            target for target in (taken, fallthrough) if target is not None and target not in body
        ]
        if len(inside) == 1 and len(outside) == 1:
            if close_pc is None or close_pc != outside[0]:
                return None
            kind = "while"
            body_start = inside[0]
            condition_pc = header_terminator.pc
            condition_block = header
        else:
            return None
    else:
        conditional_latches = []
        for latch_start in latch_blocks:
            terminator = analysis.block_by_start[latch_start].terminator
            if (
                terminator is not None
                and terminator.name in _CONDITIONAL_OPS
                and get_jump_target(terminator) == header
            ):
                conditional_latches.append(latch_start)
        if len(conditional_latches) == 1:
            latch_start = conditional_latches[0]
            latch = analysis.block_by_start[latch_start]
            _taken, fallthrough = _branch_edges(analysis, latch)
            if fallthrough is None or fallthrough in body:
                return None
            if close_pc is None or close_pc != fallthrough:
                return None
            kind = "repeat"
            condition_block = latch_start
            condition_pc = latch.terminator.pc if latch.terminator is not None else None
            continue_target = latch_start
        else:
            kind = "infinite"
            if close_pc is None:
                close_pc = max(analysis.block_by_start[start].end_pc for start in body)

    if close_pc is None:
        return None

    backedge_pcs: set[int] = set()
    break_pcs: set[int] = set()
    continue_pcs: set[int] = set()

    for source in body:
        block = analysis.block_by_start[source]
        terminator = block.terminator
        if terminator is None:
            continue
        for target in block.successors:
            if target == continue_target:
                edge = _edge_kind(analysis, source, target)
                if edge == "always" and source in latch_blocks:
                    backedge_pcs.add(terminator.pc)
                elif source != condition_block:
                    continue_pcs.add(terminator.pc)
            elif target == close_pc:
                if source not in {header, condition_block}:
                    break_pcs.add(terminator.pc)

    if kind == "repeat" and condition_pc is not None:
        backedge_pcs.add(condition_pc)
    if kind == "while" and condition_pc is not None:
        backedge_pcs.add(condition_pc)

    return AdvancedLoopRegion(
        kind=kind,
        header=header,
        body_start=body_start,
        close_pc=close_pc,
        condition_pc=condition_pc,
        condition_block=condition_block,
        continue_target=continue_target,
        body_blocks=body,
        latch_blocks=latch_blocks,
        backedge_pcs=frozenset(backedge_pcs),
        break_pcs=frozenset(break_pcs),
        continue_pcs=frozenset(continue_pcs),
        depth=0,
    )


def _action_for_pc(
    analysis: ControlFlowAnalysis,
    region: AdvancedLoopRegion,
    pc: int,
    kind: LoopActionKind,
    target: int,
) -> LoopJumpAction | None:
    block = analysis.block_at(pc)
    if block is None or block.terminator is None or block.terminator.pc != pc:
        return None
    edge = _edge_kind(analysis, block.start_pc, target)
    if edge is None:
        return None
    return LoopJumpAction(
        pc=pc,
        kind=kind,
        edge=edge,
        target=target,
        loop_header=region.header,
    )


def analyze_advanced_loops(
    analysis: ControlFlowAnalysis,
    instructions: Sequence[DecodedInstruction],
    *,
    enabled: bool = True,
) -> AdvancedLoopPlan:
    del instructions
    if not enabled:
        return AdvancedLoopPlan.empty()

    provisional = [
        region
        for loop in _group_loops(analysis.loops)
        if (region := _classify_region(analysis, loop)) is not None
    ]
    regions = tuple(
        sorted(
            (
                AdvancedLoopRegion(
                    kind=region.kind,
                    header=region.header,
                    body_start=region.body_start,
                    close_pc=region.close_pc,
                    condition_pc=region.condition_pc,
                    condition_block=region.condition_block,
                    continue_target=region.continue_target,
                    body_blocks=region.body_blocks,
                    latch_blocks=region.latch_blocks,
                    backedge_pcs=region.backedge_pcs,
                    break_pcs=region.break_pcs,
                    continue_pcs=region.continue_pcs,
                    depth=_depth(region, provisional),
                )
                for region in provisional
            ),
            key=lambda item: (item.header, -item.depth, item.close_pc),
        )
    )

    actions: dict[int, LoopJumpAction] = {}
    skipped_pcs: set[int] = set()
    structured_targets: set[int] = set()
    by_open_pc: dict[int, AdvancedLoopRegion] = {}
    repeat_by_condition_pc: dict[int, AdvancedLoopRegion] = {}

    for region in sorted(regions, key=lambda item: item.depth, reverse=True):
        if region.header in by_open_pc:
            continue
        by_open_pc[region.header] = region
        structured_targets.update({region.header, region.close_pc, region.continue_target})
        skipped_pcs.update(region.backedge_pcs)
        if region.kind == "repeat" and region.condition_pc is not None:
            repeat_by_condition_pc[region.condition_pc] = region
        for pc in region.break_pcs:
            action = _action_for_pc(analysis, region, pc, "break", region.close_pc)
            if action is not None:
                actions.setdefault(pc, action)
        for pc in region.continue_pcs:
            action = _action_for_pc(
                analysis,
                region,
                pc,
                "continue",
                region.continue_target,
            )
            if action is not None:
                actions.setdefault(pc, action)

    skipped_pcs.difference_update(actions)
    return AdvancedLoopPlan(
        regions=regions,
        by_open_pc=MappingProxyType(by_open_pc),
        repeat_by_condition_pc=MappingProxyType(repeat_by_condition_pc),
        actions=MappingProxyType(actions),
        skipped_pcs=frozenset(skipped_pcs),
        structured_targets=frozenset(structured_targets),
    )
