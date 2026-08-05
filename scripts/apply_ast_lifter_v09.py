from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


lifter_path = ROOT / "src/lunaux/backends/lifter.py"
lifter = lifter_path.read_text(encoding="utf-8")

lifter = replace_once(
    lifter,
    "from lunaux.backends.analysis import analyze_control_flow\n",
    "from lunaux.backends.analysis import analyze_control_flow\n"
    "from lunaux.backends.ast import (\n"
    "    BinaryExpr,\n"
    "    CallExpr,\n"
    "    Expr,\n"
    "    FieldExpr,\n"
    "    IndexExpr,\n"
    "    LiteralExpr,\n"
    "    MethodCallExpr,\n"
    "    NameExpr,\n"
    "    Precedence,\n"
    "    RawExpr,\n"
    "    TableExpr,\n"
    "    UnaryExpr,\n"
    "    ensure_expr,\n"
    "    render_expression,\n"
    "    source_expr,\n"
    ")\n",
    "AST imports",
)
lifter = replace_once(
    lifter,
    "from lunaux.backends.inlining import (\n"
    "    parenthesize_inlined_expression,\n"
    "    plan_expression_inlining,\n"
    ")\n",
    "from lunaux.backends.inlining import plan_expression_inlining\n",
    "inlining import",
)
lifter = replace_once(
    lifter,
    "from lunaux.backends.ssa import SSAValue, build_ssa\n",
    "from lunaux.backends.scopes import build_scope_tree\n"
    "from lunaux.backends.ssa import SSAValue, build_ssa\n",
    "scope import",
)
lifter = replace_once(
    lifter,
    "        self.pending_namecalls: dict[int, tuple[str, str]] = {}\n",
    "        self.pending_namecalls: dict[int, tuple[Expr, str]] = {}\n",
    "namecall type",
)
lifter = replace_once(
    lifter,
    "        self.out = emitter\n"
    "        self.register_names: dict[int, str] = {}\n",
    "        self.out = emitter\n"
    "        self.scope_tree = build_scope_tree(proto)\n"
    "        self.register_names: dict[int, str] = {}\n",
    "scope tree initialization",
)
lifter = replace_once(
    lifter,
    "        self.inline_expressions: dict[SSAValue, str] = {}\n",
    "        self.inline_expressions: dict[SSAValue, Expr] = {}\n",
    "inline expression type",
)

lifter = replace_once(
    lifter,
    "    def _name(self, register: int, pc: int) -> str:\n"
    "        active = _local_name(self.proto, register, pc)\n"
    "        if active:\n"
    "            self.register_names[register] = active\n"
    "            return active\n"
    "        return self.register_names.get(register, f\"v{register}\")\n\n"
    "    def _ref(self, register: int, pc: int) -> str:\n"
    "        if self.options.inline_single_use_temporaries:\n"
    "            value = self.ssa.value_at_use(pc, register)\n"
    "            if value is not None:\n"
    "                expression = self.inline_expressions.get(value)\n"
    "                if expression is not None:\n"
    "                    return parenthesize_inlined_expression(expression)\n"
    "        return self._name(register, pc)\n",
    "    def _name(self, register: int, pc: int) -> str:\n"
    "        binding = self.scope_tree.binding_for_register(register, pc)\n"
    "        if binding is not None:\n"
    "            active = _sanitize_identifier(binding.name, f\"v{register}\")\n"
    "            self.register_names[register] = active\n"
    "            return active\n"
    "        return self.register_names.get(register, f\"v{register}\")\n\n"
    "    def _ref_expr(self, register: int, pc: int) -> Expr:\n"
    "        if self.options.inline_single_use_temporaries:\n"
    "            value = self.ssa.value_at_use(pc, register)\n"
    "            if value is not None:\n"
    "                expression = self.inline_expressions.get(value)\n"
    "                if expression is not None:\n"
    "                    return expression\n"
    "        return NameExpr(self._name(register, pc))\n\n"
    "    def _ref(self, register: int, pc: int) -> str:\n"
    "        return render_expression(self._ref_expr(register, pc))\n",
    "name and reference methods",
)

