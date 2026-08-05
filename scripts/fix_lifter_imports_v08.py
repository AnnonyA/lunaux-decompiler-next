from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/lunaux/backends/lifter.py"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    old = '''from lunaux.backends.analysis import analyze_control_flow
from lunaux.backends.inlining import (
    parenthesize_inlined_expression,
    plan_expression_inlining,
)
from lunaux.backends.ssa import SSAValue, build_ssa
from lunaux.backends.bytecode import (
    ClassShapeConstant,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
    format_type_tag,
)
from lunaux.backends.opcodes import (
    DecodedInstruction,
    builtin_name,
    decode_words,
    get_jump_target,
)
'''
    new = '''from lunaux.backends.analysis import analyze_control_flow
from lunaux.backends.bytecode import (
    ClassShapeConstant,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
    format_type_tag,
)
from lunaux.backends.inlining import (
    parenthesize_inlined_expression,
    plan_expression_inlining,
)
from lunaux.backends.opcodes import (
    DecodedInstruction,
    builtin_name,
    decode_words,
    get_jump_target,
)
from lunaux.backends.ssa import SSAValue, build_ssa
'''
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one import block, found {text.count(old)}")
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
