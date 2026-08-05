# Architecture

LunaUX Next separates transport, validation, formatting options, and backend execution. The current native adapter is intentionally small so a future open engine can replace it without changing the CLI or HTTP API.

## Current layers

```text
CLI / HTTP API
      ↓
Input decoding and request validation
      ↓
DecompilerService
      ↓
DecompilerBackend protocol
      ↓
Native compatibility module or future open backend
```

## Rules

1. The CLI calls the service directly. It must not shell out to `curl` or require the HTTP server.
2. The HTTP API owns transport concerns only.
3. The service owns byte limits, filename normalization, and output limits.
4. Backends receive validated bytes and return text or a typed error.
5. Formatting preferences use a shared model and are translated at the adapter boundary.

## Intended open-engine pipeline

A future source-available Luau decompiler should use explicit stages:

```text
Bytecode reader
  → validated prototypes and instructions
  → basic blocks and control-flow graph
  → data-flow / register lifetime analysis
  → intermediate representation
  → structured regions and expressions
  → Luau AST
  → deterministic pretty-printer
```

### Bytecode reader

The reader must reject unsupported versions, truncated operands, impossible constant indexes, excessive nesting, and unreasonable allocation requests. Parsing must never trust lengths from the input without checking remaining bytes and configured limits.

### Control-flow graph

Instructions are divided into basic blocks. Edges represent fallthrough, conditional jumps, loop back edges, and exits. Dominator and post-dominator information should drive region reconstruction instead of local jump-pattern heuristics alone.

### Data flow

Register definitions and uses are tracked across blocks. The analysis should model multiple returns, varargs, closure captures, table construction, and call result arity. An SSA-like internal representation is recommended even if the final source uses ordinary local variables.

### Structuring

Loops, conditions, short-circuit expressions, `break`, and `continue` are recovered from the graph. Irreducible regions must degrade predictably, with explicit low-level comments or labels in an analysis mode rather than silently changing behavior.

### AST and printer

Semantic reconstruction and formatting are separate. Options such as semicolons, string interpolation, and `if` expressions belong in the printer when they do not alter behavior.

## Testing strategy

- Parser tests for valid and malformed bytecode.
- Golden output tests with normalized formatting.
- Recompilation tests using the official Luau compiler.
- Behavioral comparison where original and reconstructed programs can be executed safely.
- Fuzzing with strict time and memory budgets.
- Public per-release metrics for parse, recompilation, and semantic-match rates.
