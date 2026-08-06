from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:90]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_replace_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"expected one regex match in {path}, found {count}: {pattern[:90]!r}")
    path.write_text(updated, encoding="utf-8")


symbols = ROOT / "src/lunaux/backends/symbols.py"
replace_once(
    symbols,
    "from lunaux.backends.opcodes import DecodedInstruction\n"
    "from lunaux.backends.ssa import SSAProgram, SSAValue\n",
    "from lunaux.backends.opcodes import DecodedInstruction\n"
    "from lunaux.backends.roblox_patterns import (\n"
    "    match_function_call,\n"
    "    match_method_call,\n"
    ")\n"
    "from lunaux.backends.ssa import SSAProgram, SSAValue\n"
    "from lunaux.backends.type_inference import (\n"
    "    infer_function_return,\n"
    "    infer_instruction_type,\n"
    "    infer_method_return,\n"
    "    infer_property_type,\n"
    "    merge_types,\n"
    ")\n",
)
regex_replace_once(
    symbols,
    r"def _property_type\(key: str\) -> str \| None:\n.*?(?=\ndef _direct_call_type)",
    "def _property_type(key: str) -> str | None:\n"
    "    return infer_property_type(key)\n\n",
)
regex_replace_once(
    symbols,
    r"def _direct_call_type\(path: str \| None\) -> str \| None:\n.*?(?=\ndef _type_family)",
    "def _direct_call_type(path: str | None) -> str | None:\n"
    "    return infer_function_return(path)\n\n",
)
regex_replace_once(
    symbols,
    r"def _union_type\(types: set\[str\]\) -> str \| None:\n.*?(?=\ndef build_symbol_recovery)",
    "def _union_type(types: set[str]) -> str | None:\n"
    "    return merge_types(types)\n\n",
)
replace_once(
    symbols,
    "            facts[definition].add_name(debug_name, 100, \"debug local name\")\n"
    "            facts[definition].add_type(type_name, 100, \"serialized local type\")\n\n"
    "        if name == \"MOVE\":\n",
    "            facts[definition].add_name(debug_name, 100, \"debug local name\")\n"
    "            facts[definition].add_type(type_name, 100, \"serialized local type\")\n\n"
    "        constant_kind = None\n"
    "        if name in {\"LOADK\", \"LOADKX\"}:\n"
    "            instruction_constant = _instruction_constant(proto, instruction)\n"
    "            if instruction_constant is not None:\n"
    "                constant_kind = instruction_constant.kind\n"
    "        heuristic_type = infer_instruction_type(\n"
    "            name,\n"
    "            constant_kind=constant_kind,\n"
    "        )\n"
    "        if heuristic_type is not None:\n"
    "            for definition in ssa_instruction.definitions:\n"
    "                facts[definition].add_type(\n"
    "                    heuristic_type,\n"
    "                    74,\n"
    "                    \"heuristic opcode result type\",\n"
    "                )\n\n"
    "        if name == \"MOVE\":\n",
)
replace_once(
    symbols,
    "            result_registers = [value.register for value in ssa_instruction.definitions]\n"
    "            if method == \"GetService\" and instruction.b > 2:\n",
    "            result_registers = [value.register for value in ssa_instruction.definitions]\n"
    "            literal_arguments = (\n"
    "                tuple(\n"
    "                    literal_string(program.value_at_use(pc, instruction.a + offset))\n"
    "                    for offset in range(2, instruction.b)\n"
    "                )\n"
    "                if instruction.b > 2\n"
    "                else ()\n"
    "            )\n"
    "            method_pattern = match_method_call(method, literal_arguments)\n"
    "            if method_pattern is not None:\n"
    "                for register in result_registers:\n"
    "                    add_definition_name(\n"
    "                        pc,\n"
    "                        register,\n"
    "                        method_pattern.name,\n"
    "                        method_pattern.confidence,\n"
    "                        method_pattern.evidence,\n"
    "                    )\n"
    "                    add_definition_type(\n"
    "                        pc,\n"
    "                        register,\n"
    "                        method_pattern.type_name,\n"
    "                        method_pattern.confidence,\n"
    "                        method_pattern.evidence,\n"
    "                    )\n"
    "            method_return = infer_method_return(method)\n"
    "            if method_return is not None and method != \"Clone\":\n"
    "                for register in result_registers:\n"
    "                    add_definition_type(\n"
    "                        pc,\n"
    "                        register,\n"
    "                        method_return,\n"
    "                        72,\n"
    "                        f\"heuristic {method} return type\",\n"
    "                    )\n\n"
    "            if method == \"GetService\" and instruction.b > 2:\n",
)
replace_once(
    symbols,
    "                call_path = value_path(function_value)\n"
    "                return_type = _direct_call_type(call_path)\n",
    "                call_path = value_path(function_value)\n"
    "                direct_arguments = (\n"
    "                    tuple(\n"
    "                        literal_string(\n"
    "                            program.value_at_use(pc, instruction.a + offset)\n"
    "                        )\n"
    "                        for offset in range(1, instruction.b)\n"
    "                    )\n"
    "                    if instruction.b > 1\n"
    "                    else ()\n"
    "                )\n"
    "                function_pattern = match_function_call(\n"
    "                    call_path,\n"
    "                    direct_arguments,\n"
    "                )\n"
    "                if function_pattern is not None:\n"
    "                    for register in result_registers:\n"
    "                        add_definition_name(\n"
    "                            pc,\n"
    "                            register,\n"
    "                            function_pattern.name,\n"
    "                            function_pattern.confidence,\n"
    "                            function_pattern.evidence,\n"
    "                        )\n"
    "                        add_definition_type(\n"
    "                            pc,\n"
    "                            register,\n"
    "                            function_pattern.type_name,\n"
    "                            function_pattern.confidence,\n"
    "                            function_pattern.evidence,\n"
    "                        )\n"
    "                return_type = _direct_call_type(call_path)\n",
)