lifter = replace_once(
    lifter,
    "    def _assign(self, register: int, expression: str, pc: int) -> None:\n"
    "        value = self.ssa.value_defined_at(pc, register)\n"
    "        if (\n"
    "            self.options.inline_single_use_temporaries\n"
    "            and value is not None\n"
    "            and self.inline_plan.should_inline(value)\n"
    "        ):\n"
    "            self.inline_expressions[value] = expression\n"
    "            self.register_names.setdefault(register, f\"v{register}\")\n"
    "            return\n"
    "        name = self._name(register, pc)\n"
    "        if name in self.declared:\n"
    "            lhs = name\n"
    "        else:\n"
    "            lhs = \"local \" + self._annotated_name(register, name, pc)\n"
    "            self.declared.add(name)\n"
    "        self.register_names[register] = name\n"
    "        self.out.line(f\"{lhs} = {expression}\", statement=True)\n",
    "    def _assign(self, register: int, expression: Expr | str, pc: int) -> None:\n"
    "        resolved_expression = ensure_expr(expression)\n"
    "        value = self.ssa.value_defined_at(pc, register)\n"
    "        if (\n"
    "            self.options.inline_single_use_temporaries\n"
    "            and value is not None\n"
    "            and self.inline_plan.should_inline(value)\n"
    "        ):\n"
    "            self.inline_expressions[value] = resolved_expression\n"
    "            self.register_names.setdefault(register, f\"v{register}\")\n"
    "            return\n"
    "        name = self._name(register, pc)\n"
    "        if name in self.declared:\n"
    "            lhs = name\n"
    "        else:\n"
    "            lhs = \"local \" + self._annotated_name(register, name, pc)\n"
    "            self.declared.add(name)\n"
    "        self.register_names[register] = name\n"
    "        rendered = render_expression(resolved_expression)\n"
    "        self.out.line(f\"{lhs} = {rendered}\", statement=True)\n",
    "assignment method",
)

lifter = replace_once(
    lifter,
    "    def _assign_many(self, registers: list[int], expression: str, pc: int) -> None:\n"
    "        names = [self._name(register, pc) for register in registers]\n"
    "        new_flags = [name not in self.declared for name in names]\n"
    "        if all(new_flags):\n"
    "            annotated = [\n"
    "                self._annotated_name(register, name, pc)\n"
    "                for register, name in zip(registers, names, strict=True)\n"
    "            ]\n"
    "            self.out.line(\n"
    "                f\"local {', '.join(annotated)} = {expression}\",\n"
    "                statement=True,\n"
    "            )\n"
    "        elif any(new_flags):\n"
    "            declarations = [\n"
    "                self._annotated_name(register, name, pc)\n"
    "                for register, name, is_new in zip(\n"
    "                    registers,\n"
    "                    names,\n"
    "                    new_flags,\n"
    "                    strict=True,\n"
    "                )\n"
    "                if is_new\n"
    "            ]\n"
    "            self.out.line(\"local \" + \", \".join(declarations), statement=True)\n"
    "            self.out.line(f\"{', '.join(names)} = {expression}\", statement=True)\n"
    "        else:\n"
    "            self.out.line(f\"{', '.join(names)} = {expression}\", statement=True)\n"
    "        self.declared.update(names)\n"
    "        for register, name in zip(registers, names, strict=True):\n"
    "            self.register_names[register] = name\n",
    "    def _assign_many(\n"
    "        self,\n"
    "        registers: list[int],\n"
    "        expression: Expr | str,\n"
    "        pc: int,\n"
    "    ) -> None:\n"
    "        rendered_expression = render_expression(ensure_expr(expression))\n"
    "        names = [self._name(register, pc) for register in registers]\n"
    "        new_flags = [name not in self.declared for name in names]\n"
    "        if all(new_flags):\n"
    "            annotated = [\n"
    "                self._annotated_name(register, name, pc)\n"
    "                for register, name in zip(registers, names, strict=True)\n"
    "            ]\n"
    "            self.out.line(\n"
    "                f\"local {', '.join(annotated)} = {rendered_expression}\",\n"
    "                statement=True,\n"
    "            )\n"
    "        elif any(new_flags):\n"
    "            declarations = [\n"
    "                self._annotated_name(register, name, pc)\n"
    "                for register, name, is_new in zip(\n"
    "                    registers,\n"
    "                    names,\n"
    "                    new_flags,\n"
    "                    strict=True,\n"
    "                )\n"
    "                if is_new\n"
    "            ]\n"
    "            self.out.line(\"local \" + \", \".join(declarations), statement=True)\n"
    "            self.out.line(\n"
    "                f\"{', '.join(names)} = {rendered_expression}\",\n"
    "                statement=True,\n"
    "            )\n"
    "        else:\n"
    "            self.out.line(\n"
    "                f\"{', '.join(names)} = {rendered_expression}\",\n"
    "                statement=True,\n"
    "            )\n"
    "        self.declared.update(names)\n"
    "        for register, name in zip(registers, names, strict=True):\n"
    "            self.register_names[register] = name\n",
    "multi assignment method",
)

