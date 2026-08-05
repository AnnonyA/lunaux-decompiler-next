# Structured AST and lexical scopes

LunaUX Next 0.9 introduces a typed intermediate representation between recovered bytecode values and generated Luau source.

## Expression model

`lunaux.backends.ast` contains immutable nodes for:

- names, literals, varargs, and conservative raw expressions;
- unary and binary operations;
- field and index access;
- regular and method calls;
- tables and Luau `if` expressions.

The source lifter uses these nodes for the operations whose semantics are known precisely. Unsupported or incomplete constructs remain `RawExpr` values instead of being guessed into an incorrect tree.

## Precedence and associativity

The printer owns Luau precedence rules. It preserves grouping for:

- `or` and `and`;
- comparisons;
- concatenation;
- additive and multiplicative operators;
- unary operators;
- right-associative exponentiation;
- calls, fields, and indexes.

This prevents both unnecessary parentheses and semantic changes. It also handles lexical hazards such as nested negation: `-(-value)` must never become `--value`, which Luau would interpret as a comment.

## Statement model

The same module defines blocks and statement nodes for assignments, returns, expressions, branches, loops, and functions. The current bytecode lifter still emits some statements through its compatibility emitter while expression migration proceeds. These nodes form the target for a later whole-function CFG-to-AST structuring pass.

## Lexical scope model

`lunaux.backends.scopes` reconstructs a deterministic scope tree from local debug ranges. It supports:

- nested local lifetimes;
- shadowed names;
- register reuse across disjoint ranges;
- typed-local metadata;
- name and register resolution at a program counter;
- visible-binding enumeration.

When debug ranges are absent, the lifter retains its deterministic register fallback names.

## Accuracy boundary

The AST does not restore information that bytecode never stored. Comments, exact formatting, many original names, and the author's precise choice among equivalent high-level constructs remain unavailable.

The 0.9 implementation is intentionally conservative:

1. use structured nodes when operand semantics are known;
2. preserve opaque source fragments when they are not;
3. never duplicate an expression whose evaluation could have side effects;
4. preserve debug-visible local bindings;
5. prefer valid Luau over visually attractive but uncertain reconstruction.

## Future work

The next compiler phases can build on this representation to add:

- complete condition ASTs;
- CFG region conversion into statement blocks;
- explicit closure and upvalue cells;
- open-stack and multi-return value shapes;
- source recompilation and bytecode equivalence checks;
- confidence metadata for inferred names and structures.
