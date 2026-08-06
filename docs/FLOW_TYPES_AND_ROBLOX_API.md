# Flow-sensitive types and Roblox API

LunaUX Next 0.15 adds a point-sensitive type layer over CFG and SSA, plus a shared Roblox API signature catalog.

## Flow refinements

The analyzer keeps a base type for each SSA value and a separate narrowed type for each use site. Refinements propagate only through the matching CFG edge and are intersected at joins. Supported evidence includes:

- comparisons with `nil`;
- truthy and falsey branches for optional values;
- `type(value)` and `typeof(value)` string comparisons;
- validated `Instance:IsA("ClassName")` predicates;
- successful `assert(value)` calls.

A refinement is discarded at a merge unless every reachable predecessor supports a compatible fact. This prevents a type learned in one branch from leaking into its sibling or past the join.

## Roblox API catalog

The catalog contains conservative signatures for common services and engine classes, including Instance, BasePart, Player, Players, Humanoid, Workspace, UserInputService, RunService, CollectionService, TweenService, ContextActionService, RemoteEvent, BindableEvent, and value objects.

It provides service classes, owner-aware property and method types, signal callback parameter types, and callback contracts for action binding and render-step registration. Ambiguous members require owner evidence.

The catalog is a curated reconstruction aid rather than a complete or authoritative dump of every Roblox API member. Unknown, overloaded, or conflicting signatures deliberately fall back to existing heuristics or no annotation.

## Callback annotations

Inline closures from 0.14 receive API parameter types when the signal or callback position is recognized. Serialized debug types still take precedence. Shared or escaping callbacks remain named functions as before.

## Options

- `FlowSensitiveTypes` (default `true`)
- `RobloxAPITypes` (default `true`)

Both options require `InferTypes` for emitted annotations, but flow facts can still be included in `ShowRecoveredSymbols` reports.
