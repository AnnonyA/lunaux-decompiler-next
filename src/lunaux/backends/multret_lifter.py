from __future__ import annotations

from dataclasses import replace
from typing import cast

import lunaux.backends.lifter as legacy
from lunaux.backends.ast import (
    CallExpr,
    Expr,
    MethodCallExpr,
    NameExpr,
    render_expression,
    source_expr,
)
from lunaux.backends.opcodes import DecodedInstruction, setlist_semantics
from lunaux.backends.roblox_recovery import closure_proto_id
from lunaux.backends.ssa import SSAMultiUse, SSAMultiValue, SSAValue
from lunaux.backends.table_recovery import (
    PendingTableLiteral,
    table_write_source_registers,
    table_write_target_register,
)


class _MultiRetFunctionLifter(legacy._FunctionLifter):
    """Extends the core lifter with validated open-tuple and compatibility fixes."""

    def _multret_expressions(self) -> dict[SSAMultiValue, Expr]:
        expressions = getattr(self, "_v020_multret_expressions", None)
        if expressions is None:
            expressions = {}
            self._v020_multret_expressions = expressions
        return expressions

    def _persistent_multret_plan(
        self,
    ) -> tuple[dict[int, SSAMultiValue], dict[int, SSAMultiUse]]:
        """Track Luau's open stack top until consumed, replaced, or clobbered.

        Medal keeps the dynamic stack top alive across ordinary instructions. We retain
        that useful behavior, but invalidate the tuple if an intervening instruction
        overwrites any register in its open tail; this preserves LunaUX's conservative
        guarantee for bytecode that does not prove the tuple remained intact.
        """

        cached = getattr(self, "_v020_persistent_multret_plan", None)
        if cached is not None:
            return cast(tuple[dict[int, SSAMultiValue], dict[int, SSAMultiUse]], cached)

        values: dict[int, SSAMultiValue] = {}
        uses: dict[int, SSAMultiUse] = {}
        for block in self.analysis.blocks:
            if block.start_pc not in self.analysis.reachable:
                continue
            pending: SSAMultiValue | None = None
            for instruction in block.instructions:
                consumed = False
                consumer: tuple[str, int] | None = None
                if instruction.name in {"CALL", "CALLFB"} and instruction.b == 0:
                    consumer = ("arguments", instruction.a + 1)
                elif instruction.name == "RETURN" and instruction.b == 0:
                    consumer = ("return", instruction.a)
                else:
                    semantics = setlist_semantics(instruction)
                    if semantics is not None and semantics.is_open:
                        consumer = ("setlist", semantics.first_value_register)

                if consumer is not None and pending is not None:
                    kind, base_register = consumer
                    if pending.base_register >= base_register:
                        uses[instruction.pc] = SSAMultiUse(
                            consumer_pc=instruction.pc,
                            base_register=base_register,
                            kind=kind,  # type: ignore[arg-type]
                            value=pending,
                            prefix_registers=tuple(range(base_register, pending.base_register)),
                        )
                        consumed = True

                producer: SSAMultiValue | None = None
                if instruction.name in {"CALL", "CALLFB"} and instruction.c == 0:
                    producer = SSAMultiValue(
                        origin_pc=instruction.pc,
                        base_register=instruction.a,
                        kind="call",
                    )
                elif instruction.name == "GETVARARGS" and instruction.b == 0:
                    producer = SSAMultiValue(
                        origin_pc=instruction.pc,
                        base_register=instruction.a,
                        kind="varargs",
                    )

                if producer is not None:
                    values[instruction.pc] = producer
                    pending = producer
                elif consumed:
                    pending = None
                elif pending is not None:
                    access = self.analysis.register_accesses[instruction.pc]
                    if any(register >= pending.base_register for register in access.definitions):
                        pending = None

        cached_plan = (values, uses)
        self._v020_persistent_multret_plan = cached_plan
        return cached_plan

    def _persistent_multret_value(self, pc: int) -> SSAMultiValue | None:
        return self._persistent_multret_plan()[0].get(pc)

    def _persistent_multret_use(self, pc: int) -> SSAMultiUse | None:
        return self._persistent_multret_plan()[1].get(pc)

    def _consumer_for(self, value: SSAMultiValue) -> SSAMultiUse | None:
        return next(
            (use for use in self._persistent_multret_plan()[1].values() if use.value == value),
            None,
        )

    def _forced_value_names(self) -> dict[SSAValue, str]:
        names = getattr(self, "_v020_forced_value_names", None)
        if names is None:
            names = {}
            self._v020_forced_value_names = names
        return names

    def _loop_carried_names(self) -> dict[SSAValue, str]:
        """Coalesce loop-header phi webs back into mutable source variables.

        SSA versions are useful for analysis but must not escape into source as a new
        lexical local on every iteration. Medal performs an explicit SSA destruction
        phase; this ports the essential part into LunaUX while preserving our existing
        symbol/type recovery and structured loop analysis.
        """

        cached = getattr(self, "_v020_loop_carried_names", None)
        if cached is not None:
            return cast(dict[SSAValue, str], cached)

        parent: dict[SSAValue, SSAValue] = {}

        def find(value: SSAValue) -> SSAValue:
            parent.setdefault(value, value)
            root = value
            while parent[root] != root:
                root = parent[root]
            while parent[value] != value:
                next_value = parent[value]
                parent[value] = root
                value = next_value
            return root

        def union(left: SSAValue, right: SSAValue) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for phi in self.ssa.phis:
            find(phi.result)
            for operand in phi.operands.values():
                union(phi.result, operand)

        components: dict[SSAValue, set[SSAValue]] = {}
        for value in tuple(parent):
            components.setdefault(find(value), set()).add(value)

        anchors: dict[SSAValue, tuple[SSAValue, int]] = {}
        for loop in self.analysis.loops:
            for phi in self.ssa.phis:
                if phi.block != loop.header:
                    continue
                outside = [
                    value
                    for predecessor, value in phi.operands.items()
                    if predecessor not in loop.body
                ]
                inside = [
                    value for predecessor, value in phi.operands.items() if predecessor in loop.body
                ]
                if not outside or not inside:
                    continue
                root = find(phi.result)
                candidate = outside[0]
                previous = anchors.get(root)
                candidate_pc = candidate.origin_pc if candidate.origin_pc is not None else -1
                previous_pc = (
                    previous[0].origin_pc
                    if previous is not None and previous[0].origin_pc is not None
                    else -1
                )
                if previous is None or candidate_pc < previous_pc:
                    anchors[root] = (candidate, phi.register)

        result: dict[SSAValue, str] = {}
        for root, (anchor, register) in anchors.items():
            name: str | None = None
            if self.symbols is not None:
                symbol = self.symbols.symbol_for(anchor)
                if symbol is not None:
                    name = symbol.name
            if name is None:
                name = self.register_names.get(register, f"v{register}")
            for value in components.get(root, {anchor}):
                result[value] = name

        self._v020_loop_carried_names = result
        return result

    def _name(self, register: int, pc: int) -> str:
        value = self.ssa.value_at_use(pc, register)
        if value is not None:
            forced = self._forced_value_names().get(value)
            if forced is not None:
                self.register_names[register] = forced
                return forced
            loop_name = self._loop_carried_names().get(value)
            if loop_name is not None:
                self.register_names[register] = loop_name
                return loop_name

        if (
            self.scope_tree.binding_for_register(register, pc) is None
            and self.options.smart_variable_names
            and self.symbols is not None
        ):
            recovered = self.symbols.name_at_use(pc, register)
            existing = self.register_names.get(register)
            if (
                recovered is not None
                and recovered not in self.declared
                and existing is not None
                and existing in self.declared
            ):
                return existing
        return super()._name(register, pc)

    def _definition_name(self, register: int, pc: int) -> str:
        value = self.ssa.value_defined_at(pc, register)
        if value is not None:
            forced = self._forced_value_names().get(value)
            if forced is not None:
                self.register_names[register] = forced
                return forced
            loop_name = self._loop_carried_names().get(value)
            if loop_name is not None:
                self.register_names[register] = loop_name
                return loop_name

        name = super()._definition_name(register, pc)
        instruction = self.instruction_by_pc.get(pc)
        if (
            value is not None
            and instruction is not None
            and instruction.name == "GETUPVAL"
            and instruction.a == register
        ):
            binding = self.upvalue_bindings.get(instruction.b)
            if isinstance(binding, NameExpr):
                binding_name = render_expression(binding)
                if name == binding_name:
                    base = f"{binding_name}Value"
                    safe = base
                    suffix = 2
                    while safe in self.declared:
                        safe = f"{base}{suffix}"
                        suffix += 1
                    self._forced_value_names()[value] = safe
                    self.register_names[register] = safe
                    return safe
        return name

    def _annotated_name(self, register: int, name: str, pc: int) -> str:
        annotated = super()._annotated_name(register, name, pc)
        if annotated in {f"{name}: function", f"{name}: function?"}:
            return name
        return annotated

    def lift(
        self,
        *,
        as_function: bool,
        function_name_override: str | None = None,
        local_function: bool = True,
        anonymous_function: bool = False,
        method_declaration: tuple[Expr, str] | None = None,
        field_function_declaration: tuple[Expr, str] | None = None,
    ) -> None:
        original_override = self.return_type_override
        original_symbols = self.symbols
        if self.return_type_override in {"function", "function?"}:
            self.return_type_override = None
        if self.symbols is not None and self.symbols.return_type in {"function", "function?"}:
            self.symbols = replace(self.symbols, return_type=None)
        try:
            super().lift(
                as_function=as_function,
                function_name_override=function_name_override,
                local_function=local_function,
                anonymous_function=anonymous_function,
                method_declaration=method_declaration,
                field_function_declaration=field_function_declaration,
            )
        finally:
            self.return_type_override = original_override
            self.symbols = original_symbols

    def _open_table_parent_for_producer(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        return super()._open_table_parent_for_producer(instruction)

    def _record_table_write(self, instruction: DecodedInstruction) -> bool:
        if instruction.name != "SETLIST":
            return super()._record_table_write(instruction)

        pending = self._pending_table_for_write(instruction)
        if pending is None:
            return False
        pc = instruction.pc
        target = table_write_target_register(instruction)
        source_registers = table_write_source_registers(instruction)
        if target is not None and target in source_registers:
            self._flush_pending_table(pending)
            return False

        semantics = setlist_semantics(instruction)
        if semantics is None:
            return False
        start_index = semantics.semantic_first_array_index
        if semantics.is_fixed:
            count = semantics.fixed_value_count or 0
            entries: list[tuple[int, Expr, frozenset[SSAValue]]] = []
            for entry_index in range(count):
                captured = self._capture_register_expression(
                    pending,
                    instruction.b + entry_index,
                    pc,
                    allow_nested=True,
                )
                if captured is None:
                    break
                value, dependencies = captured
                entries.append((start_index + entry_index, value, dependencies))
            if len(entries) == count and pending.add_setlist_entries(tuple(entries)):
                return True
        else:
            open_captured = self.pending_open_table_values.pop(pc, None)
            if open_captured is not None and open_captured[2] == pc:
                value, dependencies, _consumer_pc = open_captured
                multi_use = self.ssa.multi_use_at(pc)
                prefix_registers = (
                    multi_use.prefix_registers
                    if multi_use is not None and multi_use.kind == "setlist"
                    else ()
                )
                fixed_entries: list[
                    tuple[int, Expr, frozenset[SSAValue]]
                ] = []
                for offset, register in enumerate(prefix_registers):
                    captured = self._capture_register_expression(
                        pending,
                        register,
                        pc,
                        allow_nested=True,
                    )
                    if captured is None:
                        break
                    prefix_value, prefix_dependencies = captured
                    fixed_entries.append(
                        (start_index + offset, prefix_value, prefix_dependencies)
                    )
                if len(fixed_entries) == len(prefix_registers) and pending.add_open_setlist(
                    start_index,
                    tuple(fixed_entries),
                    value,
                    dependencies,
                ):
                    return True

        self._flush_pending_table(pending)
        return False

    def _captured_closure_expression(
        self,
        instruction: DecodedInstruction,
    ) -> bool:
        if instruction.name not in {"NEWCLOSURE", "DUPCLOSURE"}:
            return False
        planned = (
            self.parent_proto_plan.at_creation(instruction.pc)
            if self.parent_proto_plan is not None
            else None
        )
        if planned is not None and planned.emission_kind != "shared-proto":
            return False
        child_id = closure_proto_id(self.proto, instruction)
        if child_id is None:
            return False
        value = self.ssa.value_defined_at(instruction.pc, instruction.a)
        if value is not None and value in self.callback_plan.proto_by_value:
            return False
        child = self.module.protos[child_id]
        if child.num_upvalues <= 0:
            return False

        cursor = self.instruction_index_by_pc[instruction.pc] + 1
        captures = self.instructions[cursor : cursor + child.num_upvalues]
        self_recursive = any(
            capture.name == "CAPTURE" and capture.a in {0, 1} and capture.b == instruction.a
            for capture in captures
        )
        if self_recursive:
            name = self._definition_name(instruction.a, instruction.pc)
            bindings, _dependencies = self._callback_capture_bindings(instruction, child)
            for upvalue_index, capture in enumerate(captures):
                if capture.a in {0, 1} and capture.b == instruction.a:
                    bindings[upvalue_index] = NameExpr(name)
            self.register_names[instruction.a] = name
            self.declared.add(name)
            context = self.contextual_plan.for_value(value)
            _MultiRetFunctionLifter(
                self.module,
                child,
                self.proto_names,
                self.options,
                self.out,
                inline_only_proto_ids=self.inline_only_proto_ids,
                upvalue_bindings=bindings,
                parameter_name_overrides=(
                    dict(context.parameter_names) if context is not None else None
                ),
                parameter_type_overrides=(
                    dict(context.parameter_types) if context is not None else None
                ),
                return_type_override=context.return_type if context is not None else None,
                module_analysis=self.module_analysis,
                proto_emission_plan=self.proto_emission_plan,
            ).lift(
                as_function=True,
                function_name_override=name,
                local_function=True,
            )
            return True

        expression, _dependencies = self._anonymous_function_expr(child_id, instruction)
        self._assign(instruction.a, expression, instruction.pc)
        return True

    def _call_expression(self, instruction: DecodedInstruction) -> Expr:
        use = self._persistent_multret_use(instruction.pc)
        if use is None or use.kind != "arguments":
            return super()._call_expression(instruction)

        tail = self._multret_expressions().get(use.value)
        if tail is None:
            return super()._call_expression(instruction)

        self._multret_expressions().pop(use.value, None)
        frame = self.call_frames.at(instruction.pc)
        if instruction.a in self.pending_namecalls:
            base, method = self.pending_namecalls.pop(instruction.a)
            registers = (
                frame.argument_registers
                if frame is not None
                else tuple(
                    register for register in use.prefix_registers if register >= instruction.a + 2
                )
            )
            fixed = tuple(self._ref_expr(register, instruction.pc) for register in registers)
            return MethodCallExpr(base, method, (*fixed, tail))

        function = self._ref_expr(instruction.a, instruction.pc)
        registers = frame.argument_registers if frame is not None else use.prefix_registers
        fixed = tuple(self._ref_expr(register, instruction.pc) for register in registers)
        return CallExpr(function, (*fixed, tail))

    def _handle_loop_prep(self, instruction: DecodedInstruction) -> bool:
        if instruction.name == "FORNPREP":
            target = legacy._jump_target(instruction)
            variable_register = instruction.a + 3
            variable = self._definition_name(variable_register, instruction.pc)
            value = self.ssa.value_defined_at(instruction.pc, variable_register)
            if value is not None:
                self._forced_value_names()[value] = variable
            self.register_names[variable_register] = variable
            self.declared.add(variable)
            start = self._ref(instruction.a + 2, instruction.pc)
            limit = self._ref(instruction.a, instruction.pc)
            step = self._ref(instruction.a + 1, instruction.pc)
            header = f"for {variable} = {start}, {limit}"
            if self.options.preserve_for_step or step not in ("1", "1.0"):
                header += f", {step}"
            header += " do"
            return self._open_until(target, header)

        generic_prep = {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}
        if instruction.name in generic_prep:
            loop_pc = legacy._jump_target(instruction)
            loop_instruction = self.instruction_by_pc.get(loop_pc)
            variable_count = 2
            close_pc = loop_pc + 1
            if loop_instruction is not None and loop_instruction.name == "FORGLOOP":
                variable_count = max(1, (loop_instruction.aux or 1) & 0xFF)
                close_pc = loop_pc + loop_instruction.size
            variables: list[str] = []
            for variable_index in range(variable_count):
                register = instruction.a + 3 + variable_index
                variable = (
                    self._definition_name(register, loop_pc)
                    if loop_instruction is not None and loop_instruction.name == "FORGLOOP"
                    else self._name(register, instruction.pc)
                )
                variables.append(variable)
                self.register_names[register] = variable
                if loop_instruction is not None and loop_instruction.name == "FORGLOOP":
                    value = self.ssa.value_defined_at(loop_pc, register)
                    if value is not None:
                        self._forced_value_names()[value] = variable
            self.declared.update(variables)
            iterator = self._ref(instruction.a, instruction.pc)
            state = self._ref(instruction.a + 1, instruction.pc)
            control = self._ref(instruction.a + 2, instruction.pc)
            return self._open_until(
                close_pc,
                f"for {', '.join(variables)} in {iterator}, {state}, {control} do",
            )
        return False

    def _lift_instruction(self, instruction: DecodedInstruction) -> None:
        name = instruction.name
        pc = instruction.pc

        if self._captured_closure_expression(instruction):
            return

        if name in {"CALL", "CALLFB"} and instruction.c == 0:
            value = self._persistent_multret_value(pc)
            if value is not None:
                consumer = self._consumer_for(value)
                if consumer is not None and consumer.kind in {"arguments", "return"}:
                    if name == "CALLFB":
                        slot = "sealed" if instruction.aux == 0xFFFFFFFF else str(instruction.aux)
                        self.out.line(f"-- call feedback slot: {slot}")
                    expression = self._call_expression(instruction)
                    self._multret_expressions()[value] = expression
                    return

        if name == "GETVARARGS" and instruction.b == 0:
            value = self._persistent_multret_value(pc)
            if value is not None:
                consumer = self._consumer_for(value)
                if consumer is not None and consumer.kind in {"arguments", "return"}:
                    self._multret_expressions()[value] = source_expr("...")
                    return

        if name == "RETURN" and instruction.b == 0:
            use = self._persistent_multret_use(pc)
            tail = (
                self._multret_expressions().pop(use.value, None)
                if use is not None and use.kind == "return"
                else None
            )
            if use is not None and tail is not None:
                values = [self._ref(register, pc) for register in use.prefix_registers]
                values.append(render_expression(tail))
                self.out.line("return " + ", ".join(values), statement=True)
                return

        super()._lift_instruction(instruction)


legacy._FunctionLifter = _MultiRetFunctionLifter  # type: ignore[misc]

decompile_module = legacy.decompile_module
disassemble_module = legacy.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