inlining = ROOT / "src/lunaux/backends/inlining.py"
replace_once(
    inlining,
    ")\n_ATOMIC_EXPRESSION = re.compile(\n",
    ")\n"
    "_NON_ADJACENT_INLINEABLE_DEFINITIONS = frozenset(\n"
    "    {\n"
    "        \"LOADNIL\",\n"
    "        \"LOADB\",\n"
    "        \"LOADN\",\n"
    "        \"LOADK\",\n"
    "        \"LOADKX\",\n"
    "        \"MOVE\",\n"
    "        \"ADD\",\n"
    "        \"SUB\",\n"
    "        \"MUL\",\n"
    "        \"DIV\",\n"
    "        \"MOD\",\n"
    "        \"POW\",\n"
    "        \"IDIV\",\n"
    "        \"ADDK\",\n"
    "        \"SUBK\",\n"
    "        \"MULK\",\n"
    "        \"DIVK\",\n"
    "        \"MODK\",\n"
    "        \"POWK\",\n"
    "        \"IDIVK\",\n"
    "        \"SUBRK\",\n"
    "        \"DIVRK\",\n"
    "        \"NOT\",\n"
    "        \"MINUS\",\n"
    "        \"LENGTH\",\n"
    "        \"CONCAT\",\n"
    "    }\n"
    ")\n"
    "_REORDER_SAFE_INSTRUCTIONS = frozenset(\n"
    "    {\n"
    "        \"NOP\",\n"
    "        \"COVERAGE\",\n"
    "        *_NON_ADJACENT_INLINEABLE_DEFINITIONS,\n"
    "    }\n"
    ")\n"
    "_ATOMIC_EXPRESSION = re.compile(\n",
)
replace_once(
    inlining,
    "def plan_expression_inlining(\n"
    "    program: SSAProgram,\n"
    "    proto: LuauProto,\n"
    ") -> ExpressionInliningPlan:\n",
    "def _safe_non_adjacent_gap(\n"
    "    program: SSAProgram,\n"
    "    definition_pc: int,\n"
    "    use_pc: int,\n"
    ") -> bool:\n"
    "    definition = program.instructions.get(definition_pc)\n"
    "    if definition is None:\n"
    "        return False\n"
    "    source_registers = set(_register_operands(definition.instruction))\n"
    "    intervening_pcs = sorted(\n"
    "        pc for pc in program.instructions if definition_pc < pc < use_pc\n"
    "    )\n"
    "    if len(intervening_pcs) > 6:\n"
    "        return False\n"
    "    for pc in intervening_pcs:\n"
    "        instruction = program.instructions[pc]\n"
    "        if instruction.instruction.name not in _REORDER_SAFE_INSTRUCTIONS:\n"
    "            return False\n"
    "        if any(\n"
    "            value.register in source_registers\n"
    "            for value in instruction.definitions\n"
    "        ):\n"
    "            return False\n"
    "    return True\n\n\n"
    "def plan_expression_inlining(\n"
    "    program: SSAProgram,\n"
    "    proto: LuauProto,\n"
    ") -> ExpressionInliningPlan:\n",
)
replace_once(
    inlining,
    "        if definition_pc + definition.instruction.size != use_pc:\n"
    "            continue\n"
    "        definition_block = program.analysis.block_for_pc.get(definition_pc)\n",
    "        adjacent = definition_pc + definition.instruction.size == use_pc\n"
    "        if not adjacent:\n"
    "            if (\n"
    "                definition.instruction.name\n"
    "                not in _NON_ADJACENT_INLINEABLE_DEFINITIONS\n"
    "                or not _safe_non_adjacent_gap(program, definition_pc, use_pc)\n"
    "            ):\n"
    "                continue\n"
    "        definition_block = program.analysis.block_for_pc.get(definition_pc)\n",
)

