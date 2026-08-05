# SSA and expression recovery

LunaUX Next 0.8 adds a versioned static single-assignment layer on top of the 0.7 control-flow analysis.

## SSA pipeline

```text
Luau instructions
    -> basic blocks and CFG
    -> dominance frontiers
    -> pruned phi placement
    -> dominator-tree value renaming
    -> predecessor-specific phi operands
    -> use counts and expression candidates
```

Each register definition receives a distinct value such as `R2.1`, `R2.2`, or `R2.3`. Uses resolve to the exact reaching value rather than only the physical Luau register number.

This matters because the compiler frequently reuses a register for unrelated source values. Register names alone cannot safely reconstruct expressions or scopes.

## Phi values

When several control-flow paths define the same live register, LunaUX creates a phi result and records one operand for each predecessor.

```text
R0.3 = phi(B4: R0.1, B9: R0.2)
```

Phi information is currently exposed through the analysis API and used as a foundation for future scope and expression reconstruction. LunaUX does not print synthetic phi syntax into recovered Luau source.

## Conservative temporary elimination

The source lifter can remove a temporary only when all of these conditions hold:

- the SSA value has exactly one use;
- its defining instruction has one result;
- the use is in the immediately following instruction;
- definition and use are inside the same basic block;
- the consumer uses that register once;
- the value is not represented by a named or typed debug local;
- the operation is in the supported expression set;
- no control-flow skip or open multi-result behavior is involved.

For example:

```luau
local v0 = 42
return v0
```

can become:

```luau
return 42
```

and:

```luau
local v1 = "hello"
print(v1)
```

can become:

```luau
print("hello")
```

LunaUX does not duplicate an expression when a consumer reads the same register more than once. It also preserves locals with debug names or serialized type information.

## Option

Classic API name:

```json
{
  "InlineSingleUseTemporaries": true
}
```

Python/Pydantic name:

```text
inline_single_use_temporaries
```

The option defaults to `true` and can be disabled to obtain the more literal register-oriented output.

## Public API

```python
from lunaux.backends import build_ssa, render_ssa
from lunaux.backends.opcodes import decode_words

instructions = decode_words(proto.code)
program = build_ssa(instructions, len(proto.code))
print(render_ssa(program))
```

`SSAProgram` exposes instruction uses and definitions, entry values, phi nodes with operands, use counts, and definition lookup.

## Limitations and next steps

Version 0.8 does not yet include:

- a complete expression tree with formal precedence;
- an independent structured Luau AST and printer;
- exact open-stack range analysis for every vararg/multi-return case;
- source-level scope reconstruction from phi elimination;
- recompilation and behavioral equivalence verification.

Those stages must remain conservative. Bytecode cannot preserve comments, exact formatting, all names, or every original high-level source choice.
