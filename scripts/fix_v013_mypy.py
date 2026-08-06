from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"expected one match in {path}, found {count}: {old[:100]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


lifter = ROOT / "src/lunaux/backends/lifter.py"
text = lifter.read_text(encoding="utf-8")

old = '''        value = self.ssa.value_at_use(pc, register)
        child = self.pending_tables.get(value) if value is not None else None
        if child is owner:
'''
new = '''        value = self.ssa.value_at_use(pc, register)
        expression: Expr
        child = self.pending_tables.get(value) if value is not None else None
        if child is owner:
'''
if old in text:
    text = text.replace(old, new, 1)
elif "        expression: Expr\n        child =" not in text:
    raise RuntimeError("expression annotation marker not found")

old = '''        elif instruction.name == "SETLIST" and instruction.c == 0:
            captured = self.pending_open_table_values.pop(instruction.b, None)
            if captured is not None and captured[2] == pc:
                value, dependencies, _consumer_pc = captured
'''
new = '''        elif instruction.name == "SETLIST" and instruction.c == 0:
            open_captured = self.pending_open_table_values.pop(
                instruction.b,
                None,
            )
            if open_captured is not None and open_captured[2] == pc:
                value, dependencies, _consumer_pc = open_captured
'''
if old in text:
    text = text.replace(old, new, 1)
elif "open_captured = self.pending_open_table_values.pop" not in text:
    raise RuntimeError("open tail capture marker not found")

lifter.write_text(text, encoding="utf-8")

readme = ROOT / "README.md"
text = readme.read_text(encoding="utf-8")

text = text.replace(
    "> **Version 0.12:** adds conservative phi elimination, boolean-chain reconstruction, and table-literal consolidation on top of the 0.11 semantic recovery pipeline.",
    "> **Version 0.13:** expands table recovery into an ownership- and SSA-aware reconstruction pass for nested tables, templates, dynamic keys, deterministic overwrites, aliases, and open `SETLIST` tails.",
)
text = text.replace(
    "- Consolidates straight-line `NEWTABLE` plus keyed, indexed, and `SETLIST` writes into table literals.",
    "- Reconstructs full table constructors from `NEWTABLE` and `DUPTABLE`, including nested tables, named/indexed/dynamic keys, fixed `SETLIST` ranges, and final open call or vararg tails.",
)
text = text.replace(
    "- Flushes pending table literals before calls, escapes, control flow, duplicate keys, dynamic keys, or ambiguous mutations.",
    "- Tracks table ownership, aliases, contained tables, and SSA dependencies; it materializes constructors before escapes, cycles, dependency redefinitions, unsafe calls, control flow, or ambiguous stack-top writes.",
)

section_marker = "### Class recovery\n"
if "### Full table reconstruction\n" not in text:
    table_section = '''### Full table reconstruction

Version 0.13 treats table construction as an ownership problem instead of only an adjacent-instruction pattern. A child table is absorbed into its parent only when every use is either part of its own construction or the single parent insertion. Independent tables may be built in an interleaved instruction stream without forcing either constructor to close early.

```luau
local config = {
    Name = "Sword",
    Stats = {
        Damage = 25,
        Critical = true,
    },
    [dynamicKey] = dynamicValue,
    "Fire",
    collectMore(),
}
```

Recovered constructors may include:

- `SETTABLEKS` and `SETUDATAKS` named fields;
- `SETTABLEN` and fixed `SETLIST` array ranges;
- arbitrary `SETTABLE` keys rendered as `[expression] = value`;
- `DUPTABLE` key templates and constant-valued templates;
- deterministic overwrites before the table is observed;
- single-use `MOVE` aliases;
- a final multiple-return call or `...` tail when the open `SETLIST` range is contiguous.

Self-references, shared children, calls that can observe pending state, noncontiguous open ranges, dependency redefinitions, and ambiguous escapes keep the conservative statement form.

'''
    if section_marker not in text:
        raise RuntimeError("README class recovery marker not found")
    text = text.replace(section_marker, table_section + section_marker, 1)

options_block = '''    UseIfExpression = true,
    InlineSingleUseTemporaries = true,
'''
options_replacement = '''    UseIfExpression = true,
    RecoverPhiExpressions = true,
    CombineBooleanConditions = true,
    ReconstructTableLiterals = true,
    InlineSingleUseTemporaries = true,
'''
if options_block in text:
    text = text.replace(options_block, options_replacement, 1)

old_rows = '''| `UseIfExpression` | `true` | Prefer `if ... then ... else ...` expressions instead of equivalent `and`/`or` expressions. |
| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
| `MaxOutputCharacters` | `4000000` | Maximum generated output length. Accepted range: 1,000 to 20,000,000 characters. |
'''
new_rows = '''| `UseIfExpression` | `true` | Prefer `if ... then ... else ...` expressions instead of equivalent `and`/`or` expressions. |
| `RecoverPhiExpressions` | `true` | Convert validated two-way SSA phi diamonds into Luau `if` expressions. |
| `CombineBooleanConditions` | `true` | Combine reducible short-circuit jump chains into `and` and `or`. |
| `ReconstructTableLiterals` | `true` | Recover owned table-construction regions, including nested tables, templates, dynamic keys, aliases, overwrites, and supported `SETLIST` tails. |
| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
| `SmartVariableNames` | `true` | Select names from debug metadata, SSA relationships, imports, fields, types, and Roblox API evidence. |
| `InferTypes` | `true` | Infer conservative parameter, local, expression, and return types. |
| `ShowRecoveredSymbols` | `false` | Emit comments describing recovered SSA names, types, and evidence. |
| `RecoverClasses` | `true` | Reconstruct validated experimental class regions as Luau class syntax. |
| `MaxOutputCharacters` | `4000000` | Maximum generated output length. Accepted range: 1,000 to 20,000,000 characters. |
'''
if old_rows in text:
    text = text.replace(old_rows, new_rows, 1)
elif "| `ReconstructTableLiterals` |" not in text:
    raise RuntimeError("README API options marker not found")

readme.write_text(text, encoding="utf-8")
print("fixed v0.13 typing and updated documentation")
