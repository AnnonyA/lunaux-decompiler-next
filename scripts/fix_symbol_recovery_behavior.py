from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


symbols = ROOT / "src/lunaux/backends/symbols.py"
replace_once(
    symbols,
    "        elif name in {\"CALL\", \"CALLFB\"}:\n"
    "            previous = previous_by_next_pc.get(pc)\n"
    "            method: str | None = None\n",
    "        elif name in {\"CALL\", \"CALLFB\"}:\n"
    "            previous = previous_by_next_pc.get(pc)\n"
    "            if (\n"
    "                previous is None\n"
    "                or previous.name not in {\"NAMECALL\", \"NAMECALLUDATA\"}\n"
    "                or previous.a != instruction.a\n"
    "            ):\n"
    "                previous = None\n"
    "                for candidate in reversed(instructions):\n"
    "                    if candidate.pc >= pc:\n"
    "                        continue\n"
    "                    if candidate.name in {\n"
    "                        \"CALL\",\n"
    "                        \"CALLFB\",\n"
    "                        \"RETURN\",\n"
    "                        \"JUMP\",\n"
    "                        \"JUMPBACK\",\n"
    "                        \"JUMPX\",\n"
    "                    }:\n"
    "                        break\n"
    "                    if (\n"
    "                        candidate.name in {\"NAMECALL\", \"NAMECALLUDATA\"}\n"
    "                        and candidate.a == instruction.a\n"
    "                    ):\n"
    "                        previous = candidate\n"
    "                        break\n"
    "            method: str | None = None\n",
)
replace_once(
    symbols,
    "    family_counts: defaultdict[str, int] = defaultdict(int)\n"
    "    generic_count = 0\n",
    "    family_counts: defaultdict[str, int] = defaultdict(int)\n"
    "    argument_count = 0\n"
    "    generic_count = 0\n",
)
replace_once(
    symbols,
    "                if family is None:\n"
    "                    base = f\"arg{value.register + 1}\"\n"
    "                    candidate = _Candidate(base, 36, \"parameter position\")\n",
    "                if family is None:\n"
    "                    argument_count += 1\n"
    "                    base = f\"arg{argument_count}\"\n"
    "                    candidate = _Candidate(base, 36, \"untyped parameter family\")\n",
)

bytecode_tests = ROOT / "tests/test_bytecode_engine.py"
replace_once(bytecode_tests, 'assert "local v0 = print" in source', 'assert "local print = print" in source')
replace_once(bytecode_tests, 'assert "local v0 = print;" in source', 'assert "local print = print;" in source')
replace_once(
    bytecode_tests,
    'assert "local v0: string = 5" in decompile_module(module, {}, "typed")',
    'assert "local str1: string = 5" in decompile_module(module, {}, "typed")',
)

inlining_tests = ROOT / "tests/test_lifter_inlining.py"
replace_once(inlining_tests, 'assert "local v0 = 42" in source', 'assert "local num1: number = 42" in source')
replace_once(inlining_tests, 'assert "local answer = 42" in source', 'assert "local answer: number = 42" in source')
replace_once(inlining_tests, 'assert "local v0 = 2" in source', 'assert "local num1: number = 2" in source')

recovery_tests = ROOT / "tests/test_symbol_recovery.py"
replace_once(recovery_tests, '        3: "arg4",', '        3: "arg1",')
