from __future__ import annotations

from pathlib import Path


path = Path("README.md")
text = path.read_text(encoding="utf-8")
old_banner = (
    "> **Version 0.15:** adds flow-sensitive narrowing and an owner-aware Roblox API "
    "catalog for properties, methods, services, events, and callback parameter types on "
    "top of the 0.14 callback/module pass."
)
new_banner = (
    "> **Version 0.16:** recovers conservative classes built from tables and metatables, "
    "and derives function names, parameter roles, types, and return hints from assignment "
    "and callback context."
)
if old_banner not in text:
    raise SystemExit("README version banner marker not found")
text = text.replace(old_banner, new_banner, 1)

old_highlight = (
    "- Reconstructs supported v100 `NEWCLASS` and `NEWCLASSMEMBER` regions as Luau "
    "`class ... end` declarations."
)
new_highlights = "\n".join(
    (
        old_highlight,
        "- Recovers conservative table/metatable classes from self `__index`, named closure members, constructors, instance methods, static methods, and metamethods.",
        "- Assigns contextual function names and parameter roles from class membership, table/global assignment, return position, and recognized callback contracts.",
        "- Keeps contextual parameter names stable throughout function bodies, including typed Roblox callbacks such as `input: InputObject` and `processed: boolean`.",
    )
)
if old_highlight not in text:
    raise SystemExit("README class highlight marker not found")
text = text.replace(old_highlight, new_highlights, 1)

start = text.index("### Class recovery\n")
end = text.index("> Bytecode does not retain comments", start)
section = '''### Metatable classes and contextual functions

Version 0.16 extends the existing experimental v100 class recovery to conservative table/metatable patterns. A table is folded only when SSA traces a self-referential `Class.__index = Class`, named closure members, and no dynamic member key that could change the recovered surface.

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

Members are classified as constructors, instance methods, static methods, or metamethods. Reads and writes through `self` contribute conservative property declarations. Shared closures, computed keys, conflicting assignments, and dynamic metatables retain ordinary table/function output.

The contextual function pass also derives names, parameter roles, parameter types, and return hints from class membership, named field/global assignment, return position, and recognized callback sinks. Contextual names are installed before lifting the body, so a callback rendered as `function(input: InputObject)` consistently references `input` inside the function.

Use `RecoverMetatableClasses` and `ContextualFunctions` to disable either extension independently. `RecoverClasses` remains the parent switch for all class reconstruction. See [`docs/METATABLE_CLASSES_AND_CONTEXTUAL_FUNCTIONS.md`](docs/METATABLE_CLASSES_AND_CONTEXTUAL_FUNCTIONS.md).

### Experimental bytecode classes

When a validated v100 class shape and member binding uses `NEWCLASS` and `NEWCLASSMEMBER`, LunaUX continues to emit the same shared class model as Luau `class ... end` syntax. Unsupported or ambiguous class regions retain the conservative compatibility representation.

'''
text = text[:start] + section + text[end:]
path.write_text(text, encoding="utf-8")
