from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old in text:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    if new in text:
        return
    raise RuntimeError(f"missing old and new text in {path}: {old[:80]!r}")


lifter = ROOT / "src/lunaux/backends/lifter.py"
replace_once(
    lifter,
    "from lunaux.backends.analysis import analyze_control_flow\n"
    "from lunaux.backends.classes import recover_classes\n"
    "from lunaux.backends.ast import (",
    "from lunaux.backends.analysis import analyze_control_flow\n"
    "from lunaux.backends.ast import (",
)
replace_once(
    lifter,
    "    format_type_tag,\n)\nfrom lunaux.backends.inlining import plan_expression_inlining\n",
    "    format_type_tag,\n)\n"
    "from lunaux.backends.classes import recover_classes\n"
    "from lunaux.backends.inlining import plan_expression_inlining\n",
)

symbols = ROOT / "src/lunaux/backends/symbols.py"
replace_once(
    symbols,
    "from collections.abc import Mapping, Sequence\n",
    "from collections.abc import Iterable, Mapping, Sequence\n",
)
replace_once(
    symbols,
    "def _best(values: object) -> _Candidate | None:\n"
    "    candidates = list(values)  # type: ignore[arg-type]\n",
    "def _best(values: Iterable[_Candidate]) -> _Candidate | None:\n"
    "    candidates = list(values)\n",
)
replace_once(
    symbols,
    "            elif method in {\"FindFirstChildOfClass\", \"FindFirstChildWhichIsA\"} and instruction.b > 2:\n",
    "            elif (\n"
    "                method in {\"FindFirstChildOfClass\", \"FindFirstChildWhichIsA\"}\n"
    "                and instruction.b > 2\n"
    "            ):\n",
)
replace_once(
    symbols,
    "                path = value_path(function_value)\n"
    "                return_type = _direct_call_type(path)\n",
    "                call_path = value_path(function_value)\n"
    "                return_type = _direct_call_type(call_path)\n",
)
replace_once(
    symbols,
    "            value = program.value_at_use(instruction.pc, instruction.a)\n"
    "            symbol = symbols.get(value) if value is not None else None\n",
    "            return_value = program.value_at_use(instruction.pc, instruction.a)\n"
    "            symbol = (\n"
    "                symbols.get(return_value) if return_value is not None else None\n"
    "            )\n",
)
replace_once(
    symbols,
    "            return _constant_string(proto, instruction.aux or -1)\n",
    "            index = instruction.aux if instruction.aux is not None else -1\n"
    "            return _constant_string(proto, index)\n",
)
replace_once(
    symbols,
    "            key = _constant_string(proto, instruction.aux or -1)\n",
    "            index = instruction.aux if instruction.aux is not None else -1\n"
    "            key = _constant_string(proto, index)\n",
)

classes = ROOT / "src/lunaux/backends/classes.py"
replace_once(
    classes,
    "from lunaux.backends.ssa import SSAProgram, SSAValue\n\n\n@dataclass",
    "from lunaux.backends.ssa import SSAProgram, SSAValue\n\n"
    "ClassValueDetails = tuple[\n"
    "    DecodedInstruction,\n"
    "    str,\n"
    "    tuple[str, ...],\n"
    "    tuple[str, ...],\n"
    "]\n\n\n@dataclass",
)
replace_once(
    classes,
    "    class_values: dict[SSAValue, tuple[DecodedInstruction, str, tuple[str, ...], tuple[str, ...]]] = {}\n",
    "    class_values: dict[SSAValue, ClassValueDetails] = {}\n",
)
replace_once(
    classes,
    "        key = _constant_string(proto, instruction.aux or -1) or f\"member_{instruction.pc}\"\n",
    "        key_index = instruction.aux if instruction.aux is not None else -1\n"
    "        key = _constant_string(proto, key_index) or f\"member_{instruction.pc}\"\n",
)
replace_once(
    classes,
    "    for value, details in class_values.items():\n"
    "        instruction, class_name, properties, shape_methods = details\n"
    "        recovered_methods = methods_by_class[value]\n",
    "    for class_value, class_details in class_values.items():\n"
    "        instruction, class_name, properties, shape_methods = class_details\n"
    "        recovered_methods = methods_by_class[class_value]\n",
)
