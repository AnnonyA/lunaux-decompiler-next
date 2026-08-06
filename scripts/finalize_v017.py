from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing marker: {label}")
    return text.replace(old, new, 1)


path = Path("README.md")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "> **Version 0.16:** recovers conservative classes built from tables and metatables, and derives function names, parameter roles, types, and return hints from assignment and callback context.\n",
    "> **Version 0.17:** recovers advanced reducible loops with validated `break`/`continue` edges and conservatively unflattens deterministic constant-register state machines.\n",
    "version banner",
)

text = replace_once(
    text,
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
text = replace_once(
    text,
    "### Experimental bytecode classes\n",
    section + "### Experimental bytecode classes\n",
    "advanced recovery section",
)

path.write_text(text, encoding="utf-8")
