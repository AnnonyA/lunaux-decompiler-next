# Pure-Python Luau engine

LunaUX Next 0.6 contains a static container parser, instruction decoder, enriched disassembler, and conservative source lifter implemented in Python.

## Official-format coverage

The implementation is aligned with the current public Luau definitions in:

- `Common/include/Luau/Bytecode.h`
- `Common/include/Luau/BytecodeUtils.h`
- `Bytecode/src/BytecodeBuilder.cpp`
- `VM/src/lvmload.cpp`

Supported serialized versions:

- standard bytecode versions 3 through 13;
- current experimental class bytecode version 100;
- type-information versions 1 through 3.

The parser understands all current constant tags: nil, boolean, number, string, import, table shape, closure, float vector, table-with-constants, 64-bit integer, class shape, and double-precision vector.

## Metadata recovery

The parser preserves:

- string and userdata-type tables;
- prototype headers, flags, serialized size, and estimated cost;
- instruction words and AUX words;
- constants and child-prototype links;
- definition lines and per-instruction line data;
- debug locals and upvalue names;
- structured function type bytes;
- typed upvalues and typed local ranges;
- feedback slots used by `CALLFB`;
- the selected main prototype.

## Instruction coverage

The decoder contains the complete current 90-opcode table through `NEWCLASS`. It records the official instruction encoding, AUX requirement, minimum bytecode version, fallthrough behavior, loop classification, jump-target rule, and modern builtin IDs used by `FASTCALL*`.

Strict container validation rejects:

- unknown or version-incompatible opcodes;
- missing AUX words;
- jumps into AUX data or outside a prototype;
- invalid constant, prototype, child, feedback, local, and type references;
- malformed closure capture sequences;
- oversized collections and truncated variable integers.

## Source lifting

Commonly reconstructed forms include:

- locals, globals, imports, upvalues, constants, and typed declarations;
- arithmetic, floor division, boolean selection, unary operations, length, and concatenation;
- table creation and indexed/named/list writes;
- function calls, method calls, feedback calls, varargs, and returns;
- child closures and captures;
- numeric and generic loops;
- common forward `if`/`else` layouts;
- simple `while` and `repeat until` regions;
- userdata fields and methods using the correct low-16-bit constant index;
- conservative class creation/member registration descriptions;
- builtin-aware optimized-call comments.

The disassembler exposes more detail than the source lifter when high-level reconstruction is ambiguous. It resolves constants, import paths, property names, cache slots, jump targets, builtins, feedback IDs, proto IDs, class shapes, flags, type metadata, and debug ranges.

## Upstream drift check

`scripts/check_luau_bytecode_spec.py` compares the local opcode ordering, constant tags, builtin count, and supported version range against an upstream `Bytecode.h`. A scheduled GitHub Actions workflow runs this check so a future Luau format change is visible instead of silently misdecoded.

## Limitations

A decompiler cannot recover information absent from bytecode. Comments, exact formatting, many temporary names, and some original source structures are permanently lost. Complex optimized or irreducible control flow may be emitted as labels or explanatory comments rather than fabricated source.

Parsing and lifting are static; submitted Luau bytecode is never executed.
