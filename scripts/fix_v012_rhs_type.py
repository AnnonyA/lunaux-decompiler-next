from __future__ import annotations

from pathlib import Path

path = Path(__file__).resolve().parents[1] / "src/lunaux/backends/lifter.py"
text = path.read_text(encoding="utf-8")
old = '''        if name.startswith("JUMPXEQK"):
            if name == "JUMPXEQKNIL":
                rhs = LiteralExpr("nil")
            elif name == "JUMPXEQKB":
                rhs = LiteralExpr("true" if (instruction.aux or 0) & 1 else "false")
            else:
                rhs: Expr = source_expr(
'''
new = '''        if name.startswith("JUMPXEQK"):
            rhs: Expr
            if name == "JUMPXEQKNIL":
                rhs = LiteralExpr("nil")
            elif name == "JUMPXEQKB":
                rhs = LiteralExpr("true" if (instruction.aux or 0) & 1 else "false")
            else:
                rhs = source_expr(
'''
if text.count(old) != 1:
    raise RuntimeError(f"expected one rhs block, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
