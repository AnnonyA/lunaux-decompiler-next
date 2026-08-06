# Advanced loops and state-machine unflattening

LunaUX Next 0.17 adds a CFG-native loop planner and a conservative pass for constant-register state dispatchers. Both passes run before source emission and expose immutable public plans that can be inspected independently from the lifter.

## Advanced loop recovery

Previous compatibility recovery was strongest when a loop used one obvious header and one adjacent backedge. Version 0.17 groups all natural loops that share a header, recomputes the merged body and exits, and then classifies the resulting region.

Supported loop forms include:

- pre-test `while` loops;
- post-test `repeat ... until` loops;
- infinite `while true do` loops with a validated exit;
- multiple latches that return to the same header;
- nested reducible loops;
- conditional and unconditional `break` edges;
- conditional and unconditional `continue` edges.

Numeric and generic `for` bytecode remains owned by the existing dedicated `FOR*` recovery and is not reclassified as an advanced loop.

### Pre-test loops

A header is accepted as a pre-test loop only when its block contains a conditional terminator plus ignorable instrumentation such as `NOP` or `COVERAGE`. One successor must enter the loop body and one must be the unique canonical exit.

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

The planner distinguishes the normal latch backedge from an explicit re-entry edge. The normal closing jump is suppressed; an additional validated edge to the continuation target becomes `continue`.

### Post-test loops

A post-test loop requires one conditional latch whose taken edge returns to the header and whose fallthrough edge reaches the unique exit.

```luau
repeat
    update()

    if cancelled then
        break
    end

    if retryImmediately then
        continue
    end
until complete
```

For a recovered `repeat`, `continue` targets the condition block rather than the first instruction in the body. This preserves Luau semantics because the condition must still be evaluated.

### Infinite loops

A reducible cycle without a supported pre-test or post-test condition can be emitted as `while true do` when its ownership and exits are unambiguous.

```luau
while true do
    step()

    if stopped then
        break
    end
end
```

### Conservative requirements

An advanced loop is rejected when any of the following applies:

- a body block has an external entry other than the header;
- merged exits do not resolve to one canonical target;
- the region contains `FOR*` instructions owned by numeric or generic loop recovery;
- a jump cannot be mapped to an exact taken, fallthrough, or unconditional edge;
- the region overlaps a recovered state machine;
- the CFG is irreducible or ownership remains ambiguous.

Rejected regions retain the previous compatibility output, labels, and jump comments.

## State-machine unflattening

The state-machine pass recognizes a narrow control-flow flattening pattern built around a constant numeric state register and a `JUMPXEQKN` selector chain.

A supported cycle conceptually resembles:

```luau
local state = 0

while true do
    if state == 0 then
        firstStep()
        state = 1
    elseif state == 1 then
        secondStep()
        state = 0
    end
end
```

When every transition is deterministic and the state register is private to the dispatcher, LunaUX can emit the semantic order directly:

```luau
-- unflattened state machine R0; initial=0
while true do
    firstStep()
    secondStep()
end
```

A terminating chain can be emitted without the dispatcher loop:

```luau
-- unflattened state machine R0; initial=0
firstStep()
secondStep()
return result
```

Physical case order in bytecode does not determine output order. The pass begins at the validated initial state and follows each constant transition until it reaches a terminal case or returns to the initial state.

### Required evidence

A state machine is folded only when all of the following are true:

- the dispatcher belongs to a reducible natural loop;
- selectors form a traceable `JUMPXEQKN` chain over one register;
- selector constants are unique numeric states;
- one external predecessor initializes the state with `LOADN`, `LOADK`, or `LOADKX`;
- each nonterminal case contains exactly one constant state assignment;
- each nonterminal case jumps directly back to the dispatcher;
- the state register has no reads outside selectors and no writes outside validated transitions;
- following transitions visits every recovered case exactly once before termination or a simple cycle;
- cases do not contain unsupported internal control flow;
- any terminal exit is unambiguous.

A terminal case may lie outside the natural-loop body because it does not jump back to the dispatcher. It is still included only when its selector target and ownership are directly resolvable.

### Rejected machines

The pass deliberately retains low-level output for:

- dynamic or table-driven state values;
- string, boolean, or computed selectors;
- multiple initializers or multiple entries;
- state values used by ordinary case logic;
- conditional or indirect state transitions;
- branches inside a case body;
- cycles that enter a state other than the validated initial state;
- partial chains with unreachable or multiply visited cases;
- overlapping dispatchers or ambiguous terminal exits.

This boundary avoids treating normal switch-like code as an obfuscated state machine.

## Interaction with other recovery passes

State-machine regions have priority over loop, boolean-chain, phi-expression, and label recovery for the instructions they own. Their dispatcher selectors and state writes are removed only after the complete machine validates.

Advanced loops then run on the remaining CFG. Existing expression AST, SSA inlining, table reconstruction, class recovery, contextual functions, Roblox typing, and callback recovery continue to process instructions inside emitted loop and machine bodies.

Cyclic CFGs also receive bounded flow-sensitive type analysis. When its worklist cannot converge within a budget proportional to the function graph, LunaUX discards that function's flow refinements and continues with conservative base typing instead of blocking or keeping a partial fixed point.

## Public API

The loop pass exports:

```python
from lunaux.backends import (
    AdvancedLoopPlan,
    AdvancedLoopRegion,
    LoopJumpAction,
    analyze_advanced_loops,
)
```

The state-machine pass exports:

```python
from lunaux.backends import (
    StateMachineCase,
    StateMachinePlan,
    StateMachineRegion,
    recover_state_machines,
)
```

The plans record region ownership, skipped instructions, structured targets, case order, state transitions, loop depth, backedges, and recovered `break`/`continue` actions.

## Options

Both features are enabled by default:

```json
{
  "AdvancedLoops": true,
  "UnflattenStateMachines": true
}
```

Disabling `AdvancedLoops` preserves the previous simple loop compatibility recovery. Disabling `UnflattenStateMachines` leaves dispatcher selectors and state assignments visible to the normal lifter.

## Validation workflow

CI uses a concurrency group scoped to the pull request or pushed ref. A newer commit cancels its obsolete matrix, preventing queued macOS jobs from older revisions from delaying validation of the current head.

## Accuracy boundary

Luau bytecode does not retain the author's original loop spelling, labels, comments, or the reason a dispatcher exists. Version 0.17 reconstructs one supported semantic structure from CFG and constant data-flow evidence. It does not claim exact original source and does not attempt generalized deobfuscation of arbitrary virtual machines.
