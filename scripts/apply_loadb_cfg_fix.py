from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/lunaux/backends/analysis.py"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    old = (
        "        and (instruction.name not in _TERMINATOR_NAMES)\n"
        "        and (target is None or is_fallthrough(instruction.opcode))\n"
    )
    new = (
        "        and (instruction.name not in _TERMINATOR_NAMES)\n"
        "        and not (instruction.name == \"LOADB\" and instruction.c)\n"
        "        and (target is None or is_fallthrough(instruction.opcode))\n"
    )
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one LOADB successor match, found {text.count(old)}")
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
