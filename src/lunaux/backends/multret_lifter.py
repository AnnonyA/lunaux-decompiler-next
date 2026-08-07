from __future__ import annotations

from dataclasses import replace

import lunaux.backends.lifter as legacy
from lunaux.backends.ast import CallExpr, Expr, MethodCallExpr, NameExpr, render_expression, source_expr
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAMultiUse, SSAMultiValue


class _MultiRetFunctionLifter(legacy._FunctionLifter):
    """Extends the core lifter with validated open-tuple and compatibility fixes."""

    def _multret_expressions(self) -> dict[SSAMultiValue, Expr]:
        expressions = getattr(self, "_v020_multret_expressions", None)
        if expressions is None:
            expressions = {}
            self._v020_multret_expressions = expressions
        return expressions

    def _consumer_for(self, value: SSAMultiValue) -> SSAMultiUse | None:
        return next(
            (use for use in self.ssa.multi_values.uses if use.value == value),
            None,
        )

    def _name(self, register: int, pc: int) -> str:
        # In stripped/optimized bytecode the same physical register frequently carries
        # several SSA versions around a loop. Once we have emitted a declaration for
        # that register, keep the source identifier stable unless real debug-scope
        # metadata explicitly introduces a different binding.
        if self.scope_tree.binding_for_register(register, pc) is None:
            existing = self.register_names.get(register)
            if existing is not None:
                return existing
        return super()._name(register, pc)

    def _definition_name(self, register: int, pc: int) -> str:
        if self.scope_tree.binding_for_register(register, pc) is None:
            existing = self.register_names.get(register)
            if existing is not None:
                return existing
        return super()._definition_name(register, pc)

    def _annotated_name(self, register: int, name: str, pc: int) -> str:
        annotated = super()._annotated_name(register, name, pc)
        # Bare `function` is a bytecode type tag, not valid Luau annotation syntax.
        # Dropping only this lossy annotation is safer than emitting uncompilable code.
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
            )
        finally:
            self.return_type_override = original_override
            self.symbols = original_symbols

    def _open_table_parent_for_producer(
        self,
        instruction: DecodedInstruction,
    ) -> legacy.PendingTableLiteral | None:
        next_instruction = self.next_instruction_by_pc.get(instruction.pc)
        if (
            next_instruction is None
            or next_instruction.name != "SETLIST"
            or next_instruction.c != 0
            or next_instruction.b != instruction.a
        ):
            return None
        pending = self._pending_table_for_write(next_instruction)
        if pending is None:
            return None
        access = self.analysis.register_accesses[instruction.pc]
        if pending.register in access.uses:
            return None
        # Luau's SETLIST AUX already contains the first 1-based table index.
        start_index = next_instruction.aux or 0
        return pending if pending.can_add_open_tail(start_index) else None

    def _record_table_write(self, instruction: DecodedInstruction) -> bool:
        if instruction.name != "SETLIST":
            return super()._record_table_write(instruction)

        pending = self._pending_table_for_write(instruction)
        if pending is None:
            return False
        pc = instruction.pc
        target = legacy.table_write_target_register(instruction)
        source_registers = legacy.table_write_source_registers(instruction)
        if target is not None and target in source_registers:
            self._flush_pending_table(pending)
            return False

        start_index = instruction.aux or 0
        if instruction.c > 0:
            count = instruction.c - 1
            entries: list[tuple[int, Expr, frozenset[legacy.SSAValue]]] = []
            for index in range(count):
                captured = self._capture_register_expression(
                    pending,
                    instruction.b + index,
                    pc,
                    allow_nested=True,
                )
                if captured is None:
                    break
                value, dependencies = captured
                entries.append((start_index + index, value, dependencies))
            if len(entries) == count and pending.add_indices(tuple(entries)):
                return True
        else:
            open_captured = self.pending_open_table_values.pop(instruction.b, None)
            if open_captured is not None and open_captured[2] == pc:
                value, dependencies, _consumer_pc = open_captured
                if pending.add_open_tail(start_index, value, dependencies):
                    self._flush_pending_table(pending)
                    return True

        self._flush_pending_table(pending)
        return False

    def _captured_closure_expression(
        self,
        instruction: DecodedInstruction,
    ) -> bool:
        if instruction.name not in {"NEWCLOSURE", "DUPCLOSURE"}:
            return False
        child_id = legacy.closure_proto_id(self.proto, instruction)
        if child_id is None:
            return False
        child = self.module.protos[child_id]
        if child.num_upvalues <= 0:
            return False

        cursor = self.instruction_index_by_pc[instruction.pc] + 1
        captures = self.instructions[cursor : cursor + child.num_upvalues]
        self_recursive = any(
            capture.name == "CAPTURE"
            and capture.a in {0, 1}
            and capture.b == instruction.a
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
            context = self.contextual_plan.for_value(
                self.ssa.value_defined_at(instruction.pc, instruction.a)
            )
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
        use = self.ssa.multi_use_at(instruction.pc)
        if use is None or use.kind != "arguments":
            return super()._call_expression(instruction)

        tail = self._multret_expressions().get(use.value)
        if tail is None:
            return super()._call_expression(instruction)

        self._multret_expressions().pop(use.value, None)
        if instruction.a in self.pending_namecalls:
            base, method = self.pending_namecalls.pop(instruction.a)
            fixed = tuple(
                self._ref_expr(register, instruction.pc)
                for register in use.prefix_registers
                if register >= instruction.a + 2
            )
            return MethodCallExpr(base, method, (*fixed, tail))

        function = self._ref_expr(instruction.a, instruction.pc)
        fixed = tuple(
            self._ref_expr(register, instruction.pc)
            for register in use.prefix_registers
        )
        return CallExpr(function, (*fixed, tail))

    def _lift_instruction(self, instruction: DecodedInstruction) -> None:
        name = instruction.name
        pc = instruction.pc

        if self._captured_closure_expression(instruction):
            return

        if name in {"CALL", "CALLFB"} and instruction.c == 0:
            value = self.ssa.multi_value_at(pc)
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
            value = self.ssa.multi_value_at(pc)
            if value is not None:
                consumer = self._consumer_for(value)
                if consumer is not None and consumer.kind in {"arguments", "return"}:
                    self._multret_expressions()[value] = source_expr("...")
                    return

        if name == "RETURN" and instruction.b == 0:
            use = self.ssa.multi_use_at(pc)
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


# The legacy module resolves this class dynamically when it creates function lifters,
# including nested callbacks and class methods. Installing the extension once keeps all
# existing public entry points compatible without duplicating the large core emitter.
legacy._FunctionLifter = _MultiRetFunctionLifter  # type: ignore[misc]

decompile_module = legacy.decompile_module
disassemble_module = legacy.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
