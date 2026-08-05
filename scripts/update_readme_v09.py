from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "README.md"
text = path.read_text(encoding="utf-8")

replacements = (
    (
        "> **Version 0.8:** adds versioned SSA values, predecessor-specific phi operands, use counts, and conservative single-use temporary elimination on top of the 0.7 control-flow and data-flow engine.",
        "> **Version 0.9:** adds a structured Luau expression AST, precedence-aware printing, and lexical scope recovery on top of the CFG and SSA engine.",
    ),
    (
        "- Eliminates safe adjacent single-use temporaries without duplicating evaluations or hiding named/typed debug locals.\n- Reconstructs common expressions, table access, calls, methods, returns, closures, numeric/generic loops, `while`/`repeat` regions, and `if`/`else` layouts using compatibility patterns plus whole-function CFG/SSA analysis.",
        "- Eliminates safe adjacent single-use temporaries without duplicating evaluations or hiding named/typed debug locals.\n- Represents recovered unary, binary, table, field, index, call, and method expressions as immutable AST nodes.\n- Prints Luau expressions with formal precedence and associativity, including safe nested unary rendering.\n- Reconstructs lexical scopes from debug ranges, including shadowing, register reuse, and typed bindings.\n- Reconstructs common expressions, table access, calls, methods, returns, closures, numeric/generic loops, `while`/`repeat` regions, and `if`/`else` layouts using compatibility patterns plus whole-function CFG/SSA analysis.",
    ),
    (
        "The compiler-analysis design is documented in [`docs/COMPILER_ANALYSIS.md`](docs/COMPILER_ANALYSIS.md), and the SSA/expression stage in [`docs/SSA_AND_EXPRESSIONS.md`](docs/SSA_AND_EXPRESSIONS.md).",
        "The compiler-analysis design is documented in [`docs/COMPILER_ANALYSIS.md`](docs/COMPILER_ANALYSIS.md), the SSA stage in [`docs/SSA_AND_EXPRESSIONS.md`](docs/SSA_AND_EXPRESSIONS.md), and the structured AST/scope stage in [`docs/AST_AND_SCOPES.md`](docs/AST_AND_SCOPES.md).",
    ),
)

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one README match, found {count}: {old[:60]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
