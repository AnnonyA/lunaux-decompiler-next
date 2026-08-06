from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing marker: {label}")
    return text.replace(old, new, 1)


state_path = Path("src/lunaux/backends/state_machine.py")
state_text = state_path.read_text(encoding="utf-8")

state_text = replace_once(
    state_text,
    '''        if selector.match_target not in loop_body:
            return None
''',
    '''        if selector.match_target not in analysis.block_by_start:
            return None
''',
    "selector target ownership",
)
state_text = replace_once(
    state_text,
    '''    if block.start_pc not in loop_body:
        return None

    instructions = [
''',
    '''    instructions = [
''',
    "terminal case location",
)
state_text = replace_once(
    state_text,
    '''    if target == dispatcher_header:
        if len(state_assignments) != 1:
''',
    '''    if target == dispatcher_header:
        if block.start_pc not in loop_body or len(state_assignments) != 1:
''',
    "transition case loop ownership",
)
state_text = replace_once(
    state_text,
    '''def _exclusive_state_register(
    analysis: ControlFlowAnalysis,
    loop_body: frozenset[int],
    register: int,
''',
    '''def _exclusive_state_register(
    analysis: ControlFlowAnalysis,
    owned_blocks: frozenset[int],
    register: int,
''',
    "exclusive block parameter",
)
state_text = replace_once(
    state_text,
    '''    for block_start in loop_body:
        for instruction in analysis.block_by_start[block_start].instructions:
''',
    '''    for block_start in owned_blocks:
        for instruction in analysis.block_by_start[block_start].instructions:
''',
    "exclusive block iteration",
)
state_text = replace_once(
    state_text,
    '''def _group_loops(loops: Sequence[NaturalLoop]) -> tuple[NaturalLoop, ...]:
''',
    '''def _group_loops(
    analysis: ControlFlowAnalysis,
    loops: Sequence[NaturalLoop],
) -> tuple[NaturalLoop, ...]:
''',
    "state grouped loop signature",
)
state_text = replace_once(
    state_text,
    '''        body = frozenset(block for member in members for block in member.body)
        exits = frozenset(edge for member in members for edge in member.exits)
        result.append(
''',
    '''        body = frozenset(block for member in members for block in member.body)
        exits = frozenset(
            (source, target)
            for source in body
            for target in analysis.block_by_start[source].successors
            if target not in body
        )
        result.append(
''',
    "state grouped loop exits",
)
state_text = replace_once(
    state_text,
    '''    if not _exclusive_state_register(
        analysis,
        loop.body,
        state_register,
''',
    '''    owned_blocks = loop.body | frozenset(case_blocks)
    if not _exclusive_state_register(
        analysis,
        owned_blocks,
        state_register,
''',
    "owned case blocks",
)
state_text = replace_once(
    state_text,
    '''            for block_start in loop.body
            for instruction in analysis.block_by_start[block_start].instructions
''',
    '''            for block_start in owned_blocks
            for instruction in analysis.block_by_start[block_start].instructions
''',
    "machine max pc blocks",
)
state_text = replace_once(
    state_text,
    '''        for loop in _group_loops(analysis.loops)
''',
    '''        for loop in _group_loops(analysis, analysis.loops)
''',
    "state grouped loop call",
)
state_path.write_text(state_text, encoding="utf-8")

loop_path = Path("src/lunaux/backends/advanced_loops.py")
loop_text = loop_path.read_text(encoding="utf-8")
loop_text = replace_once(
    loop_text,
    '''def _group_loops(loops: Sequence[NaturalLoop]) -> tuple[NaturalLoop, ...]:
''',
    '''def _group_loops(
    analysis: ControlFlowAnalysis,
    loops: Sequence[NaturalLoop],
) -> tuple[NaturalLoop, ...]:
''',
    "advanced grouped loop signature",
)
loop_text = replace_once(
    loop_text,
    '''        body: set[int] = set()
        exits: set[tuple[int, int]] = set()
        for member in members:
            body.update(member.body)
            exits.update(member.exits)
        merged.append(
''',
    '''        body: set[int] = set()
        for member in members:
            body.update(member.body)
        exits = {
            (source, target)
            for source in body
            for target in analysis.block_by_start[source].successors
            if target not in body
        }
        merged.append(
''',
    "advanced grouped loop exits",
)
loop_text = replace_once(
    loop_text,
    '''        for loop in _group_loops(analysis.loops)
''',
    '''        for loop in _group_loops(analysis, analysis.loops)
''',
    "advanced grouped loop call",
)
loop_path.write_text(loop_text, encoding="utf-8")
