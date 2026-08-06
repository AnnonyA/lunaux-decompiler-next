# Roblox events, callbacks, and modules

LunaUX Next 0.14 adds a conservative Roblox semantic pass on top of CFG, SSA,
expression, and table reconstruction.

## Event connections

Recognized `RBXScriptSignal` calls keep their source signal and connection method:

```luau
local connection: RBXScriptConnection = button.Activated:Connect(function(input)
    print(input)
end)
```

The pass recognizes `Connect`, `ConnectParallel`, `Once`, and `Wait`. Connection
results receive `RBXScriptConnection` evidence when the bytecode actually returns
the connection.

## Inline callbacks

A closure is rendered as an anonymous function only when SSA proves that its
closure instance reaches exactly one supported callback sink, module field, or
return value. Supported callback sinks include Roblox event connections,
`ContextActionService` bindings, `RunService:BindToRenderStep`, `task` scheduling,
`coroutine` creation/wrapping, `pcall`, `xpcall`, and `table.sort`.

Closure aliases through single-use `MOVE` instructions are followed. Captured
values and references are rebound inside the anonymous function, while the
original `CAPTURE` instructions are omitted from source output.

Shared callbacks remain named functions:

```luau
local function onChanged(value)
    print(value)
end

first.Changed:Connect(onChanged)
second.Changed:Connect(onChanged)
```

## ModuleScript recovery

`require` dependencies are recovered from direct instance paths and common
`WaitForChild`/`FindFirstChild` chains. The required value is named from the last
stable path component:

```luau
local inventoryService = require(script.Parent.InventoryService)
```

Module tables can absorb single-owner function fields:

```luau
return {
    Start = function()
        -- recovered body
    end,
}
```

The output header reports recovered module dependencies and whether the main
prototype consistently exports a table, function, required module, or another
value. Dynamic require targets remain explicit expressions instead of receiving
an invented module path.

## Conservative barriers

Inlining is disabled when a closure is shared, escapes through an unknown sink,
has ambiguous captures, participates in control-flow merges, or cannot be tied
to a supported callback/module context. Table reconstruction still materializes
a pending module table before a captured dependency changes or a closure captures
the table itself.

The relevant API options are:

- `RecoverRobloxEvents` (default `true`)
- `InlineRobloxCallbacks` (default `true`)
- `RecoverRobloxModules` (default `true`)
