from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"expected one regex match in {path}, found {count}: {pattern!r}")
    path.write_text(updated, encoding="utf-8")


ast_path = ROOT / "src/lunaux/backends/ast.py"
replace_once(
    ast_path,
    """@dataclass(frozen=True, slots=True)\nclass TableField:\n    key: Expr | None\n    value: Expr\n""",
    """@dataclass(frozen=True, slots=True)\nclass TableField:\n    key: Expr | None\n    value: Expr\n    name: str | None = None\n""",
)
replace_once(
    ast_path,
    """        for field in expression.fields:\n            value = render_expression(field.value)\n            if field.key is None:\n                fields.append(value)\n            else:\n                fields.append(f\"[{render_expression(field.key)}] = {value}\")\n""",
    """        for field in expression.fields:\n            value = render_expression(field.value)\n            if field.name is not None and _identifier(field.name):\n                fields.append(f\"{field.name} = {value}\")\n            elif field.key is None:\n                fields.append(value)\n            else:\n                fields.append(f\"[{render_expression(field.key)}] = {value}\")\n""",
)

lifter = ROOT / "src/lunaux/backends/lifter.py"
replace_once(
    lifter,
    """    FieldExpr,\n    IndexExpr,\n    LiteralExpr,\n""",
    """    FieldExpr,\n    IfExpr,\n    IndexExpr,\n    LiteralExpr,\n""",
)
replace_once(
    lifter,
    """from lunaux.backends.ssa import SSAValue, build_ssa\nfrom lunaux.backends.symbols import SymbolRecovery, build_symbol_recovery\n""",
    """from lunaux.backends.ssa import SSAValue, build_ssa\nfrom lunaux.backends.structuring import build_structured_recovery\nfrom lunaux.backends.symbols import SymbolRecovery, build_symbol_recovery\nfrom lunaux.backends.table_recovery import (\n    PendingTableLiteral,\n    is_table_write,\n    should_flush_tables_before,\n    table_write_target_register,\n)\n""",
)
replace_once(
    lifter,
    """    preserve_for_step: bool\n    inline_single_use_temporaries: bool\n""",
    """    preserve_for_step: bool\n    use_if_expression: bool\n    recover_phi_expressions: bool\n    combine_boolean_conditions: bool\n    reconstruct_table_literals: bool\n    inline_single_use_temporaries: bool\n""",
)
replace_once(
    lifter,
    """            preserve_for_step=options.get(\"PreserveForStep\", False),\n            inline_single_use_temporaries=options.get(\n""",
    """            preserve_for_step=options.get(\"PreserveForStep\", False),\n            use_if_expression=options.get(\"UseIfExpression\", True),\n            recover_phi_expressions=options.get(\"RecoverPhiExpressions\", True),\n            combine_boolean_conditions=options.get(\n                \"CombineBooleanConditions\",\n                True,\n            ),\n            reconstruct_table_literals=options.get(\n                \"ReconstructTableLiterals\",\n                True,\n            ),\n            inline_single_use_temporaries=options.get(\n""",
)
replace_once(
    lifter,
    """        self.ssa = build_ssa(\n            self.instructions,\n            len(proto.code),\n            analysis=self.analysis,\n        )\n        self.symbols: SymbolRecovery | None = None\n""",
    """        self.ssa = build_ssa(\n            self.instructions,\n            len(proto.code),\n            analysis=self.analysis,\n        )\n        self.structured_plan = build_structured_recovery(self.ssa)\n        self.phi_conditions: dict[int, Expr] = {}\n        self.pending_tables: dict[SSAValue, PendingTableLiteral] = {}\n        self.symbols: SymbolRecovery | None = None\n""",
)
replace_once(
    lifter,
    """        self._analyze_control_flow()\n        self._analyze_cfg_regions()\n        self.labels = self._collect_labels()\n""",
    """        self._analyze_control_flow()\n        self._analyze_cfg_regions()\n        loop_condition_pcs = set(self.while_headers) | set(self.repeat_conditions)\n        phi_enabled = options.use_if_expression and options.recover_phi_expressions\n        self.active_phi_headers = (\n            dict(self.structured_plan.phi_by_header) if phi_enabled else {}\n        )\n        self.active_phi_joins = (\n            dict(self.structured_plan.phi_by_join) if phi_enabled else {}\n        )\n        self.captured_phi_values = (\n            self.structured_plan.captured_phi_values\n            if phi_enabled\n            else frozenset()\n        )\n        self.phi_definition_pcs = frozenset(\n            value.origin_pc\n            for value in self.captured_phi_values\n            if value.origin_pc is not None\n        )\n        self.active_boolean_chains = (\n            {\n                root: chain\n                for root, chain in self.structured_plan.boolean_by_root.items()\n                if not (set(chain.condition_pcs) & loop_condition_pcs)\n            }\n            if options.combine_boolean_conditions\n            else {}\n        )\n        self.active_structuring_skip_pcs: set[int] = set()\n        for region in self.active_phi_headers.values():\n            self.active_structuring_skip_pcs.update(region.skipped_pcs)\n        for chain in self.active_boolean_chains.values():\n            self.active_structuring_skip_pcs.update(chain.skipped_pcs)\n        self.labels = self._collect_labels()\n""",
)
replace_once(
    lifter,
    """        for region in self.if_else_regions.values():\n            structured_targets.add(region.else_pc)\n            structured_targets.add(region.end_pc)\n""",
    """        for region in self.if_else_regions.values():\n            structured_targets.add(region.else_pc)\n            structured_targets.add(region.end_pc)\n        for region in self.active_phi_headers.values():\n            structured_targets.add(region.then_block)\n            structured_targets.add(region.else_block)\n            structured_targets.add(region.join_pc)\n        for chain in self.active_boolean_chains.values():\n            structured_targets.add(chain.body_start)\n            structured_targets.add(chain.false_start)\n            structured_targets.add(chain.join)\n""",
)
replace_once(
    lifter,
    """        value = self.ssa.value_defined_at(pc, register)\n        if (\n            self.options.inline_single_use_temporaries\n""",
    """        value = self.ssa.value_defined_at(pc, register)\n        if value is not None and value in self.captured_phi_values:\n            self.inline_expressions[value] = resolved_expression\n            return\n        if (\n            self.options.inline_single_use_temporaries\n""",
)
replace_once(
    lifter,
    """        for register, name in zip(registers, names, strict=True):\n            self.register_names[register] = name\n\n    def _close_blocks(self, pc: int) -> None:\n""",
    """        for register, name in zip(registers, names, strict=True):\n            self.register_names[register] = name\n\n    def _assign_phi_result(self, value: SSAValue, expression: Expr, pc: int) -> None:\n        if self.ssa.uses_of(value) <= 0:\n            return\n        binding = self.scope_tree.binding_for_register(value.register, pc)\n        if (\n            self.options.inline_single_use_temporaries\n            and self.ssa.uses_of(value) == 1\n            and binding is None\n        ):\n            self.inline_expressions[value] = expression\n            return\n        symbol = self.symbols.symbol_for(value) if self.symbols is not None else None\n        recovered_name = symbol.name if symbol is not None else None\n        fallback = self.register_names.get(value.register, f\"v{value.register}\")\n        name = _sanitize_identifier(\n            binding.name if binding is not None else recovered_name,\n            fallback,\n        )\n        type_name = symbol.type_name if symbol is not None else None\n        if type_name is None:\n            type_name = _local_type(\n                self.module,\n                self.proto,\n                value.register,\n                pc,\n            )\n        annotated = f\"{name}: {type_name}\" if type_name and type_name != \"any\" else name\n        prefix = \"\" if name in self.declared else \"local \"\n        self.out.line(\n            f\"{prefix}{annotated} = {render_expression(expression)}\",\n            statement=True,\n        )\n        self.declared.add(name)\n        self.register_names[value.register] = name\n\n    def _finalize_phi_regions(self, pc: int) -> None:\n        for region in self.active_phi_joins.get(pc, ()):\n            condition = self.phi_conditions.pop(region.condition_pc, None)\n            if condition is None:\n                continue\n            for assignment in region.assignments:\n                then_value = self.inline_expressions.pop(assignment.then_value, None)\n                else_value = self.inline_expressions.pop(assignment.else_value, None)\n                if then_value is None or else_value is None:\n                    continue\n                self._assign_phi_result(\n                    assignment.result,\n                    IfExpr(condition, then_value, else_value),\n                    pc,\n                )\n\n    def _flush_pending_table(self, pending: PendingTableLiteral) -> None:\n        self.pending_tables.pop(pending.value, None)\n        self._assign(\n            pending.register,\n            pending.expression(),\n            pending.definition_pc,\n        )\n\n    def _flush_pending_tables(self) -> None:\n        for pending in sorted(\n            tuple(self.pending_tables.values()),\n            key=lambda item: item.definition_pc,\n        ):\n            self._flush_pending_table(pending)\n\n    def _flush_tables_before(self, instruction: DecodedInstruction) -> None:\n        if not self.options.reconstruct_table_literals or not self.pending_tables:\n            return\n        registers = frozenset(\n            pending.register for pending in self.pending_tables.values()\n        )\n        if should_flush_tables_before(instruction, registers):\n            self._flush_pending_tables()\n\n    def _pending_table_for_write(\n        self,\n        instruction: DecodedInstruction,\n    ) -> PendingTableLiteral | None:\n        target = table_write_target_register(instruction)\n        if target is None:\n            return None\n        value = self.ssa.value_at_use(instruction.pc, target)\n        return self.pending_tables.get(value) if value is not None else None\n\n    def _record_table_write(self, instruction: DecodedInstruction) -> bool:\n        pending = self._pending_table_for_write(instruction)\n        if pending is None:\n            return False\n        pc = instruction.pc\n        success = False\n        if instruction.name in {\"SETTABLEKS\", \"SETUDATAKS\"}:\n            success = pending.add_named(\n                self._table_key(instruction),\n                self._ref_expr(instruction.a, pc),\n            )\n        elif instruction.name == \"SETTABLEN\":\n            success = pending.add_index(\n                instruction.c + 1,\n                self._ref_expr(instruction.a, pc),\n            )\n        elif instruction.name == \"SETLIST\" and instruction.c > 0:\n            count = instruction.c - 1\n            start_index = (instruction.aux or 0) + 1\n            entries = tuple(\n                (\n                    start_index + index,\n                    self._ref_expr(instruction.b + index, pc),\n                )\n                for index in range(count)\n            )\n            success = pending.add_indices(entries)\n        elif instruction.name == \"SETTABLE\":\n            key = self._ref_expr(instruction.c, pc)\n            if isinstance(key, LiteralExpr):\n                try:\n                    decoded = json.loads(key.text)\n                except (json.JSONDecodeError, TypeError):\n                    decoded = None\n                if isinstance(decoded, str):\n                    success = pending.add_named(\n                        decoded,\n                        self._ref_expr(instruction.a, pc),\n                    )\n                elif key.text.isdigit():\n                    success = pending.add_index(\n                        int(key.text),\n                        self._ref_expr(instruction.a, pc),\n                    )\n        if success:\n            return True\n        self._flush_pending_table(pending)\n        return False\n\n    def _close_blocks(self, pc: int) -> None:\n""",
)
regex_once(
    lifter,
    r"    def _conditional_body\(self, instruction: DecodedInstruction\) -> str \| None:\n.*?        return None\n\n    def _handle_loop_prep",
    """    def _conditional_expr(self, instruction: DecodedInstruction) -> Expr | None:\n        name = instruction.name\n        if name == \"JUMPIF\":\n            return UnaryExpr(\"not\", self._ref_expr(instruction.a, instruction.pc))\n        if name == \"JUMPIFNOT\":\n            return self._ref_expr(instruction.a, instruction.pc)\n        if name in _COMPARISON_FALLTHROUGH:\n            rhs_register = (instruction.aux or 0) & 0xFF\n            return BinaryExpr(\n                self._ref_expr(instruction.a, instruction.pc),\n                _COMPARISON_FALLTHROUGH[name],\n                self._ref_expr(rhs_register, instruction.pc),\n            )\n        if name.startswith(\"JUMPXEQK\"):\n            if name == \"JUMPXEQKNIL\":\n                rhs = LiteralExpr(\"nil\")\n            elif name == \"JUMPXEQKB\":\n                rhs = LiteralExpr(\"true\" if (instruction.aux or 0) & 1 else \"false\")\n            else:\n                rhs = source_expr(\n                    _constant_expr(\n                        self.proto,\n                        (instruction.aux or 0) & 0xFFFFFF,\n                    )\n                )\n            fallthrough_operator = \"==\" if instruction.aux_not else \"~=\"\n            return BinaryExpr(\n                self._ref_expr(instruction.a, instruction.pc),\n                fallthrough_operator,\n                rhs,\n            )\n        return None\n\n    def _conditional_body(self, instruction: DecodedInstruction) -> str | None:\n        expression = self._conditional_expr(instruction)\n        return render_expression(expression) if expression is not None else None\n\n    def _boolean_chain_expression(self, condition_pcs: tuple[int, ...], operator: str) -> Expr | None:\n        expressions: list[Expr] = []\n        for condition_pc in condition_pcs:\n            instruction = self.instruction_by_pc.get(condition_pc)\n            if instruction is None:\n                return None\n            expression = self._conditional_expr(instruction)\n            if expression is None:\n                return None\n            expressions.append(expression)\n        if not expressions:\n            return None\n        combined = expressions[0]\n        for expression in expressions[1:]:\n            combined = BinaryExpr(combined, operator, expression)\n        return combined\n\n    def _handle_loop_prep""",
)
replace_once(
    lifter,
    """        for instruction in self.instructions:\n            self._close_blocks(instruction.pc)\n            opened_loop = self._open_structured_loop(instruction)\n""",
    """        for instruction in self.instructions:\n            self._finalize_phi_regions(instruction.pc)\n            self._flush_tables_before(instruction)\n            self._close_blocks(instruction.pc)\n            opened_loop = self._open_structured_loop(instruction)\n""",
)
replace_once(
    lifter,
    """            if instruction.pc in self.class_plan.skipped_instruction_pcs:\n                continue\n""",
    """            if instruction.pc in self.class_plan.skipped_instruction_pcs:\n                continue\n            if (\n                instruction.pc in self.active_structuring_skip_pcs\n                and instruction.pc not in self.phi_definition_pcs\n            ):\n                continue\n""",
)
replace_once(
    lifter,
    """        self._close_blocks(len(self.proto.code))\n""",
    """        self._finalize_phi_regions(len(self.proto.code))\n        self._flush_pending_tables()\n        self._close_blocks(len(self.proto.code))\n""",
)
replace_once(
    lifter,
    """    def _lift_instruction(self, instruction: DecodedInstruction) -> None:\n        name = instruction.name\n        pc = instruction.pc\n        expression: Expr | str\n""",
    """    def _lift_instruction(self, instruction: DecodedInstruction) -> None:\n        name = instruction.name\n        pc = instruction.pc\n        expression: Expr | str\n        if (\n            self.options.reconstruct_table_literals\n            and is_table_write(instruction)\n            and self._record_table_write(instruction)\n        ):\n            return\n""",
)
replace_once(
    lifter,
    """        elif name == \"NEWTABLE\":\n            self._assign(instruction.a, TableExpr(), pc)\n""",
    """        elif name == \"NEWTABLE\":\n            value = self.ssa.value_defined_at(pc, instruction.a)\n            if self.options.reconstruct_table_literals and value is not None:\n                self.pending_tables[value] = PendingTableLiteral(\n                    value=value,\n                    register=instruction.a,\n                    definition_pc=pc,\n                )\n                self.register_names.setdefault(instruction.a, f\"v{instruction.a}\")\n            else:\n                self._assign(instruction.a, TableExpr(), pc)\n""",
)
replace_once(
    lifter,
    """        elif name in _CONDITIONAL_OPS:\n            target = _jump_target(instruction)\n            condition = self._conditional_body(instruction)\n            region = self.if_else_regions.get(pc)\n            if condition is None or target <= pc:\n""",
    """        elif name in _CONDITIONAL_OPS:\n            target = _jump_target(instruction)\n            condition_expression = self._conditional_expr(instruction)\n            condition = (\n                render_expression(condition_expression)\n                if condition_expression is not None\n                else None\n            )\n            phi_region = self.active_phi_headers.get(pc)\n            if phi_region is not None and condition_expression is not None:\n                self.phi_conditions[pc] = condition_expression\n                return\n            chain = self.active_boolean_chains.get(pc)\n            if chain is not None:\n                combined = self._boolean_chain_expression(\n                    chain.condition_pcs,\n                    chain.operator,\n                )\n                if combined is not None:\n                    self.out.open(f\"if {render_expression(combined)} then\")\n                    if chain.has_else:\n                        self.else_transitions[chain.false_start] = chain.join\n                    else:\n                        self.block_closures[chain.join].append(\"end\")\n                    return\n            region = self.if_else_regions.get(pc)\n            if condition is None or target <= pc:\n""",
)

