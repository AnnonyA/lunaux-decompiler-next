from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


structuring = ROOT / "src/lunaux/backends/structuring.py"
replace_once(
    structuring,
    "from collections.abc import Mapping, Sequence\n",
    "from collections.abc import Mapping\n",
)
replace_once(
    structuring,
    """def _phi_regions(program: SSAProgram) -> tuple[PhiIfRegion, ...]:\n""",
    """def _definitions_by_value(\n    program: SSAProgram,\n    instructions: tuple[DecodedInstruction, ...],\n) -> dict[SSAValue, DecodedInstruction] | None:\n    result: dict[SSAValue, DecodedInstruction] = {}\n    for instruction in instructions:\n        definitions = register_access(instruction).definitions\n        if len(definitions) != 1:\n            return None\n        register = next(iter(definitions))\n        value = program.value_defined_at(instruction.pc, register)\n        if value is None:\n            return None\n        result[value] = instruction\n    return result\n\n\ndef _phi_regions(program: SSAProgram) -> tuple[PhiIfRegion, ...]:\n""",
)
replace_once(
    structuring,
    """        then_by_value = {\n            program.value_defined_at(instruction.pc, next(iter(register_access(instruction).definitions))): instruction\n            for instruction in then_definitions\n        }\n        else_by_value = {\n            program.value_defined_at(instruction.pc, next(iter(register_access(instruction).definitions))): instruction\n            for instruction in else_definitions\n        }\n        if None in then_by_value or None in else_by_value:\n            continue\n""",
    """        then_by_value = _definitions_by_value(program, then_definitions)\n        else_by_value = _definitions_by_value(program, else_definitions)\n        if then_by_value is None or else_by_value is None:\n            continue\n""",
)

lifter = ROOT / "src/lunaux/backends/lifter.py"
replace_once(
    lifter,
    """        annotated = f\"{name}: {type_name}\" if type_name and type_name != \"any\" else name\n        prefix = \"\" if name in self.declared else \"local \"\n        self.out.line(\n            f\"{prefix}{annotated} = {render_expression(expression)}\",\n            statement=True,\n        )\n""",
    """        annotated = f\"{name}: {type_name}\" if type_name and type_name != \"any\" else name\n        is_new = name not in self.declared\n        lhs = annotated if is_new else name\n        prefix = \"local \" if is_new else \"\"\n        self.out.line(\n            f\"{prefix}{lhs} = {render_expression(expression)}\",\n            statement=True,\n        )\n""",
)
replace_once(
    lifter,
    """    def _boolean_chain_expression(self, condition_pcs: tuple[int, ...], operator: str) -> Expr | None:\n""",
    """    def _boolean_chain_expression(\n        self,\n        condition_pcs: tuple[int, ...],\n        operator: str,\n    ) -> Expr | None:\n""",
)
replace_once(
    lifter,
    """        pc = instruction.pc\n        success = False\n""",
    """        pc = instruction.pc\n        target = table_write_target_register(instruction)\n        if (\n            target is not None\n            and instruction.name != \"SETLIST\"\n            and instruction.a == target\n        ):\n            self._flush_pending_table(pending)\n            return False\n        if instruction.name == \"SETLIST\" and instruction.c > 0:\n            count = instruction.c - 1\n            if target is not None and target in range(\n                instruction.b,\n                instruction.b + count,\n            ):\n                self._flush_pending_table(pending)\n                return False\n        success = False\n""",
)

reconstructed = ROOT / "src/lunaux/backends/reconstructed.py"
replace_once(
    reconstructed,
    '    """Portable reconstruction with CFG, SSA, structured conditions, phi recovery, and table literals."""\n',
    '    """Portable reconstruction with structured CFG, SSA, phi, and table recovery."""\n',
)
