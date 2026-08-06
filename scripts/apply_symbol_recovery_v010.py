from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src/lunaux/backends/lifter.py"
text = path.read_text(encoding="utf-8")

replacements = (
    (
        "from lunaux.backends.analysis import analyze_control_flow\nfrom lunaux.backends.ast import (",
        "from lunaux.backends.analysis import analyze_control_flow\n"
        "from lunaux.backends.classes import recover_classes\n"
        "from lunaux.backends.ast import (",
    ),
    (
        "from lunaux.backends.ssa import SSAValue, build_ssa\n",
        "from lunaux.backends.ssa import SSAValue, build_ssa\n"
        "from lunaux.backends.symbols import SymbolRecovery, build_symbol_recovery\n",
    ),
    (
        "    preserve_for_step: bool\n    inline_single_use_temporaries: bool\n",
        "    preserve_for_step: bool\n"
        "    inline_single_use_temporaries: bool\n"
        "    smart_variable_names: bool\n"
        "    infer_types: bool\n"
        "    show_recovered_symbols: bool\n"
        "    recover_classes: bool\n",
    ),
    (
        "            inline_single_use_temporaries=options.get(\n"
        "                \"InlineSingleUseTemporaries\",\n"
        "                True,\n"
        "            ),\n"
        "        )\n",
        "            inline_single_use_temporaries=options.get(\n"
        "                \"InlineSingleUseTemporaries\",\n"
        "                True,\n"
        "            ),\n"
        "            smart_variable_names=options.get(\"SmartVariableNames\", True),\n"
        "            infer_types=options.get(\"InferTypes\", True),\n"
        "            show_recovered_symbols=options.get(\n"
        "                \"ShowRecoveredSymbols\",\n"
        "                False,\n"
        "            ),\n"
        "            recover_classes=options.get(\"RecoverClasses\", True),\n"
        "        )\n",
    ),
    (
        "        self.ssa = build_ssa(\n"
        "            self.instructions,\n"
        "            len(proto.code),\n"
        "            analysis=self.analysis,\n"
        "        )\n"
        "        self.inline_plan = plan_expression_inlining(self.ssa, proto)\n",
        "        self.ssa = build_ssa(\n"
        "            self.instructions,\n"
        "            len(proto.code),\n"
        "            analysis=self.analysis,\n"
        "        )\n"
        "        self.symbols: SymbolRecovery | None = None\n"
        "        if (\n"
        "            options.smart_variable_names\n"
        "            or options.infer_types\n"
        "            or options.show_recovered_symbols\n"
        "        ):\n"
        "            self.symbols = build_symbol_recovery(\n"
        "                module,\n"
        "                proto,\n"
        "                self.instructions,\n"
        "                self.ssa,\n"
        "            )\n"
        "        self.class_plan = recover_classes(\n"
        "            module,\n"
        "            proto,\n"
        "            self.instructions,\n"
        "            self.ssa,\n"
        "        )\n"
        "        self.inline_plan = plan_expression_inlining(self.ssa, proto)\n",
    ),
    (
        "    def _name(self, register: int, pc: int) -> str:\n"
        "        binding = self.scope_tree.binding_for_register(register, pc)\n"
        "        if binding is not None:\n"
        "            active = _sanitize_identifier(binding.name, f\"v{register}\")\n"
        "            self.register_names[register] = active\n"
        "            return active\n"
        "        return self.register_names.get(register, f\"v{register}\")\n",
        "    def _name(self, register: int, pc: int) -> str:\n"
        "        binding = self.scope_tree.binding_for_register(register, pc)\n"
        "        if binding is not None:\n"
        "            active = _sanitize_identifier(binding.name, f\"v{register}\")\n"
        "            self.register_names[register] = active\n"
        "            return active\n"
        "        if self.options.smart_variable_names and self.symbols is not None:\n"
        "            recovered = self.symbols.name_at_use(pc, register)\n"
        "            if recovered is not None:\n"
        "                self.register_names[register] = recovered\n"
        "                return recovered\n"
        "        return self.register_names.get(register, f\"v{register}\")\n"
        "\n"
        "    def _definition_name(self, register: int, pc: int) -> str:\n"
        "        binding = self.scope_tree.binding_for_register(register, pc)\n"
        "        if binding is not None:\n"
        "            active = _sanitize_identifier(binding.name, f\"v{register}\")\n"
        "            self.register_names[register] = active\n"
        "            return active\n"
        "        if self.options.smart_variable_names and self.symbols is not None:\n"
        "            recovered = self.symbols.name_at_definition(pc, register)\n"
        "            if recovered is not None:\n"
        "                self.register_names[register] = recovered\n"
        "                return recovered\n"
        "        return self.register_names.get(register, f\"v{register}\")\n",
    ),
    (
        "    def _annotated_name(self, register: int, name: str, pc: int) -> str:\n"
        "        type_name = _local_type(self.module, self.proto, register, pc)\n"
        "        return f\"{name}: {type_name}\" if type_name and type_name != \"any\" else name\n",
        "    def _annotated_name(self, register: int, name: str, pc: int) -> str:\n"
        "        type_name: str | None = None\n"
        "        if self.options.infer_types and self.symbols is not None:\n"
        "            type_name = self.symbols.type_at_definition(pc, register)\n"
        "            if type_name is None and pc == 0:\n"
        "                type_name = self.symbols.entry_types.get(register)\n"
        "        if type_name is None:\n"
        "            type_name = _local_type(self.module, self.proto, register, pc)\n"
        "        return f\"{name}: {type_name}\" if type_name and type_name != \"any\" else name\n",
    ),
    (
        "        name = self._name(register, pc)\n",
        "        name = self._definition_name(register, pc)\n",
    ),
    (
        "        names = [self._name(register, pc) for register in registers]\n",
        "        names = [self._definition_name(register, pc) for register in registers]\n",
    ),
    (
        "    def lift(self, *, as_function: bool) -> None:\n"
        "        parameters = []\n"
        "        for register in range(self.proto.num_params):\n"
        "            name = _local_name(self.proto, register, 0) or f\"arg{register + 1}\"\n"
        "            name = _sanitize_identifier(name, f\"arg{register + 1}\")\n"
        "            parameters.append(self._annotated_name(register, name, 0))\n"
        "            self.register_names[register] = name\n"
        "            self.declared.add(name)\n"
        "        if self.proto.is_vararg:\n"
        "            parameters.append(\"...\")\n"
        "\n"
        "        if as_function:\n"
        "            function_name = self.proto_names[self.proto.proto_id]\n"
        "            self.out.open(f\"local function {function_name}({', '.join(parameters)})\")\n",
        "    def lift(\n"
        "        self,\n"
        "        *,\n"
        "        as_function: bool,\n"
        "        function_name_override: str | None = None,\n"
        "        local_function: bool = True,\n"
        "    ) -> None:\n"
        "        parameters = []\n"
        "        for register in range(self.proto.num_params):\n"
        "            recovered_name = (\n"
        "                self.symbols.entry_names.get(register)\n"
        "                if self.options.smart_variable_names and self.symbols is not None\n"
        "                else None\n"
        "            )\n"
        "            name = (\n"
        "                _local_name(self.proto, register, 0)\n"
        "                or recovered_name\n"
        "                or f\"arg{register + 1}\"\n"
        "            )\n"
        "            name = _sanitize_identifier(name, f\"arg{register + 1}\")\n"
        "            parameters.append(self._annotated_name(register, name, 0))\n"
        "            self.register_names[register] = name\n"
        "            self.declared.add(name)\n"
        "        if self.proto.is_vararg:\n"
        "            parameters.append(\"...\")\n"
        "\n"
        "        if as_function:\n"
        "            function_name = (\n"
        "                function_name_override or self.proto_names[self.proto.proto_id]\n"
        "            )\n"
        "            prefix = \"local function\" if local_function else \"function\"\n"
        "            header = f\"{prefix} {function_name}({', '.join(parameters)})\"\n"
        "            if (\n"
        "                self.options.infer_types\n"
        "                and self.symbols is not None\n"
        "                and self.symbols.return_type\n"
        "                and self.symbols.return_type != \"any\"\n"
        "            ):\n"
        "                header += f\": {self.symbols.return_type}\"\n"
        "            self.out.open(header)\n",
    ),
    (
        "        if self.options.upvalue_comment and self.proto.num_upvalues:\n",
        "        if self.options.show_recovered_symbols and self.symbols is not None:\n"
        "            report = self.symbols.report_lines()\n"
        "            if report:\n"
        "                self.out.line(\"-- recovered symbols:\")\n"
        "                for line in report:\n"
        "                    self.out.line(\"--   \" + line)\n"
        "        if self.options.upvalue_comment and self.proto.num_upvalues:\n",
    ),
    (
        "            if instruction.pc in self.repeat_conditions:\n",
        "            if instruction.pc in self.class_plan.skipped_instruction_pcs:\n"
        "                continue\n"
        "            if instruction.pc in self.repeat_conditions:\n",
    ),
    (
        "    def _lift_instruction(self, instruction: DecodedInstruction) -> None:\n",
        "    def _emit_recovered_class(self, instruction: DecodedInstruction) -> bool:\n"
        "        declaration = self.class_plan.at(instruction.pc)\n"
        "        if declaration is None:\n"
        "            return False\n"
        "        class_name = _sanitize_identifier(declaration.name, \"AnonymousClass\")\n"
        "        self.register_names[instruction.a] = class_name\n"
        "        self.declared.add(class_name)\n"
        "        self.out.open(f\"class {class_name}\")\n"
        "        if declaration.superclass_register is not None:\n"
        "            superclass = self._ref(declaration.superclass_register, instruction.pc)\n"
        "            self.out.line(f\"-- superclass: {superclass}\")\n"
        "        for property_name in declaration.properties:\n"
        "            property_name = _sanitize_identifier(property_name, \"property\")\n"
        "            self.out.line(f\"public {property_name}\")\n"
        "        if declaration.properties and declaration.methods:\n"
        "            self.out.line()\n"
        "        for method in declaration.methods:\n"
        "            method_name = _sanitize_identifier(method.name, \"method\")\n"
        "            if method.proto_id is None:\n"
        "                self.out.line(f\"-- unresolved method {method_name}\")\n"
        "                continue\n"
        "            child = self.module.protos[method.proto_id]\n"
        "            _FunctionLifter(\n"
        "                self.module,\n"
        "                child,\n"
        "                self.proto_names,\n"
        "                self.options,\n"
        "                self.out,\n"
        "            ).lift(\n"
        "                as_function=True,\n"
        "                function_name_override=method_name,\n"
        "                local_function=False,\n"
        "            )\n"
        "        self.out.close()\n"
        "        return True\n"
        "\n"
        "    def _lift_instruction(self, instruction: DecodedInstruction) -> None:\n",
    ),
    (
        "        elif name == \"NEWCLASS\":\n"
        "            constant = _constant(self.proto, instruction.aux or 0)\n"
        "            class_name = \"AnonymousClass\"\n"
        "            if (\n"
        "                constant\n"
        "                and constant.kind == \"class_shape\"\n"
        "                and isinstance(constant.value, ClassShapeConstant)\n"
        "            ):\n"
        "                class_name, _, _ = _class_shape_names(self.proto, constant.value)\n"
        "            superclass = (\n"
        "                \"nil\"\n"
        "                if instruction.b == 0xFF\n"
        "                else self._ref(instruction.b, pc)\n"
        "            )\n"
        "            self._assign(\n"
        "                instruction.a,\n"
        "                f\"{{}} --[[ class {class_name}; superclass={superclass} ]]\",\n"
        "                pc,\n"
        "            )\n",
        "        elif name == \"NEWCLASS\":\n"
        "            if self.options.recover_classes and self._emit_recovered_class(instruction):\n"
        "                return\n"
        "            constant = _constant(self.proto, instruction.aux or 0)\n"
        "            class_name = \"AnonymousClass\"\n"
        "            if (\n"
        "                constant\n"
        "                and constant.kind == \"class_shape\"\n"
        "                and isinstance(constant.value, ClassShapeConstant)\n"
        "            ):\n"
        "                class_name, _, _ = _class_shape_names(self.proto, constant.value)\n"
        "            superclass = (\n"
        "                \"nil\"\n"
        "                if instruction.b == 0xFF\n"
        "                else self._ref(instruction.b, pc)\n"
        "            )\n"
        "            self._assign(\n"
        "                instruction.a,\n"
        "                f\"{{}} --[[ class {class_name}; superclass={superclass} ]]\",\n"
        "                pc,\n"
        "            )\n",
    ),
)

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match, found {count}: {old[:100]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
