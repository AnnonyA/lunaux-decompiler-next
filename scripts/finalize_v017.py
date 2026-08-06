from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing marker: {label}")
    return text.replace(old, new, 1)


readme_path = Path("README.md")
readme = readme_path.read_text(encoding="utf-8")
readme = replace_once(
    readme,
    "> **Version 0.16:** recovers conservative classes built from tables and metatables, and derives function names, parameter roles, types, and return hints from assignment and callback context.\n",
    "> **Version 0.17:** recovers advanced reducible loops with validated `break`/`continue` edges and conservatively unflattens deterministic constant-register state machines.\n",
    "version banner",
)
readme = replace_once(
    readme,
    "- Combines reducible short-circuit branch chains into `and` and `or` conditions without crossing side effects.\n",
    "- Combines reducible short-circuit branch chains into `and` and `or` conditions without crossing side effects.\n"
    "- Groups natural loops by CFG header, recomputes merged exits, and recovers pre-test, post-test, infinite, multi-latch, and nested loop regions.\n"
    "- Converts validated loop exits and re-entry edges into Luau `break` and `continue` while suppressing only the implicit closing backedge.\n"
    "- Unflattens deterministic numeric `JUMPXEQKN` state dispatchers into transition order when the state register and every transition have exclusive constant ownership.\n",
    "control-flow highlights",
)
section = '''### Advanced loops and state-machine unflattening

Version 0.17 replaces adjacency-only loop recognition with a CFG-native plan. Natural loops sharing one header are merged before exits are recomputed, so multiple latches and explicit `continue` edges do not create false loop exits.

```luau
while running do
    if shouldSkip then
        continue
    end

    process()

    if finished then
        break
    end
end
```

The pass supports conservative pre-test `while`, post-test `repeat ... until`, infinite `while true do`, nested reducible loops, and conditional or unconditional `break`/`continue`. Numeric and generic `for` bytecode remains owned by the existing dedicated recovery.

Version 0.17 also recognizes constant numeric state dispatchers built from `JUMPXEQKN`. When the initial state, selector chain, state register ownership, and every transition validate, physical case order is replaced with semantic transition order.

```luau
-- unflattened state machine R0; initial=0
while true do
    firstStep()
    secondStep()
end
```

Dynamic states, indirect transitions, case-local branches, state values used by ordinary logic, multiple entries, ambiguous exits, and partial or irreducible machines retain the low-level representation. The pass reconstructs a supported semantic structure; it does not claim generalized deobfuscation or exact original source.

Use `AdvancedLoops` and `UnflattenStateMachines` to disable either pass independently. See [`docs/ADVANCED_LOOPS_AND_STATE_MACHINES.md`](docs/ADVANCED_LOOPS_AND_STATE_MACHINES.md).

'''
readme = replace_once(
    readme,
    "### Experimental bytecode classes\n",
    section + "### Experimental bytecode classes\n",
    "advanced recovery section",
)
readme_path.write_text(readme, encoding="utf-8")

flow_path = Path("src/lunaux/backends/flow_types.py")
flow = flow_path.read_text(encoding="utf-8")
flow = replace_once(
    flow,
    '''    queue: deque[int] = deque([resolved_analysis.entry])
    queued = {resolved_analysis.entry}

    while queue:
        block_start = queue.popleft()
''',
    '''    queue: deque[int] = deque([resolved_analysis.entry])
    queued = {resolved_analysis.entry}
    edge_count = sum(len(block.successors) for block in resolved_analysis.blocks)
    convergence_budget = max(64, len(resolved_analysis.blocks) * max(1, edge_count) * 8)
    processed_blocks = 0

    while queue:
        processed_blocks += 1
        if processed_blocks > convergence_budget:
            return FlowTypeAnalysis.empty()
        block_start = queue.popleft()
''',
    "flow convergence budget",
)
flow_path.write_text(flow, encoding="utf-8")

structuring_path = Path("src/lunaux/backends/structuring.py")
structuring = structuring_path.read_text(encoding="utf-8")
structuring = replace_once(
    structuring,
    '''    conditions = [root]
    failure = root.taken
    current = root
    while True:
        candidate = branch_by_header.get(current.fallthrough)
        if candidate is None or candidate.taken != failure:
            break
''',
    '''    conditions = [root]
    failure = root.taken
    current = root
    visited_headers = {root.header}
    while True:
        candidate = branch_by_header.get(current.fallthrough)
        if (
            candidate is None
            or candidate.header in visited_headers
            or candidate.taken != failure
        ):
            break
        visited_headers.add(candidate.header)
''',
    "and-chain cycle guard",
)
structuring = replace_once(
    structuring,
    '''    conditions = [root]
    skipped_pcs = set(skipped)
    current = root
    while True:
        candidate = branch_by_header.get(current.taken)
        if candidate is None:
            break
''',
    '''    conditions = [root]
    skipped_pcs = set(skipped)
    current = root
    visited_headers = {root.header}
    while True:
        candidate = branch_by_header.get(current.taken)
        if candidate is None or candidate.header in visited_headers:
            break
        visited_headers.add(candidate.header)
''',
    "or-chain cycle guard",
)
structuring_path.write_text(structuring, encoding="utf-8")

lifter_path = Path("src/lunaux/backends/lifter.py")
lifter = lifter_path.read_text(encoding="utf-8")
lifter = replace_once(
    lifter,
    '''        for instruction in self.instructions:
            target = get_jump_target(instruction)
            if (
                target is not None
''',
    '''        for instruction in self.instructions:
            if instruction.pc in self.state_machine_plan.skipped_pcs:
                continue
            target = get_jump_target(instruction)
            if (
                target is not None
''',
    "state-machine label exclusion",
)
lifter_path.write_text(lifter, encoding="utf-8")
