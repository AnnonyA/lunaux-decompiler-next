from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lunaux.backends.opcodes import DecodedInstruction, get_jump_target, is_fallthrough

_TERMINATOR_NAMES = frozenset({"RETURN", "JUMP", "JUMPBACK", "JUMPX"})


@dataclass(frozen=True, slots=True)
class RegisterAccess:
    definitions: frozenset[int]
    uses: frozenset[int]


@dataclass(frozen=True, slots=True)
class BasicBlock:
    start_pc: int
    end_pc: int
    instructions: tuple[DecodedInstruction, ...]
    predecessors: frozenset[int]
    successors: frozenset[int]

    @property
    def terminator(self) -> DecodedInstruction | None:
        return self.instructions[-1] if self.instructions else None


@dataclass(frozen=True, slots=True)
class NaturalLoop:
    header: int
    latch: int
    body: frozenset[int]
    exits: frozenset[tuple[int, int]]


@dataclass(frozen=True, slots=True)
class BranchRegion:
    header: int
    fallthrough: int
    taken: int
    join: int | None


@dataclass(frozen=True, slots=True)
class PhiNode:
    block: int
    register: int
    predecessors: frozenset[int]


@dataclass(frozen=True, slots=True)
class DefUseChain:
    reaching_definitions: Mapping[tuple[int, int], frozenset[int]]
    definition_uses: Mapping[tuple[int, int], frozenset[int]]


@dataclass(frozen=True, slots=True)
class ControlFlowAnalysis:
    entry: int
    blocks: tuple[BasicBlock, ...]
    block_by_start: Mapping[int, BasicBlock]
    block_for_pc: Mapping[int, int]
    reachable: frozenset[int]
    dominators: Mapping[int, frozenset[int]]
    immediate_dominators: Mapping[int, int | None]
    postdominators: Mapping[int, frozenset[int]]
    immediate_postdominators: Mapping[int, int | None]
    dominance_frontiers: Mapping[int, frozenset[int]]
    branches: tuple[BranchRegion, ...]
    loops: tuple[NaturalLoop, ...]
    phi_nodes: tuple[PhiNode, ...]
    register_accesses: Mapping[int, RegisterAccess]
    live_in: Mapping[int, frozenset[int]]
    live_out: Mapping[int, frozenset[int]]
    def_use: DefUseChain

    def block_at(self, pc: int) -> BasicBlock | None:
        start = self.block_for_pc.get(pc)
        return self.block_by_start.get(start) if start is not None else None

    def dominates(self, dominator: int, block: int) -> bool:
        return dominator in self.dominators.get(block, frozenset())

    def postdominates(self, postdominator: int, block: int) -> bool:
        return postdominator in self.postdominators.get(block, frozenset())


def _freeze_map(values: dict[int, set[int]]) -> Mapping[int, frozenset[int]]:
    return MappingProxyType({key: frozenset(value) for key, value in values.items()})


def _instruction_successors(
    instruction: DecodedInstruction,
    valid_pcs: frozenset[int],
    code_size: int,
) -> set[int]:
    successors: set[int] = set()
    target = get_jump_target(instruction)
    if target is not None and target in valid_pcs:
        successors.add(target)
    next_pc = instruction.pc + instruction.size
    if (
        next_pc < code_size
        and next_pc in valid_pcs
        and (instruction.name not in _TERMINATOR_NAMES)
        and not (instruction.name == "LOADB" and instruction.c)
        and (target is None or is_fallthrough(instruction.opcode))
    ):
        successors.add(next_pc)
    return successors


def _leaders(
    instructions: tuple[DecodedInstruction, ...],
    code_size: int,
) -> tuple[int, ...]:
    if not instructions:
        return ()
    valid_pcs = frozenset(item.pc for item in instructions)
    leaders = {instructions[0].pc}
    for instruction in instructions:
        target = get_jump_target(instruction)
        if target is not None and target in valid_pcs:
            leaders.add(target)
        next_pc = instruction.pc + instruction.size
        if (
            next_pc < code_size
            and next_pc in valid_pcs
            and (target is not None or instruction.name in _TERMINATOR_NAMES)
        ):
            leaders.add(next_pc)
    return tuple(sorted(leaders))


