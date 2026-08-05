# Pure-Python Luau engine

LunaUX Next 0.4 includes a static parser, enriched disassembler, and heuristic source lifter implemented in Python. It is used when the native `luna` extension is unavailable or when `LUNAUX_BACKEND_MODE=reconstructed` is selected.

## Input parsing

The parser follows the serialized bytecode layout used by the public Luau VM implementation. It reads:

- bytecode and type-information versions;
- the global string table;
- prototype headers and instruction words;
- nil, boolean, number, string, import, table, closure, vector, integer, class-shape, and extended table constants;
- child-prototype references;
- source line data;
- local-variable and upvalue names when debug data is present;
- feedback slots and newer prototype metadata.

The implementation understands the public format layouts for bytecode versions 3 through 12. Unknown versions, malformed variable integers, invalid references, oversized collections, and truncated files are rejected without executing the supplied bytecode.

Reference implementation paths in the Luau project:

- `Common/include/Luau/Bytecode.h`
- `VM/src/lvmload.cpp`

## Source reconstruction

The lifter currently reconstructs common forms of:

- constants, locals, globals, imports, and upvalues;
- arithmetic, boolean, unary, length, and concatenation expressions;
- table creation, indexed fields, named fields, and list writes;
- regular calls and method calls;
- return values and varargs;
- closures and child prototypes;
- conditional regions from forward conditional jumps;
- numeric and generic loops when their bytecode layout is recognizable;
- line, function, local, and upvalue metadata.

The disassembler additionally resolves constants, import paths, property names, line numbers, and jump targets.

## Limitations

A decompiler cannot recover information that was not preserved in bytecode. Comments, original formatting, many temporary-variable names, and some high-level source choices are permanently lost.

The Python lifter is intentionally conservative. Complex irreducible control flow, optimized fast calls, unusual compiler transformations, and newly introduced opcodes may be rendered with labels or explanatory comments instead of guessed source. A compatible native backend remains available for patterns not yet handled by the open engine.

## Safety model

Parsing and lifting are static operations. LunaUX Next never loads the submitted bytecode into the Luau VM and never executes it. Collection sizes and references are bounded and validated before use.

Only inspect bytecode you own or are authorized to analyze.
