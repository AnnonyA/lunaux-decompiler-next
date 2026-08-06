from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing marker: {label}")
    return text.replace(old, new, 1)


path = Path("src/lunaux/backends/state_machine.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''        if selector.match_target not in loop_body:
            return None
''',
    '''        if selector.match_target not in analysis.block_by_start:
            return None
''',
    "selector target ownership",
)
text = replace_once(
    text,
    '''    if block.start_pc not in loop_body:
        return None

    instructions = [
''',
    '''    instructions = [
''',
    "terminal case location",
)
text = replace_once(
    text,
    '''    if target == dispatcher_header:
        if len(state_assignments) != 1:
''',
    '''    if target == dispatcher_header:
        if block.start_pc not in loop_body or len(state_assignments) != 1:
''',
    "transition case loop ownership",
)
text = replace_once(
    text,
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
text = replace_once(
    text,
    '''    for block_start in loop_body:
        for instruction in analysis.block_by_start[block_start].instructions:
''',
    '''    for block_start in owned_blocks:
        for instruction in analysis.block_by_start[block_start].instructions:
''',
    "exclusive block iteration",
)
text = replace_once(
    text,
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
text = replace_once(
    text,
    '''            for block_start in loop.body
            for instruction in analysis.block_by_start[block_start].instructions
''',
    '''            for block_start in owned_blocks
            for instruction in analysis.block_by_start[block_start].instructions
''',
    "machine max pc blocks",
)

path.write_text(text, encoding="utf-8")
