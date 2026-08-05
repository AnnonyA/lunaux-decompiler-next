from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(
            f"Expected one match in {path}, found {text.count(old)}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "src/lunaux/backends/ssa.py",
        "        for values in self.phis_by_block.values():\n"
        "            values.sort(key=lambda item: item.register)\n",
        "        for phi_builders in self.phis_by_block.values():\n"
        "            phi_builders.sort(key=lambda item: item.register)\n",
    )
    replace_once(
        "src/lunaux/backends/ssa.py",
        "        for values in self.children.values():\n"
        "            values.sort(key=lambda block: order.get(block, len(order)))\n",
        "        for child_blocks in self.children.values():\n"
        "            child_blocks.sort(\n"
        "                key=lambda block: order.get(block, len(order))\n"
        "            )\n",
    )
    replace_once(
        "src/lunaux/backends/inlining.py",
        "from collections import defaultdict\n",
        "import re\n"
        "from collections import defaultdict\n",
    )
    replace_once(
        "src/lunaux/backends/inlining.py",
        "_SUPPORTED_CONSUMERS = frozenset(\n",
        "_ATOMIC_EXPRESSION = re.compile(\n"
        "    r'^(?:nil|true|false|-?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?'\n"
        "    r'|\"(?:\\\\.|[^\"\\\\])*\"|[A-Za-z_][A-Za-z0-9_]*)$'\n"
        ")\n"
        "_SUPPORTED_CONSUMERS = frozenset(\n",
    )
    replace_once(
        "src/lunaux/backends/inlining.py",
        "def parenthesize_inlined_expression(expression: str) -> str:\n"
        "    stripped = expression.strip()\n"
        "    if stripped.startswith(\"(\") and stripped.endswith(\")\"):\n"
        "        return stripped\n"
        "    return f\"({stripped})\"\n",
        "def parenthesize_inlined_expression(expression: str) -> str:\n"
        "    stripped = expression.strip()\n"
        "    if _ATOMIC_EXPRESSION.fullmatch(stripped):\n"
        "        return stripped\n"
        "    if stripped.startswith(\"(\") and stripped.endswith(\")\"):\n"
        "        return stripped\n"
        "    return f\"({stripped})\"\n",
    )
    replace_once(
        "tests/test_bytecode_engine.py",
        "    assert 'local v1 = \"hello\"' in source\n"
        "    assert \"v0(v1)\" in source\n",
        "    assert 'local v1 = \"hello\"' not in source\n"
        "    assert 'v0(\"hello\")' in source\n",
    )
    replace_once(
        "tests/test_bytecode_engine.py",
        "    assert \"v0(v1);\" in source\n",
        "    assert 'v0(\"hello\");' in source\n",
    )
    replace_once(
        "tests/test_bytecode_engine.py",
        "    assert \"local v0 = 42\" in source\n"
        "    assert \"return v0\" in source\n",
        "    assert \"local v0 = 42\" not in source\n"
        "    assert \"return 42\" in source\n",
    )
    replace_once(
        "tests/test_lifter_inlining.py",
        "    assert \"return (42)\" in source\n",
        "    assert \"return 42\" in source\n",
    )
    replace_once(
        "tests/test_lifter_inlining.py",
        "    assert \"return (-(4))\" in source\n",
        "    assert \"return -4\" in source\n",
    )
    replace_once(
        "tests/test_inlining.py",
        "def test_parenthesizes_once() -> None:\n"
        "    assert parenthesize_inlined_expression(\"a + b\") == \"(a + b)\"\n"
        "    assert parenthesize_inlined_expression(\"(a + b)\") == \"(a + b)\"\n",
        "def test_parenthesizes_only_compound_expressions() -> None:\n"
        "    assert parenthesize_inlined_expression(\"42\") == \"42\"\n"
        "    assert parenthesize_inlined_expression('\\\"hello\\\"') == '\\"hello\\\"'\n"
        "    assert parenthesize_inlined_expression(\"value\") == \"value\"\n"
        "    assert parenthesize_inlined_expression(\"a + b\") == \"(a + b)\"\n"
        "    assert parenthesize_inlined_expression(\"(a + b)\") == \"(a + b)\"\n",
    )
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
