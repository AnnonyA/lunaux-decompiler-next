from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one README match, found {text.count(old)}")
    return text.replace(old, new, 1)


def main() -> None:
    text = README.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "> **Version 0.6:** synchronizes the open engine with the current official "
        "Luau bytecode specification: standard bytecode versions 3–13, experimental "
        "class bytecode version 100, the complete 90-opcode table, structured type "
        "metadata, double-precision vectors, classes, userdata field opcodes, feedback "
        "slots, and stricter validation.",
        "> **Version 0.7:** adds compiler-grade control-flow and data-flow analysis on "
        "top of the complete Luau bytecode v3–v13/v100 decoder. The Python engine now "
        "builds basic blocks, dominators, postdominators, natural loops, liveness, "
        "reaching definitions, def-use chains, and pruned SSA phi placement.",
    )
    text = replace_once(
        text,
        "- Reconstructs common expressions, table access, calls, methods, returns, "
        "closures, numeric/generic loops, simple `while`/`repeat` regions, and common "
        "`if`/`else` layouts.\n"
        "- Resolves modern userdata, class, fastcall, feedback, and proto operands in "
        "disassembly.\n",
        "- Builds an AUX-aware control-flow graph with dominators, postdominators, "
        "dominance frontiers, branch joins, natural loops, and strongly connected "
        "components.\n"
        "- Computes register liveness, reaching definitions, reverse def-use chains, "
        "and conservative SSA phi placement.\n"
        "- Reconstructs common expressions, table access, calls, methods, returns, "
        "closures, numeric/generic loops, `while`/`repeat` regions, and `if`/`else` "
        "layouts using both compatibility patterns and whole-function CFG analysis.\n"
        "- Resolves modern userdata, class, fastcall, feedback, and proto operands in "
        "disassembly.\n",
    )
    text = replace_once(
        text,
        "The repository also checks its opcode, constant, builtin, and bytecode-version "
        "metadata against the current upstream `Luau/Bytecode.h` on a schedule. See "
        "[`scripts/check_luau_bytecode_spec.py`](scripts/check_luau_bytecode_spec.py).",
        "The repository also checks its opcode, constant, builtin, and bytecode-version "
        "metadata against the current upstream `Luau/Bytecode.h` on a schedule. See "
        "[`scripts/check_luau_bytecode_spec.py`](scripts/check_luau_bytecode_spec.py). "
        "The compiler-analysis design and public API are documented in "
        "[`docs/COMPILER_ANALYSIS.md`](docs/COMPILER_ANALYSIS.md).",
    )
    README.write_text(text, encoding="utf-8")
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