pyproject = ROOT / "pyproject.toml"
replace_once(pyproject, 'version = "0.10.0"', 'version = "0.11.0"')
replace_once(
    pyproject,
    'description = "A multi-engine Luau decompiler with CFG, SSA, structured expressions, and lexical scope recovery"',
    'description = "A multi-engine Luau decompiler with semantic Roblox patterns, heuristic types, CFG, SSA, and structured recovery"',
)

package = ROOT / "src/lunaux/__init__.py"
replace_once(package, '__version__ = "0.10.0"', '__version__ = "0.11.0"')

reconstructed = ROOT / "src/lunaux/backends/reconstructed.py"
replace_once(reconstructed, '        return "0.10.0"', '        return "0.11.0"')

readme = ROOT / "README.md"
regex_replace_once(
    readme,
    r"> \*\*Version 0\.10:\*\*.*?\n",
    "> **Version 0.11:** adds a reusable Roblox pattern registry, a pre-emission "
    "heuristic type engine, and safe non-adjacent temporary elimination.\n",
)
replace_once(
    readme,
    "- Recovers symbol names from debug metadata, SSA relationships, imports, fields, prototype bindings, and Roblox API call evidence.\n",
    "- Recovers symbol names from debug metadata, SSA relationships, imports, fields, prototype bindings, and Roblox API call evidence.\n"
    "- Uses a dedicated Roblox pattern registry for services, children, tags, attributes, signals, spatial queries, constructors, players, and raycasts.\n",
)
replace_once(
    readme,
    "- Infers conservative parameter, local, and return types from serialized type metadata plus data flow and known operation contracts.\n",
    "- Infers conservative parameter, local, and return types from serialized type metadata plus data flow and known operation contracts.\n"
    "- Runs reusable opcode, property, method, constructor, and flow type heuristics before source emission.\n"
    "- Inlines single-use temporaries across short pure instruction gaps while blocking calls, mutations, branches, and source-register redefinitions.\n",
)
