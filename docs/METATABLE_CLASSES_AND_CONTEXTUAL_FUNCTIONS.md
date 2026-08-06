# Metatable classes and contextual functions

LunaUX Next 0.16 extends class recovery beyond the experimental `NEWCLASS` bytecode and adds a function-context pass that runs before source emission.

## Metatable-backed classes

The recovery pass recognizes conservative table-class patterns such as:

```luau
local Point = {}
Point.__index = Point

function Point.new(x)
    return setmetatable({ x = x }, Point)
end

function Point:getX()
    return self.x
end

function Point:__tostring()
    return `Point({self.x})`
end
```

When ownership and data flow are unambiguous, the compatibility emitter can represent the recovered shape as:

```luau
class Point
    -- recovered from metatable __index pattern
    public x

    -- constructor
    function new(x): Point
        -- reconstructed body
    end

    function getX(self: Point)
        return self.x
    end

    -- metamethod
    function __tostring(self: Point): string
        -- reconstructed body
    end
end
```

A table is folded only when the pass finds all of the following evidence:

- a directly traceable `NEWTABLE` or `DUPTABLE` definition;
- a self-referential `Class.__index = Class` assignment;
- one or more named closure members with resolvable child prototypes;
- at least one constructor, instance method, or metamethod;
- no dynamic-key member write that could change the class surface.

Single-register `MOVE` aliases are canonicalized back to the owning SSA value before checking `__index`, member assignments, and closure ownership. The original member writes, closure creation instructions, and validated capture instructions are skipped only after the class declaration owns those closures. Shared closures and unresolved members keep their ordinary representation.

## Method classification

Members are classified as:

- `constructor` for `new` and `create`;
- `metamethod` for names beginning with `__`;
- `instance_method` when parameter zero is used as a receiver;
- `static_method` for the remaining named class functions.

Reads and writes such as `self.Health` or `self.x` contribute conservative property declarations. Constructor returns are annotated with the recovered class type. Known metamethod contracts add parameter roles and return hints such as `boolean`, `number`, or `string`.

Experimental v100 `NEWCLASS` and `NEWCLASSMEMBER` recovery continues to use the same `ClassRecoveryPlan`, so both bytecode-native and metatable-backed classes share one public model.

## Contextual functions

`FunctionContextPlan` derives a function's likely role from its use rather than relying only on the prototype debug name. Supported evidence includes:

- assignment to a named table field;
- membership in a recovered class;
- assignment to a global;
- return from a prototype;
- recognized callback positions from the Roblox callback pass.

The context may provide:

- a stable function name;
- a function kind;
- parameter names;
- parameter types;
- a conservative return type;
- evidence and confidence metadata.

For example, a callback with the Roblox signature `(InputObject, boolean)` is rendered consistently as:

```luau
UserInputService.InputBegan:Connect(function(
    input: InputObject,
    processed: boolean
)
    if not processed then
        print(input.KeyCode)
    end
end)
```

The contextual name is installed in the function's register map before lifting the body, preventing a header such as `input` from being followed by stale references such as `arg1`.

## Public options

- `RecoverClasses` enables all supported class reconstruction.
- `RecoverMetatableClasses` enables the table/metatable extension and defaults to `true`.
- `ContextualFunctions` enables contextual names, parameter roles, and return hints and defaults to `true`.

Disabling `RecoverMetatableClasses` leaves ordinary table and closure assignments intact while preserving experimental v100 class recovery. Disabling `ContextualFunctions` retains the previous prototype and type naming behavior.

## Accuracy boundary

This pass reconstructs a supported semantic pattern, not the original source syntax. Luau bytecode does not preserve whether the author used dot syntax, colon syntax, helper constructors, a class library, exact parameter names, comments, or formatting.

Dynamic metatables, computed member names, shared closure ownership, conflicting assignments, and incomplete evidence remain conservative table/function output. A recovered class name may come from debug locals or a validated assignment target; otherwise LunaUX emits a deterministic generated name rather than claiming an original identifier.