def _build_blocks(
    instructions: tuple[DecodedInstruction, ...],
    code_size: int,
) -> tuple[tuple[BasicBlock, ...], dict[int, int]]:
    leaders = _leaders(instructions, code_size)
    if not leaders:
        return (), {}
    instruction_by_pc = {item.pc: item for item in instructions}
    valid_pcs = frozenset(instruction_by_pc)
    block_ranges: list[tuple[int, int]] = []
    for index, start in enumerate(leaders):
        end = leaders[index + 1] if index + 1 < len(leaders) else code_size
        block_ranges.append((start, end))

    temporary: dict[int, tuple[int, tuple[DecodedInstruction, ...]]] = {}
    block_for_pc: dict[int, int] = {}
    for start, end in block_ranges:
        block_instructions = tuple(
            instruction_by_pc[pc] for pc in sorted(pc for pc in valid_pcs if start <= pc < end)
        )
        if not block_instructions:
            continue
        temporary[start] = (end, block_instructions)
        for instruction in block_instructions:
            block_for_pc[instruction.pc] = start

    successor_map: dict[int, set[int]] = {start: set() for start in temporary}
    predecessor_map: dict[int, set[int]] = {start: set() for start in temporary}
    for start, (_end, block_instructions) in temporary.items():
        terminator = block_instructions[-1]
        for successor_pc in _instruction_successors(terminator, valid_pcs, code_size):
            successor_start = block_for_pc.get(successor_pc)
            if successor_start is None:
                continue
            successor_map[start].add(successor_start)
            predecessor_map[successor_start].add(start)

    blocks = tuple(
        BasicBlock(
            start_pc=start,
            end_pc=end,
            instructions=block_instructions,
            predecessors=frozenset(predecessor_map[start]),
            successors=frozenset(successor_map[start]),
        )
        for start, (end, block_instructions) in sorted(temporary.items())
    )
    return blocks, block_for_pc


def _reachable(entry: int, successors: Mapping[int, frozenset[int]]) -> frozenset[int]:
    seen: set[int] = set()
    pending = [entry]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(successors.get(current, frozenset()) - seen)
    return frozenset(seen)


def _dominators(
    entry: int,
    nodes: frozenset[int],
    predecessors: Mapping[int, frozenset[int]],
) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {
        node: ({node} if node == entry else set(nodes)) for node in nodes
    }
    changed = True
    while changed:
        changed = False
        for node in sorted(nodes):
            if node == entry:
                continue
            incoming = [
                result[pred] for pred in predecessors.get(node, frozenset()) if pred in nodes
            ]
            updated = {node}
            if incoming:
                updated.update(set.intersection(*incoming))
            if updated != result[node]:
                result[node] = updated
                changed = True
    return result


def _postdominators(
    nodes: frozenset[int],
    successors: Mapping[int, frozenset[int]],
) -> dict[int, set[int]]:
    exits = {node for node in nodes if not (successors.get(node, frozenset()) & nodes)}
    if not exits:
        return {node: {node} for node in nodes}
    result: dict[int, set[int]] = {
        node: ({node} if node in exits else set(nodes)) for node in nodes
    }
    changed = True
    while changed:
        changed = False
        for node in sorted(nodes, reverse=True):
            if node in exits:
                continue
            outgoing = [result[succ] for succ in successors.get(node, frozenset()) if succ in nodes]
            updated = {node}
            if outgoing:
                updated.update(set.intersection(*outgoing))
            if updated != result[node]:
                result[node] = updated
                changed = True
    return result


def _immediate_relations(
    relations: Mapping[int, set[int]],
    root: int | None,
) -> dict[int, int | None]:
    result: dict[int, int | None] = {}
    for node, related in relations.items():
        if root is not None and node == root:
            result[node] = None
            continue
        strict = related - {node}
        result[node] = max(strict, key=lambda item: len(relations[item]), default=None)
    return result


def _dominance_frontiers(
    nodes: frozenset[int],
    predecessors: Mapping[int, frozenset[int]],
    immediate_dominators: Mapping[int, int | None],
) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {node: set() for node in nodes}
    for node in nodes:
        incoming = predecessors.get(node, frozenset()) & nodes
        if len(incoming) < 2:
            continue
        stop = immediate_dominators.get(node)
        for predecessor in incoming:
            runner: int | None = predecessor
            visited: set[int] = set()
            while runner is not None and runner != stop and runner not in visited:
                visited.add(runner)
                result[runner].add(node)
                runner = immediate_dominators.get(runner)
    return result


