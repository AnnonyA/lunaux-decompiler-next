from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src/lunaux/backends/symbols.py"
text = path.read_text(encoding="utf-8")

replacements = (
    (
        "        elif name in {\"GETTABLEKS\", \"GETUDATAKS\"}:\n"
        "            index = (\n"
        "                instruction.userdata_constant_index\n"
        "                if name == \"GETUDATAKS\"\n"
        "                else instruction.aux\n"
        "            )\n"
        "            key = _constant_string(proto, index if index is not None else -1)\n",
        "        elif name in {\"GETTABLEKS\", \"GETUDATAKS\"}:\n"
        "            field_index = (\n"
        "                instruction.userdata_constant_index\n"
        "                if name == \"GETUDATAKS\"\n"
        "                else instruction.aux\n"
        "            )\n"
        "            key = _constant_string(\n"
        "                proto,\n"
        "                field_index if field_index is not None else -1,\n"
        "            )\n",
    ),
    (
        "                for candidate in reversed(instructions):\n"
        "                    if candidate.pc >= pc:\n"
        "                        continue\n"
        "                    if candidate.name in {\n",
        "                for previous_instruction in reversed(instructions):\n"
        "                    if previous_instruction.pc >= pc:\n"
        "                        continue\n"
        "                    if previous_instruction.name in {\n",
    ),
    (
        "                        candidate.name in {\"NAMECALL\", \"NAMECALLUDATA\"}\n"
        "                        and candidate.a == instruction.a\n"
        "                    ):\n"
        "                        previous = candidate\n",
        "                        previous_instruction.name\n"
        "                        in {\"NAMECALL\", \"NAMECALLUDATA\"}\n"
        "                        and previous_instruction.a == instruction.a\n"
        "                    ):\n"
        "                        previous = previous_instruction\n",
    ),
    (
        "                    candidate = _Candidate(base, 36, \"untyped parameter family\")\n",
        "                    generated_name = _Candidate(\n"
        "                        base,\n"
        "                        36,\n"
        "                        \"untyped parameter family\",\n"
        "                    )\n",
    ),
    (
        "                    candidate = _Candidate(\n"
        "                        f\"{family_base}{suffix}\",\n"
        "                        58,\n",
        "                    generated_name = _Candidate(\n"
        "                        f\"{family_base}{suffix}\",\n"
        "                        58,\n",
    ),
    (
        "                candidate = _Candidate(\n"
        "                    f\"{family_base}{suffix}\",\n"
        "                    48,\n",
        "                generated_name = _Candidate(\n"
        "                    f\"{family_base}{suffix}\",\n"
        "                    48,\n",
    ),
    (
        "                candidate = _Candidate(f\"var{generic_count}\", 20, \"generic fallback\", True)\n"
        "            best_name = candidate\n",
        "                generated_name = _Candidate(\n"
        "                    f\"var{generic_count}\",\n"
        "                    20,\n"
        "                    \"generic fallback\",\n"
        "                    True,\n"
        "                )\n"
        "            best_name = generated_name\n",
    ),
)

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match, found {count}: {old[:90]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