models = ROOT / "src/lunaux/models.py"
replace_once(
    models,
    """    use_if_expression: bool = Field(default=True, alias=\"UseIfExpression\")\n    inline_single_use_temporaries: bool = Field(\n""",
    """    use_if_expression: bool = Field(default=True, alias=\"UseIfExpression\")\n    recover_phi_expressions: bool = Field(\n        default=True,\n        alias=\"RecoverPhiExpressions\",\n    )\n    combine_boolean_conditions: bool = Field(\n        default=True,\n        alias=\"CombineBooleanConditions\",\n    )\n    reconstruct_table_literals: bool = Field(\n        default=True,\n        alias=\"ReconstructTableLiterals\",\n    )\n    inline_single_use_temporaries: bool = Field(\n""",
)
replace_once(
    models,
    """            \"UseIfExpression\": self.use_if_expression,\n            \"InlineSingleUseTemporaries\": self.inline_single_use_temporaries,\n""",
    """            \"UseIfExpression\": self.use_if_expression,\n            \"RecoverPhiExpressions\": self.recover_phi_expressions,\n            \"CombineBooleanConditions\": self.combine_boolean_conditions,\n            \"ReconstructTableLiterals\": self.reconstruct_table_literals,\n            \"InlineSingleUseTemporaries\": self.inline_single_use_temporaries,\n""",
)

