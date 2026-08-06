# LunaUX 0.19 scalar state-machine recovery

The first 0.19 control-flow milestone broadens deterministic dispatcher recovery from numeric-only states to all scalar constants represented by Luau's `JUMPXEQK*` family.

## Supported selectors

- `JUMPXEQKNIL` for `nil`;
- `JUMPXEQKB` for booleans;
- `JUMPXEQKN` for number and integer constants;
- `JUMPXEQKS` for string constants.

Initial states and transitions may be produced by `LOADNIL`, non-skipping `LOADB`, `LOADN`, `LOADK`, or `LOADKX` when the loaded constant is scalar.

## Correctness guards

Recovery remains conservative. The pass requires one state register, exclusive scalar assignments, a deterministic transition chain, complete selector coverage, and simple case blocks.

State identity is type-aware. In particular, `false` and numeric `0` are separate states even though Python considers them equal. A transition to `nil` is also distinguished from a terminal case by the presence of its transition instruction.

Selectors whose opcode does not match the referenced constant kind are rejected. Table, vector, closure, class-shape, import, and other non-scalar constants are not accepted as dispatcher states.

## Still deferred

This milestone does not yet recover multi-block cases, case-local branches, multiple exits, indirect transitions, encoded states, or partial state machines. Those remain later 0.19 work.
