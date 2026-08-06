from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


readme = ROOT / "README.md"
replace_once(
    readme,
    "> **Version 0.9:** adds a structured Luau expression AST, precedence-aware printing, and lexical scope recovery on top of the CFG and SSA engine.\n",
    "> **Version 0.10:** adds evidence-based symbol recovery, generated type families, conservative type inference, recovered function signatures, and Luau class reconstruction.\n",
)
replace_once(
    readme,
    "- Reconstructs lexical scopes from debug ranges, including shadowing, register reuse, and typed bindings.\n",
    "- Reconstructs lexical scopes from debug ranges, including shadowing, register reuse, and typed bindings.\n"
    "- Recovers symbol names from debug metadata, SSA relationships, imports, fields, prototype bindings, and Roblox API call evidence.\n"
    "- Generates stable type-family names such as `num1`, `bool1`, `str1`, `arg1`, `vec1`, and `buf1` when original names are absent.\n"
    "- Infers conservative parameter, local, and return types from serialized type metadata plus data flow and known operation contracts.\n"
    "- Reconstructs supported v100 `NEWCLASS` and `NEWCLASSMEMBER` regions as Luau `class ... end` declarations.\n",
)
replace_once(
    readme,
    "## Quick start\n",
    "## Recovery quality\n\n"
    "### Latest bytecode\n\n"
    "Reads official serialized Luau bytecode v3 through v13, retained type metadata v1 through v3, and the current experimental v100 class format. Roblox opcode-byte encoding used by some clients is normalized conservatively before validation.\n\n"
    "```text\n"
    "bytecode v12 · types v3\n"
    "```\n\n"
    "### Generated names\n\n"
    "Names are selected from evidence instead of register position alone. Debug locals and prototype names have the highest priority, followed by imports, fields, string arguments to calls such as `GetService`, SSA copies, and inferred type families.\n\n"
    "```text\n"
    "num1 · bool1 · str1 · arg1 · vec1 · buf1\n"
    "```\n\n"
    "For example, a validated `game:GetService(\"Players\")` result can be named `Players`, while a typed unnamed parameter can become `player: Player` or `num1: number`. Set `ShowRecoveredSymbols` to `true` to emit the SSA value, selected name/type, and the strongest evidence as comments in reconstructed output.\n\n"
    "### Types and inference\n\n"
    "Serialized parameter/local types are preserved. Missing types are inferred conservatively from constants, numeric/string/table opcodes, property reads, known Luau builtins, selected Roblox method contracts, moves, and SSA merges. Function return annotations are emitted only when the observed return paths agree.\n\n"
    "```luau\n"
    "local function func(\n"
    "    num1: number,\n"
    "    bool1: boolean,\n"
    "    str1: string,\n"
    "    arg1,\n"
    "    vec1: vector,\n"
    "    buf1: buffer\n"
    "): string?\n"
    "    -- reconstructed body\n"
    "end\n"
    "```\n\n"
    "### Class recovery\n\n"
    "When the v100 class shape and member bindings validate, `NEWCLASS` and `NEWCLASSMEMBER` are emitted as class syntax instead of anonymous table placeholders.\n\n"
    "```luau\n"
    "class Point\n"
    "    public x\n\n"
    "    function length(self: Point): number\n"
    "        -- reconstructed body\n"
    "    end\n"
    "end\n"
    "```\n\n"
    "Class construction remains a normal call expression, for example `local point: Point = Point(1)`. Unsupported or ambiguous class regions retain the conservative compatibility representation.\n\n"
    "> Bytecode does not retain comments, original formatting, every source-level construct, or all names. Smart recovery reports the best supported reconstruction; it does not claim exact original source.\n\n"
    "## Quick start\n",
)
replace_once(
    readme,
    "    InlineSingleUseTemporaries = true,\n    MaxOutputCharacters = 4000000,\n",
    "    InlineSingleUseTemporaries = true,\n"
    "    SmartVariableNames = true,\n"
    "    InferTypes = true,\n"
    "    ShowRecoveredSymbols = false,\n"
    "    RecoverClasses = true,\n"
    "    MaxOutputCharacters = 4000000,\n",
)

example = ROOT / "examples/api_script.luau"
replace_once(
    example,
    "    InlineSingleUseTemporaries = true,\n    MaxOutputCharacters = 4000000,\n",
    "    InlineSingleUseTemporaries = true,\n"
    "    SmartVariableNames = true,\n"
    "    InferTypes = true,\n"
    "    ShowRecoveredSymbols = false,\n"
    "    RecoverClasses = true,\n"
    "    MaxOutputCharacters = 4000000,\n",
)