for relative in ("pyproject.toml", "src/lunaux/__init__.py"):
    path = ROOT / relative
    replace_once(path, '0.11.0', '0.12.0')

reconstructed = ROOT / "src/lunaux/backends/reconstructed.py"
replace_once(reconstructed, 'return "0.11.0"', 'return "0.12.0"')
replace_once(
    reconstructed,
    '"""Portable Luau reconstruction with CFG, SSA, AST, symbols, types, and classes."""',
    '"""Portable reconstruction with CFG, SSA, structured conditions, phi recovery, and table literals."""',
)

example = ROOT / "examples/api_script.luau"
replace_once(
    example,
    """    UseIfExpression = true,\n    InlineSingleUseTemporaries = true,\n""",
    """    UseIfExpression = true,\n    RecoverPhiExpressions = true,\n    CombineBooleanConditions = true,\n    ReconstructTableLiterals = true,\n    InlineSingleUseTemporaries = true,\n""",
)

readme = ROOT / "README.md"
replace_once(
    readme,
    "> **Version 0.11:** adds a reusable Roblox pattern registry, a pre-emission heuristic type engine, and safe non-adjacent temporary elimination.",
    "> **Version 0.12:** adds conservative phi elimination, boolean-chain reconstruction, and table-literal consolidation on top of the 0.11 semantic recovery pipeline.",
)
replace_once(
    readme,
    "- Computes register liveness, reaching definitions, reverse def-use chains, and conservative SSA phi placement.\n- Renames register definitions into versioned SSA values and resolves phi operands for each predecessor.\n",
    "- Computes register liveness, reaching definitions, reverse def-use chains, and conservative SSA phi placement.\n- Renames register definitions into versioned SSA values and resolves phi operands for each predecessor.\n- Converts validated two-branch phi diamonds into typed Luau `if ... then ... else ...` expressions.\n- Combines reducible short-circuit branch chains into `and` and `or` conditions without crossing side effects.\n- Consolidates straight-line `NEWTABLE` plus keyed, indexed, and `SETLIST` writes into table literals.\n",
)
replace_once(
    readme,
    "- Inlines single-use temporaries across short pure instruction gaps while blocking calls, mutations, branches, and source-register redefinitions.\n",
    "- Inlines single-use temporaries across short pure instruction gaps while blocking calls, mutations, branches, and source-register redefinitions.\n- Flushes pending table literals before calls, escapes, control flow, duplicate keys, dynamic keys, or ambiguous mutations.\n",
)