def _natural_loops(
    nodes: frozenset[int],
    predecessors: Mapping[int, frozenset[int]],
    successors: Mapping[int, frozenset[int]],
    dominators: Mapping[int, set[int]],
) -> tuple[NaturalLoop, ...]:
    loops: list[NaturalLoop] = []
    for latch in sorted(nodes):
        for header in sorted(successors.get(latch, frozenset()) & nodes):
            if header not in dominators[latch]:
                continue
            body = {header, latch}
            pending = [latch]
            while pending:
                current = pending.pop()
                for predecessor in predecessors.get(current, frozenset()) & nodes:
                    if predecessor not in body:
                        body.add(predecessor)
                        pending.append(predecessor)
            exits = {
                (source, target)
                for source in body
                for target in successors.get(source, frozenset())
                if target not in body
            }
            loops.append(
                NaturalLoop(
                    header=header,
                    latch=latch,
                    body=frozenset(body),
                    exits=frozenset(exits),
                )
            )
    return tuple(sorted(loops, key=lambda item: (item.header, item.latch)))


def _branch_regions(
    blocks: tuple[BasicBlock, ...],
    block_for_pc: Mapping[int, int],
    immediate_postdominators: Mapping[int, int | None],
) -> tuple[BranchRegion, ...]:
    regions: list[BranchRegion] = []
    for block in blocks:
        terminator = block.terminator
        if terminator is None or len(block.successors) != 2:
            continue
        target_pc = get_jump_target(terminator)
        next_pc = terminator.pc + terminator.size
        taken = block_for_pc.get(target_pc) if target_pc is not None else None
        fallthrough = block_for_pc.get(next_pc)
        if taken is None or fallthrough is None or taken == fallthrough:
            continue
        regions.append(
            BranchRegion(
                header=block.start_pc,
                fallthrough=fallthrough,
                taken=taken,
                join=immediate_postdominators.get(block.start_pc),
            )
        )
    return tuple(regions)


def _phi_nodes(
    blocks: tuple[BasicBlock, ...],
    accesses: Mapping[int, RegisterAccess],
    dominance_frontiers: Mapping[int, set[int]],
    live_in: Mapping[int, set[int]],
    live_out: Mapping[int, set[int]],
) -> tuple[PhiNode, ...]:
    definition_blocks: dict[int, set[int]] = defaultdict(set)
    by_start = {block.start_pc: block for block in blocks}
    for block in blocks:
        for instruction in block.instructions:
            for register in accesses[instruction.pc].definitions:
                definition_blocks[register].add(block.start_pc)

    nodes: list[PhiNode] = []
    for register, starts in sorted(definition_blocks.items()):
        worklist = list(starts)
        placed: set[int] = set()
        while worklist:
            current = worklist.pop()
            for frontier in dominance_frontiers.get(current, set()):
                if frontier in placed or register not in live_in.get(frontier, set()):
                    continue
                placed.add(frontier)
                predecessors = frozenset(
                    predecessor
                    for predecessor in by_start[frontier].predecessors
                    if register in live_out.get(predecessor, set())
                )
                nodes.append(
                    PhiNode(
                        block=frontier,
                        register=register,
                        predecessors=predecessors,
                    )
                )
                if frontier not in starts:
                    worklist.append(frontier)
    return tuple(sorted(nodes, key=lambda item: (item.block, item.register)))


def _range(start: int, count: int) -> frozenset[int]:
    return frozenset(range(start, start + max(0, count)))


