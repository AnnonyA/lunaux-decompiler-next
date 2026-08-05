from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src/lunaux/backends/lifter.py"
text = path.read_text(encoding="utf-8")
old = (
    "    def _lift_instruction(self, instruction: DecodedInstruction) -> None:\n"
    "        name = instruction.name\n"
    "        pc = instruction.pc\n"
)
new = old + "        expression: Expr | str\n"
count = text.count(old)
if count != 1:
    raise RuntimeError(f"expected one _lift_instruction header, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
