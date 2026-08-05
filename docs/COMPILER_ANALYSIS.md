# Compiler analysis architecture

LunaUX Next 0.7 introduces a compiler-analysis layer between Luau bytecode decoding and source reconstruction.

## Pipeline

```text
serialized Luau bytecode
    -> decoded instructions
    -> basic blocks
    -> control-flow graph
    -> dominance and data-flow analysis
    -> structured source lifter
```

The existing source lifter remains the final emitter, but it can now use whole-function graph information instead of relying only on adjacent opcode patterns.

## Implemented in 0.7

The Python engine builds AUX-aware basic blocks and computes:

- predecessor and successor edges;
- reachable blocks;
- dominators and immediate dominators;
- postdominators and immediate postdominators;
- dominance frontiers;
- natural loops and loop exits;
- conditional branch regions and join blocks;
- register definitions and uses;
- block liveness;
- reaching definitions and reverse def-use chains;
- pruned SSA `phi` placement;
- reverse postorder;
- strongly connected components;
- Graphviz DOT output for diagnostics.

The lifter uses graph-derived loop and branch regions to supplement its compatibility heuristics for `while`, `repeat`, and `if`/`else` reconstruction.

## Public analysis API

```python
from lunaux.backends import analyze_control_flow, render_cfg_dot
from lunaux.backends.opcodes import decode_words

instructions = decode_words(proto.code)
analysis = analyze_control_flow(instructions, len(proto.code))
print(render_cfg_dot(analysis))
```

`ControlFlowAnalysis` exposes blocks, dominators, postdominators, loops, branch regions, liveness, def-use information, and proposed `phi` nodes.

## Accuracy model

The analysis is intentionally conservative. Unknown stack-top ranges from open calls, varargs, or returns are not guessed. A decompiler should preserve uncertainty rather than invent source semantics.

Bytecode does not retain comments, exact formatting, every local name, or necessarily the original high-level construct selected by the author. CFG and data-flow analysis improve semantic reconstruction, but they do not make exact source recovery mathematically possible.

## Next compiler phases

The following stages build on this foundation:

1. SSA value renaming and explicit `phi` operands.
2. Expression-tree construction and temporary elimination.
3. A structured Luau AST and independent source printer.
4. Multi-return and open-stack value-range analysis.
5. Scope, closure, and upvalue-cell reconstruction.
6. Recompilation and differential semantic verification.
7. Type and variable-name inference with confidence thresholds.

These phases should be measured using recompilability and behavioral equivalence, not only visual similarity.
