# LunaUX 0.20: semantic MULTRET source emission

The 0.20 SSA layer proves local ownership of open Luau value sequences. This increment connects that proof to source emission.

## Recovered forms

When an open call is the validated final value sequence of a return, LunaUX emits the call directly in final expression position:

```luau
return fixedValue, produceMany()
```

When open varargs are the validated tail of a call, they remain in final argument position:

```luau
return target(fixedArgument, ...)
```

A call may consume one open sequence and produce another. The emitter therefore supports deterministic chains without inventing temporary registers or a guessed tuple size.

## Conservative fallback

The semantic form is used only when `SSAMultiValuePlan` links the producer and consumer. A mutation, branch, unsupported gap, different basic block, or missing producer keeps the previous explicit stack-top diagnostic. This prevents readability improvements from silently changing behavior.

## Implementation boundary

The MULTRET emitter extends the existing function lifter rather than duplicating its large control-flow and expression implementation. The reconstructed backend installs the extension once, so nested callbacks and recovered class methods use the same validated behavior.

Future 0.20 increments can extend the same proof to more open table-tail layouts and tuple-aware optimization without weakening the fallback boundary.