lifter = replace_once(
    lifter,
    "    def _call_expression(self, instruction: DecodedInstruction) -> str:\n"
    "        if instruction.a in self.pending_namecalls:\n"
    "            base, method = self.pending_namecalls.pop(instruction.a)\n"
    "            start = instruction.a + 2\n"
    "            count = max(0, instruction.b - 2) if instruction.b else 0\n"
    "            args = [self._ref(start + index, instruction.pc) for index in range(count)]\n"
    "            method_expr = (\n"
    "                method\n"
    "                if _IDENTIFIER.fullmatch(method) and method not in _RESERVED\n"
    "                else f\"[{_quote(method)}]\"\n"
    "            )\n"
    "            if method_expr.startswith(\"[\"):\n"
    "                return f\"{base}{method_expr}({', '.join(args)})\"\n"
    "            return f\"{base}:{method_expr}({', '.join(args)})\"\n"
    "        function = self._ref(instruction.a, instruction.pc)\n"
    "        if instruction.b == 0:\n"
    "            args_text = \"... --[[ all arguments through stack top ]]\"\n"
    "        else:\n"
    "            args = [\n"
    "                self._ref(instruction.a + index, instruction.pc)\n"
    "                for index in range(1, instruction.b)\n"
    "            ]\n"
    "            args_text = \", \".join(args)\n"
    "        return f\"{function}({args_text})\"\n",
    "    def _call_expression(self, instruction: DecodedInstruction) -> Expr:\n"
    "        if instruction.a in self.pending_namecalls:\n"
    "            base, method = self.pending_namecalls.pop(instruction.a)\n"
    "            start = instruction.a + 2\n"
    "            count = max(0, instruction.b - 2) if instruction.b else 0\n"
    "            args = tuple(\n"
    "                self._ref_expr(start + index, instruction.pc)\n"
    "                for index in range(count)\n"
    "            )\n"
    "            return MethodCallExpr(base, method, args)\n"
    "        function = self._ref_expr(instruction.a, instruction.pc)\n"
    "        if instruction.b == 0:\n"
    "            text = (\n"
    "                f\"{render_expression(function)}\"\n"
    "                \"(... --[[ all arguments through stack top ]])\"\n"
    "            )\n"
    "            return RawExpr(text, Precedence.POSTFIX)\n"
    "        args = tuple(\n"
    "            self._ref_expr(instruction.a + index, instruction.pc)\n"
    "            for index in range(1, instruction.b)\n"
    "        )\n"
    "        return CallExpr(function, args)\n",
    "call expression method",
)

