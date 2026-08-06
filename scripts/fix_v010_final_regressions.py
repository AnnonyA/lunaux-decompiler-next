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
    "        else:\n            entry_names[register] = f\"arg{register + 1}\"\n",
    "        else:\n"
    "            argument_count += 1\n"
    "            entry_names[register] = f\"arg{argument_count}\"\n",
)

bytecode_tests = ROOT / "tests/test_bytecode_engine.py"
replace_once(bytecode_tests, "assert 'v0(\"hello\")' in source", "assert 'print(\"hello\")' in source")
replace_once(
    bytecode_tests,
    "assert 'v0(\"hello\");' in source",
    "assert 'print(\"hello\");' in source",
)

inlining_tests = ROOT / "tests/test_lifter_inlining.py"
replace_once(inlining_tests, 'assert "return v0" in source', 'assert "return num1" in source')
replace_once(
    inlining_tests,
    'assert "return v0 + v0" in source',
    'assert "return num1 + num1" in source',
)
