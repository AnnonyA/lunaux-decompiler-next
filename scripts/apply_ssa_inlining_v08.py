from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/lunaux/backends/lifter.py"


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one lifter match, found {text.count(old)}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from lunaux.backends.analysis import analyze_control_flow\n",
        "from lunaux.backends.analysis import analyze_control_flow\n"
        "from lunaux.backends.inlining import (\n"
        "    parenthesize_inlined_expression,\n"
        "    plan_expression_inlining,\n"
        ")\n"
        "from lunaux.backends.ssa import SSAValue, build_ssa\n",
    )
    text = replace_once(
        text,
        "    preserve_for_step: bool\n\n"
        "    @classmethod\n",
        "    preserve_for_step: bool\n"
        "    inline_single_use_temporaries: bool\n\n"
        "    @classmethod\n",
    )
    text = replace_once(
        text,
        "            preserve_for_step=options.get(\"PreserveForStep\", False),\n"
        "        )\n",
        "            preserve_for_step=options.get(\"PreserveForStep\", False),\n"
        "            inline_single_use_temporaries=options.get(\n"
        "                \"InlineSingleUseTemporaries\",\n"
        "                True,\n"
        "            ),\n"
        "        )\n",
    )
    text = replace_once(
        text,
        "        self.analysis = analyze_control_flow(self.instructions, len(proto.code))\n"
        "        self.instruction_by_pc = {\n",
        "        self.analysis = analyze_control_flow(self.instructions, len(proto.code))\n"
        "        self.ssa = build_ssa(\n"
        "            self.instructions,\n"
        "            len(proto.code),\n"
        "            analysis=self.analysis,\n"
        "        )\n"
        "        self.inline_plan = plan_expression_inlining(self.ssa, proto)\n"
        "        self.inline_expressions: dict[SSAValue, str] = {}\n"
        "        self.instruction_by_pc = {\n",
    )
    text = replace_once(
        text,
        "    def _ref(self, register: int, pc: int) -> str:\n"
        "        return self._name(register, pc)\n\n",
        "    def _ref(self, register: int, pc: int) -> str:\n"
        "        if self.options.inline_single_use_temporaries:\n"
        "            value = self.ssa.value_at_use(pc, register)\n"
        "            if value is not None:\n"
        "                expression = self.inline_expressions.get(value)\n"
        "                if expression is not None:\n"
        "                    return parenthesize_inlined_expression(expression)\n"
        "        return self._name(register, pc)\n\n",
    )
    text = replace_once(
        text,
        "    def _assign(self, register: int, expression: str, pc: int) -> None:\n"
        "        name = self._name(register, pc)\n",
        "    def _assign(self, register: int, expression: str, pc: int) -> None:\n"
        "        value = self.ssa.value_defined_at(pc, register)\n"
        "        if (\n"
        "            self.options.inline_single_use_temporaries\n"
        "            and value is not None\n"
        "            and self.inline_plan.should_inline(value)\n"
        "        ):\n"
        "            self.inline_expressions[value] = expression\n"
        "            self.register_names.setdefault(register, f\"v{register}\")\n"
        "            return\n"
        "        name = self._name(register, pc)\n",
    )
    TARGET.write_text(text, encoding="utf-8")
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