replacements = [
    (
        "        elif name == \"MOVE\":\n"
        "            self._assign(instruction.a, self._ref(instruction.b, pc), pc)\n",
        "        elif name == \"MOVE\":\n"
        "            self._assign(instruction.a, self._ref_expr(instruction.b, pc), pc)\n",
        "MOVE",
    ),
    (
        "        elif name == \"GETGLOBAL\":\n"
        "            self._assign(instruction.a, self._global_key(instruction), pc)\n",
        "        elif name == \"GETGLOBAL\":\n"
        "            self._assign(\n"
        "                instruction.a,\n"
        "                RawExpr(self._global_key(instruction), Precedence.POSTFIX),\n"
        "                pc,\n"
        "            )\n",
        "GETGLOBAL",
    ),
    (
        "        elif name == \"GETIMPORT\":\n"
        "            self._assign(instruction.a, _decode_import(self.proto, instruction.aux), pc)\n",
        "        elif name == \"GETIMPORT\":\n"
        "            self._assign(\n"
        "                instruction.a,\n"
        "                RawExpr(\n"
        "                    _decode_import(self.proto, instruction.aux),\n"
        "                    Precedence.POSTFIX,\n"
        "                ),\n"
        "                pc,\n"
        "            )\n",
        "GETIMPORT",
    ),
    (
        "                _sanitize_identifier(upvalue, f\"upvalue_{instruction.b}\"),\n"
        "                pc,\n"
        "            )\n"
        "        elif name == \"SETUPVAL\":\n",
        "                NameExpr(\n"
        "                    _sanitize_identifier(upvalue, f\"upvalue_{instruction.b}\")\n"
        "                ),\n"
        "                pc,\n"
        "            )\n"
        "        elif name == \"SETUPVAL\":\n",
        "GETUPVAL",
    ),
    (
        "        elif name == \"GETTABLE\":\n"
        "            expression = (\n"
        "                f\"{self._ref(instruction.b, pc)}\"\n"
        "                f\"[{self._ref(instruction.c, pc)}]\"\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "        elif name == \"GETTABLE\":\n"
        "            expression = IndexExpr(\n"
        "                self._ref_expr(instruction.b, pc),\n"
        "                self._ref_expr(instruction.c, pc),\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "GETTABLE",
    ),
    (
        "        elif name in {\"GETTABLEKS\", \"GETUDATAKS\"}:\n"
        "            expression = _field(\n"
        "                self._ref(instruction.b, pc),\n"
        "                self._table_key(instruction),\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "        elif name in {\"GETTABLEKS\", \"GETUDATAKS\"}:\n"
        "            expression = FieldExpr(\n"
        "                self._ref_expr(instruction.b, pc),\n"
        "                self._table_key(instruction),\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "GETTABLEKS",
    ),
    (
        "        elif name == \"GETTABLEN\":\n"
        "            self._assign(\n"
        "                instruction.a,\n"
        "                f\"{self._ref(instruction.b, pc)}[{instruction.c + 1}]\",\n"
        "                pc,\n"
        "            )\n",
        "        elif name == \"GETTABLEN\":\n"
        "            self._assign(\n"
        "                instruction.a,\n"
        "                IndexExpr(\n"
        "                    self._ref_expr(instruction.b, pc),\n"
        "                    LiteralExpr(str(instruction.c + 1)),\n"
        "                ),\n"
        "                pc,\n"
        "            )\n",
        "GETTABLEN",
    ),
    (
        "        elif name in _BINARY_OPS:\n"
        "            expression = (\n"
        "                f\"{self._ref(instruction.b, pc)} {_BINARY_OPS[name]} \"\n"
        "                f\"{self._ref(instruction.c, pc)}\"\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "        elif name in _BINARY_OPS:\n"
        "            expression = BinaryExpr(\n"
        "                self._ref_expr(instruction.b, pc),\n"
        "                _BINARY_OPS[name],\n"
        "                self._ref_expr(instruction.c, pc),\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "binary operations",
    ),
    (
        "        elif name in _BINARY_CONST_OPS:\n"
        "            expression = (\n"
        "                f\"{self._ref(instruction.b, pc)} {_BINARY_CONST_OPS[name]} \"\n"
        "                f\"{_constant_expr(self.proto, instruction.c)}\"\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "        elif name in _BINARY_CONST_OPS:\n"
        "            expression = BinaryExpr(\n"
        "                self._ref_expr(instruction.b, pc),\n"
        "                _BINARY_CONST_OPS[name],\n"
        "                source_expr(_constant_expr(self.proto, instruction.c)),\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "binary constant operations",
    ),
    (
        "        elif name in {\"SUBRK\", \"DIVRK\"}:\n"
        "            operator = \"-\" if name == \"SUBRK\" else \"/\"\n"
        "            expression = (\n"
        "                f\"{_constant_expr(self.proto, instruction.b)} {operator} \"\n"
        "                f\"{self._ref(instruction.c, pc)}\"\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "        elif name in {\"SUBRK\", \"DIVRK\"}:\n"
        "            operator = \"-\" if name == \"SUBRK\" else \"/\"\n"
        "            expression = BinaryExpr(\n"
        "                source_expr(_constant_expr(self.proto, instruction.b)),\n"
        "                operator,\n"
        "                self._ref_expr(instruction.c, pc),\n"
        "            )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "reverse constant operations",
    ),
    (
        "        elif name in _UNARY_OPS:\n"
        "            self._assign(\n"
        "                instruction.a,\n"
        "                f\"{_UNARY_OPS[name]}{self._ref(instruction.b, pc)}\",\n"
        "                pc,\n"
        "            )\n",
        "        elif name in _UNARY_OPS:\n"
        "            self._assign(\n"
        "                instruction.a,\n"
        "                UnaryExpr(\n"
        "                    _UNARY_OPS[name].strip(),\n"
        "                    self._ref_expr(instruction.b, pc),\n"
        "                ),\n"
        "                pc,\n"
        "            )\n",
        "unary operations",
    ),
    (
        "        elif name == \"CONCAT\":\n"
        "            values = [\n"
        "                self._ref(register, pc)\n"
        "                for register in range(instruction.b, instruction.c + 1)\n"
        "            ]\n"
        "            self._assign(instruction.a, \" .. \".join(values), pc)\n",
        "        elif name == \"CONCAT\":\n"
        "            expression = self._ref_expr(instruction.c, pc)\n"
        "            for register in reversed(range(instruction.b, instruction.c)):\n"
        "                expression = BinaryExpr(\n"
        "                    self._ref_expr(register, pc),\n"
        "                    \"..\",\n"
        "                    expression,\n"
        "                )\n"
        "            self._assign(instruction.a, expression, pc)\n",
        "CONCAT",
    ),
    (
        "        elif name == \"NEWTABLE\":\n"
        "            self._assign(instruction.a, \"{}\", pc)\n",
        "        elif name == \"NEWTABLE\":\n"
        "            self._assign(instruction.a, TableExpr(), pc)\n",
        "NEWTABLE",
    ),
    (
        "        elif name in {\"NAMECALL\", \"NAMECALLUDATA\"}:\n"
        "            self.pending_namecalls[instruction.a] = (\n"
        "                self._ref(instruction.b, pc),\n"
        "                self._table_key(instruction),\n"
        "            )\n"
        "            self.register_names[instruction.a + 1] = self._ref(instruction.b, pc)\n",
        "        elif name in {\"NAMECALL\", \"NAMECALLUDATA\"}:\n"
        "            base = self._ref_expr(instruction.b, pc)\n"
        "            self.pending_namecalls[instruction.a] = (\n"
        "                base,\n"
        "                self._table_key(instruction),\n"
        "            )\n"
        "            self.register_names[instruction.a + 1] = render_expression(base)\n",
        "NAMECALL",
    ),
    (
        "            expression = self._call_expression(instruction)\n"
        "            if instruction.c == 1:\n"
        "                self.out.line(expression, statement=True)\n"
        "            elif instruction.c == 0:\n"
        "                self._assign(\n"
        "                    instruction.a,\n"
        "                    expression + \" --[[ multiple returns ]]\",\n"
        "                    pc,\n"
        "                )\n"
        "            else:\n",
        "            expression = self._call_expression(instruction)\n"
        "            if instruction.c == 1:\n"
        "                self.out.line(render_expression(expression), statement=True)\n"
        "            elif instruction.c == 0:\n"
        "                self._assign(\n"
        "                    instruction.a,\n"
        "                    RawExpr(\n"
        "                        render_expression(expression)\n"
        "                        + \" --[[ multiple returns ]]\"\n"
        "                    ),\n"
        "                    pc,\n"
        "                )\n"
        "            else:\n",
        "CALL output",
    ),
]
for old, new, label in replacements:
    lifter = replace_once(lifter, old, new, label)

lifter_path.write_text(lifter, encoding="utf-8")

ast_path = ROOT / "src/lunaux/backends/ast.py"
ast = ast_path.read_text(encoding="utf-8")
ast = replace_once(
    ast,
    "    if isinstance(expression, UnaryExpr):\n"
    "        operand = _render_child(expression.operand, Precedence.UNARY)\n"
    "        separator = \" \" if expression.operator == \"not\" else \"\"\n"
    "        return f\"{expression.operator}{separator}{operand}\"\n",
    "    if isinstance(expression, UnaryExpr):\n"
    "        operand = _render_child(expression.operand, Precedence.UNARY)\n"
    "        if isinstance(expression.operand, UnaryExpr):\n"
    "            operand = f\"({render_expression(expression.operand)})\"\n"
    "        separator = \" \" if expression.operator == \"not\" else \"\"\n"
    "        return f\"{expression.operator}{separator}{operand}\"\n",
    "nested unary rendering",
)
ast_path.write_text(ast, encoding="utf-8")

test_ast_path = ROOT / "tests/test_ast.py"
test_ast = test_ast_path.read_text(encoding="utf-8")
test_ast += (
    "\n\ndef test_nested_unary_never_becomes_a_comment() -> None:\n"
    "    expression = UnaryExpr(\"-\", UnaryExpr(\"-\", name(\"value\")))\n\n"
    "    assert render_expression(expression) == \"-(-value)\"\n"
)
test_ast_path.write_text(test_ast, encoding="utf-8")

test_lifter_path = ROOT / "tests/test_lifter_inlining.py"
test_lifter = test_lifter_path.read_text(encoding="utf-8")
test_lifter = replace_once(
    test_lifter,
    "    assert \"return (v0 + v0)\" in source\n",
    "    assert \"return v0 + v0\" in source\n",
    "AST inlining expectation",
)
test_lifter += (
    "\n\ndef test_nested_unary_inlining_is_valid_luau() -> None:\n"
    "    module = _module(\n"
    "        (\n"
    "            _ad(\"LOADN\", 0, 4),\n"
    "            _abc(\"MINUS\", 1, 0, 0),\n"
    "            _abc(\"MINUS\", 2, 1, 0),\n"
    "            _abc(\"RETURN\", 2, 2, 0),\n"
    "        )\n"
    "    )\n\n"
    "    source = decompile_module(module, {}, \"unary.luac\")\n\n"
    "    assert \"return -(-4)\" in source\n"
    "    assert \"--4\" not in source\n"
)
test_lifter_path.write_text(test_lifter, encoding="utf-8")
