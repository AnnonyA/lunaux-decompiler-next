from __future__ import annotations

from pathlib import Path

path = Path(__file__).resolve().parents[1] / "src/lunaux/backends/lifter.py"
text = path.read_text(encoding="utf-8")

old = '''        value = self.ssa.value_at_use(pc, register)
        child = self.pending_tables.get(value) if value is not None else None
        if child is owner:
'''
new = '''        value = self.ssa.value_at_use(pc, register)
        expression: Expr
        child = self.pending_tables.get(value) if value is not None else None
        if child is owner:
'''
if old in text:
    text = text.replace(old, new, 1)
elif "        expression: Expr\n        child =" not in text:
    raise RuntimeError("expression annotation marker not found")

old = '''        elif instruction.name == "SETLIST" and instruction.c == 0:
            captured = self.pending_open_table_values.pop(instruction.b, None)
            if captured is not None and captured[2] == pc:
                value, dependencies, _consumer_pc = captured
'''
new = '''        elif instruction.name == "SETLIST" and instruction.c == 0:
            open_captured = self.pending_open_table_values.pop(
                instruction.b,
                None,
            )
            if open_captured is not None and open_captured[2] == pc:
                value, dependencies, _consumer_pc = open_captured
'''
if old in text:
    text = text.replace(old, new, 1)
elif "open_captured = self.pending_open_table_values.pop" not in text:
    raise RuntimeError("open tail capture marker not found")

path.write_text(text, encoding="utf-8")
print("fixed v0.13 mypy local inference")
