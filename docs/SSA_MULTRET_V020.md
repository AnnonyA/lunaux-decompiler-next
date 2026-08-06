# LunaUX 0.20: MULTRET-aware SSA

Luau uses the stack top to represent open value sequences. The relevant bytecode forms are:

- `CALL B=0`: consume arguments through the current stack top;
- `CALL C=0`: preserve every returned value and move the stack top;
- `RETURN B=0`: return every value from register `A` through the stack top;
- `GETVARARGS B=0`: copy every variadic value and move the stack top;
- `SETLIST C=0`: append every value from register `B` through the stack top.

Treating these forms as one ordinary register loses tuple ownership. LunaUX 0.20 therefore adds an explicit MULTRET layer to `SSAProgram`.

## Model

`SSAMultiValue` represents an open tuple produced by a call or `GETVARARGS`. `SSAMultiUse` links that tuple to one conservative consumer and records any fixed registers that appear before the open tail.

For example, the bytecode form corresponding to:

```luau
return fixedValue, produceMany()
```

is represented as one fixed prefix register plus the open tuple produced by `produceMany()`; the tuple is not fabricated as a sequence of unknown register definitions.

A call can consume one open tuple and produce another in the same instruction, which allows chains such as:

```luau
return outer(fixedArgument, inner(...))
```

## Safety boundary

The initial 0.20 analysis is intentionally local and deterministic:

- ownership is propagated only inside one reachable basic block;
- `NOP` and `COVERAGE` are the only allowed instructions between producer and consumer;
- ordinary instructions, mutations, branches, and calls without a validated relationship invalidate pending ownership;
- unresolved open tuples remain visible through `SSAMultiValuePlan.unresolved_values`;
- the register SSA remains conservative and the MULTRET plan supplements it instead of inventing a maximum tuple length.

## Public API

`SSAProgram` now exposes:

```python
program.multi_values
program.multi_value_at(producer_pc)
program.multi_use_at(consumer_pc)
```

The public backend package exports `SSAMultiValue`, `SSAMultiUse`, and `SSAMultiValuePlan`. `render_ssa` annotates both producers and validated consumers.

## Next 0.20 increment

The source emitter will consume this ownership plan to replace low-level stack-top comments with semantic Luau forms such as direct multiple returns, expanded final arguments, and open table tails. That integration remains gated by the same conservative ownership proof.
