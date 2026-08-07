from __future__ import annotations

import lunaux.backends.lifter as legacy
from lunaux.backends.ast import CallExpr, Expr, MethodCallExpr, render_expression, source_expr
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAMultiUse, SSAMultiValue


class _MultiRetFunctionLifter(legacy._FunctionLifter):
    """Extends the core lifter with validated open-tuple source emission."""

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