def register_access(instruction: DecodedInstruction) -> RegisterAccess:
    name = instruction.name
    definitions: frozenset[int] = frozenset()
    uses: frozenset[int] = frozenset()

    if name in {
        "LOADNIL",
        "LOADB",
        "LOADN",
        "LOADK",
        "GETGLOBAL",
        "GETIMPORT",
        "GETUPVAL",
        "NEWTABLE",
        "DUPTABLE",
        "NEWCLOSURE",
        "DUPCLOSURE",
        "LOADKX",
    }:
        definitions = frozenset({instruction.a})
    elif name == "MOVE":
        definitions = frozenset({instruction.a})
        uses = frozenset({instruction.b})
    elif name in {"SETGLOBAL", "SETUPVAL"}:
        uses = frozenset({instruction.a})
    elif name == "GETTABLE":
        definitions = frozenset({instruction.a})
        uses = frozenset({instruction.b, instruction.c})
    elif name == "SETTABLE":
        uses = frozenset({instruction.a, instruction.b, instruction.c})
    elif name in {"GETTABLEKS", "GETUDATAKS", "GETTABLEN"}:
        definitions = frozenset({instruction.a})
        uses = frozenset({instruction.b})
    elif name in {"SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
        uses = frozenset({instruction.a, instruction.b})
    elif name in {"NAMECALL", "NAMECALLUDATA"}:
        definitions = frozenset({instruction.a, instruction.a + 1})
        uses = frozenset({instruction.b})
    elif name in {
        "ADD",
        "SUB",
        "MUL",
        "DIV",
        "MOD",
        "POW",
        "IDIV",
        "AND",
        "OR",
    }:
        definitions = frozenset({instruction.a})
        uses = frozenset({instruction.b, instruction.c})
    elif name in {
        "ADDK",
        "SUBK",
        "MULK",
        "DIVK",
        "MODK",
        "POWK",
        "IDIVK",
        "ANDK",
        "ORK",
    }:
        definitions = frozenset({instruction.a})
        uses = frozenset({instruction.b})
    elif name in {"SUBRK", "DIVRK"}:
        definitions = frozenset({instruction.a})
        uses = frozenset({instruction.c})
    elif name in {"NOT", "MINUS", "LENGTH"}:
        definitions = frozenset({instruction.a})
        uses = frozenset({instruction.b})
    elif name == "CONCAT":
        definitions = frozenset({instruction.a})
        uses = frozenset(range(instruction.b, instruction.c + 1))
    elif name in {
        "JUMPIF",
        "JUMPIFNOT",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "CMPPROTO",
    }:
        uses = frozenset({instruction.a})
    elif name in {
        "JUMPIFEQ",
        "JUMPIFLE",
        "JUMPIFLT",
        "JUMPIFNOTEQ",
        "JUMPIFNOTLE",
        "JUMPIFNOTLT",
    }:
        rhs = (instruction.aux or 0) & 0xFF
        uses = frozenset({instruction.a, rhs})
    elif name in {"CALL", "CALLFB"}:
        argument_count = instruction.b - 1 if instruction.b > 0 else 0
        uses = frozenset({instruction.a}) | _range(instruction.a + 1, argument_count)
        result_count = instruction.c - 1 if instruction.c > 0 else 1
        definitions = _range(instruction.a, result_count)
    elif name == "RETURN":
        result_count = instruction.b - 1 if instruction.b > 0 else 1
        uses = _range(instruction.a, result_count)
    elif name == "GETVARARGS":
        result_count = instruction.b - 1 if instruction.b > 0 else 1
        definitions = _range(instruction.a, result_count)
    elif name == "SETLIST":
        value_count = instruction.c - 1 if instruction.c > 0 else 1
        uses = frozenset({instruction.a}) | _range(instruction.b, value_count)
    elif name == "FORNPREP":
        uses = _range(instruction.a, 3)
        definitions = frozenset({instruction.a + 3})
    elif name == "FORNLOOP":
        uses = _range(instruction.a, 4)
        definitions = _range(instruction.a, 4)
    elif name in {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}:
        uses = _range(instruction.a, 3)
    elif name == "FORGLOOP":
        count = max(1, (instruction.aux or 1) & 0xFF)
        uses = _range(instruction.a, 3)
        definitions = _range(instruction.a + 3, count)
    elif name == "CAPTURE" and instruction.a != 2:
        uses = frozenset({instruction.b})
    elif name == "FASTCALL1":
        uses = frozenset({instruction.b})
    elif name == "FASTCALL2":
        uses = frozenset({instruction.b, instruction.aux_a or 0})
    elif name == "FASTCALL2K":
        uses = frozenset({instruction.b})
    elif name == "FASTCALL3":
        uses = frozenset({instruction.b, instruction.aux_a or 0, instruction.aux_b or 0})
    elif name == "NEWCLASS":
        definitions = frozenset({instruction.a})
        if instruction.b != 0xFF:
            uses = frozenset({instruction.b})
    elif name == "NEWCLASSMEMBER":
        uses = frozenset({instruction.a, instruction.c})
    elif name == "CLOSEUPVALS":
        uses = frozenset({instruction.a})

    return RegisterAccess(definitions=definitions, uses=uses)


def _block_use_def(
    blocks: tuple[BasicBlock, ...],
    accesses: Mapping[int, RegisterAccess],
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    block_uses: dict[int, set[int]] = {}
    block_defs: dict[int, set[int]] = {}
    for block in blocks:
        used_before_definition: set[int] = set()
        definitions: set[int] = set()
        for instruction in block.instructions:
            access = accesses[instruction.pc]
            used_before_definition.update(access.uses - definitions)
            definitions.update(access.definitions)
        block_uses[block.start_pc] = used_before_definition
        block_defs[block.start_pc] = definitions
    return block_uses, block_defs


def _liveness(
    blocks: tuple[BasicBlock, ...],
    accesses: Mapping[int, RegisterAccess],
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    block_uses, block_defs = _block_use_def(blocks, accesses)
    live_in: dict[int, set[int]] = {block.start_pc: set() for block in blocks}
    live_out: dict[int, set[int]] = {block.start_pc: set() for block in blocks}
    changed = True
    while changed:
        changed = False
        for block in reversed(blocks):
            start = block.start_pc
            outgoing = (
                set().union(*(live_in[item] for item in block.successors))
                if block.successors
                else set()
            )
            incoming = block_uses[start] | (outgoing - block_defs[start])
            if outgoing != live_out[start] or incoming != live_in[start]:
                live_out[start] = outgoing
                live_in[start] = incoming
                changed = True
    return live_in, live_out


def _merge_definition_states(
    states: list[dict[int, set[int]]],
) -> dict[int, set[int]]:
    merged: dict[int, set[int]] = defaultdict(set)
    for state in states:
        for register, definitions in state.items():
            merged[register].update(definitions)
    return dict(merged)


def _transfer_definitions(
    block: BasicBlock,
    incoming: dict[int, set[int]],
    accesses: Mapping[int, RegisterAccess],
) -> dict[int, set[int]]:
    state = {register: set(definitions) for register, definitions in incoming.items()}
    for instruction in block.instructions:
        for register in accesses[instruction.pc].definitions:
            state[register] = {instruction.pc}
    return state


def _def_use(
    blocks: tuple[BasicBlock, ...],
    accesses: Mapping[int, RegisterAccess],
) -> DefUseChain:
    incoming: dict[int, dict[int, set[int]]] = {block.start_pc: {} for block in blocks}
    outgoing: dict[int, dict[int, set[int]]] = {block.start_pc: {} for block in blocks}
    by_start = {block.start_pc: block for block in blocks}
    changed = True
    while changed:
        changed = False
        for block in blocks:
            predecessor_states = [outgoing[item] for item in block.predecessors]
            new_incoming = _merge_definition_states(predecessor_states)
            new_outgoing = _transfer_definitions(block, new_incoming, accesses)
            if new_incoming != incoming[block.start_pc] or new_outgoing != outgoing[block.start_pc]:
                incoming[block.start_pc] = new_incoming
                outgoing[block.start_pc] = new_outgoing
                changed = True

    reaching: dict[tuple[int, int], frozenset[int]] = {}
    reverse: dict[tuple[int, int], set[int]] = defaultdict(set)
    for start, block in by_start.items():
        state = {register: set(definitions) for register, definitions in incoming[start].items()}
        for instruction in block.instructions:
            access = accesses[instruction.pc]
            for register in access.uses:
                definitions = frozenset(state.get(register, set()))
                reaching[(instruction.pc, register)] = definitions
                for definition_pc in definitions:
                    reverse[(definition_pc, register)].add(instruction.pc)
            for register in access.definitions:
                state[register] = {instruction.pc}

    return DefUseChain(
        reaching_definitions=MappingProxyType(reaching),
        definition_uses=MappingProxyType({key: frozenset(value) for key, value in reverse.items()}),
    )


def analyze_control_flow(
    instructions: tuple[DecodedInstruction, ...] | list[DecodedInstruction],
    code_size: int,
) -> ControlFlowAnalysis:
    ordered = tuple(sorted(instructions, key=lambda item: item.pc))
    blocks, block_for_pc = _build_blocks(ordered, code_size)
    if not blocks:
        empty_map: Mapping[int, frozenset[int]] = MappingProxyType({})
        empty_optional: Mapping[int, int | None] = MappingProxyType({})
        return ControlFlowAnalysis(
            entry=0,
            blocks=(),
            block_by_start=MappingProxyType({}),
            block_for_pc=MappingProxyType({}),
            reachable=frozenset(),
            dominators=empty_map,
            immediate_dominators=empty_optional,
            postdominators=empty_map,
            immediate_postdominators=empty_optional,
            dominance_frontiers=empty_map,
            branches=(),
            loops=(),
            phi_nodes=(),
            register_accesses=MappingProxyType({}),
            live_in=empty_map,
            live_out=empty_map,
            def_use=DefUseChain(MappingProxyType({}), MappingProxyType({})),
        )

    entry = blocks[0].start_pc
    block_by_start = {block.start_pc: block for block in blocks}
    predecessors = {block.start_pc: block.predecessors for block in blocks}
    successors = {block.start_pc: block.successors for block in blocks}
    reachable = _reachable(entry, successors)
    dominators = _dominators(entry, reachable, predecessors)
    postdominators = _postdominators(reachable, successors)
    immediate_dominators = _immediate_relations(dominators, entry)
    immediate_postdominators = _immediate_relations(postdominators, None)
    frontiers = _dominance_frontiers(reachable, predecessors, immediate_dominators)
    loops = _natural_loops(reachable, predecessors, successors, dominators)
    accesses = {instruction.pc: register_access(instruction) for instruction in ordered}
    live_in, live_out = _liveness(blocks, accesses)
    branches = _branch_regions(blocks, block_for_pc, immediate_postdominators)
    phi_nodes = _phi_nodes(blocks, accesses, frontiers, live_in, live_out)

    return ControlFlowAnalysis(
        entry=entry,
        blocks=blocks,
        block_by_start=MappingProxyType(block_by_start),
        block_for_pc=MappingProxyType(block_for_pc),
        reachable=reachable,
        dominators=_freeze_map(dominators),
        immediate_dominators=MappingProxyType(immediate_dominators),
        postdominators=_freeze_map(postdominators),
        immediate_postdominators=MappingProxyType(immediate_postdominators),
        dominance_frontiers=_freeze_map(frontiers),
        branches=branches,
        loops=loops,
        phi_nodes=phi_nodes,
        register_accesses=MappingProxyType(accesses),
        live_in=_freeze_map(live_in),
        live_out=_freeze_map(live_out),
        def_use=_def_use(blocks, accesses),
    )


def reverse_postorder(analysis: ControlFlowAnalysis) -> tuple[int, ...]:
    if not analysis.blocks:
        return ()
    visited: set[int] = set()
    postorder: list[int] = []
    stack: list[tuple[int, bool]] = [(analysis.entry, False)]
    while stack:
        node, expanded = stack.pop()
        if expanded:
            postorder.append(node)
            continue
        if node in visited:
            continue
        visited.add(node)
        stack.append((node, True))
        successors = analysis.block_by_start[node].successors
        for successor in sorted(successors, reverse=True):
            if successor not in visited:
                stack.append((successor, False))
    postorder.reverse()
    return tuple(postorder)


def strongly_connected_components(
    analysis: ControlFlowAnalysis,
) -> tuple[frozenset[int], ...]:
    if not analysis.reachable:
        return ()
    reverse_edges: dict[int, set[int]] = {node: set() for node in analysis.reachable}
    for node in analysis.reachable:
        for successor in analysis.block_by_start[node].successors & analysis.reachable:
            reverse_edges[successor].add(node)

    assigned: set[int] = set()
    components: list[frozenset[int]] = []
    for root in reverse_postorder(analysis):
        if root in assigned:
            continue
        component: set[int] = set()
        pending = [root]
        while pending:
            node = pending.pop()
            if node in assigned:
                continue
            assigned.add(node)
            component.add(node)
            pending.extend(reverse_edges[node] - assigned)
        components.append(frozenset(component))
    return tuple(components)


def render_cfg_dot(analysis: ControlFlowAnalysis) -> str:
    lines = ["digraph luau_cfg {", "  node [shape=box];"]
    loop_headers = {loop.header for loop in analysis.loops}
    phi_by_block: dict[int, list[int]] = defaultdict(list)
    for phi in analysis.phi_nodes:
        phi_by_block[phi.block].append(phi.register)
    for block in analysis.blocks:
        instruction_names = "\\l".join(
            f"{instruction.pc}: {instruction.name}" for instruction in block.instructions
        )
        suffixes: list[str] = []
        if block.start_pc in loop_headers:
            suffixes.append("loop header")
        if phi_by_block[block.start_pc]:
            registers = ", ".join(f"R{item}" for item in phi_by_block[block.start_pc])
            suffixes.append("phi " + registers)
        suffix = "\\l" + "\\l".join(suffixes) if suffixes else ""
        label = f"B{block.start_pc}\\l{instruction_names}{suffix}\\l"
        lines.append(f'  B{block.start_pc} [label="{label}"];')
    for block in analysis.blocks:
        for successor in sorted(block.successors):
            lines.append(f"  B{block.start_pc} -> B{successor};")
    lines.append("}")
    return "\n".join(lines) + "\n"
