from __future__ import annotations

from typing import cast

import lunaux.backends.lifter as legacy
import lunaux.backends.quality_lifter as quality
from lunaux.backends.ast import (
    BinaryExpr,
    Expr,
    LiteralExpr,
    NameExpr,
    UnaryExpr,
    ensure_expr,
    render_expression,
    source_expr,
)
from lunaux.backends.bytecode import LuauBytecodeModule
from lunaux.backends.compat_quality_lifter import (
    _CompatibilityQualityFunctionLifter,
    _rewrite_legacy_short_circuit_booleans,
)
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAValue

_SCALAR_CONSTANT_KINDS = frozenset({"nil", "boolean", "number", "integer", "string"})


class _SafeCompatibilityQualityFunctionLifter(_CompatibilityQualityFunctionLifter):
    """Narrow legacy fixes that preserve the 0.18 gate's proven semantics.

    The broad stripped-v6 SSA coalescing experiment improved readability but merged
    unrelated register lifetimes. Keep that experiment disabled and recover only
    values whose identity can be proved locally: scalar literals, pure expressions
    needed to replace otherwise-undefined temporaries, and names that would shadow a
    captured upvalue.
    """

    def _legacy_ssa_identity_enabled(self) -> bool:
        return False

    def _legacy_stripped(self) -> bool:
        return self.module.version <= 6 and not self.proto.locals

    def _safe_scalar_instruction(self, instruction: DecodedInstruction) -> bool:
        if instruction.name in {"LOADNIL", "LOADB", "LOADN"}:
            return True
        if instruction.name == "LOADK":
            index = instruction.d
        elif instruction.name == "LOADKX":
            index = instruction.aux if instruction.aux is not None else -1
        else:
            return False
        if not 0 <= index < len(self.proto.constants):
            return False
        return self.proto.constants[index].kind in _SCALAR_CONSTANT_KINDS

    def _assign(self, register: int, expression: Expr | str, pc: int) -> None:
        if self._legacy_stripped():
            value = self.ssa.value_defined_at(pc, register)
            instruction = self.instruction_by_pc.get(pc)
            if (
                value is not None
                and instruction is not None
                and self.ssa.uses_of(value) == 1
                and self.scope_tree.binding_for_register(register, pc) is None
                and self._safe_scalar_instruction(instruction)
            ):
                self.inline_expressions[value] = ensure_expr(expression)
                self.register_names.setdefault(register, f"v{register}")
                return
        super()._assign(register, expression, pc)

    def _upvalue_identifier_names(self) -> frozenset[str]:
        cached = getattr(self, "_safe_upvalue_identifier_names", None)
        if cached is not None:
            return cast(frozenset[str], cached)
        names = frozenset(
            rendered
            for binding in self.upvalue_bindings.values()
            if legacy._IDENTIFIER.fullmatch(rendered := render_expression(binding))
        )
        self._safe_upvalue_identifier_names = names
        return names

    def _definition_name(self, register: int, pc: int) -> str:
        name = super()._definition_name(register, pc)
        if not self._legacy_stripped() or name not in self._upvalue_identifier_names():
            return name

        instruction = self.instruction_by_pc.get(pc)
        if instruction is not None and instruction.name == "GETUPVAL":
            # The parent compatibility lifter already gives GETUPVAL temporaries a
            # non-shadowing name when they alias their binding.
            return name

        value = self.ssa.value_defined_at(pc, register)
        base = f"{name}Local"
        candidate = base
        suffix = 2
        occupied = self.declared | set(self._upvalue_identifier_names())
        while candidate in occupied:
            candidate = f"{base}{suffix}"
            suffix += 1
        if value is not None:
            self._forced_value_names()[value] = candidate
        self.register_names[register] = candidate
        return candidate

    def _legacy_operand_expression(
        self,
        pc: int,
        register: int,
        seen: frozenset[SSAValue],
    ) -> Expr | None:
        value = self.ssa.value_at_use(pc, register)
        if value is None:
            return None
        direct = self.inline_expressions.get(value)
        if direct is not None:
            return direct

        name = self._name(register, pc)
        if name in self.declared:
            return NameExpr(name)
        reconstructed = self._legacy_value_expression(value, seen)
        if reconstructed is not None:
            return reconstructed
        return None

    def _legacy_constant_expression(self, instruction: DecodedInstruction) -> Expr | None:
        if instruction.name == "LOADNIL":
            return LiteralExpr("nil")
        if instruction.name == "LOADB":
            return LiteralExpr("true" if instruction.b else "false")
        if instruction.name == "LOADN":
            return LiteralExpr(str(instruction.d))
        if instruction.name == "LOADK":
            index = instruction.d
        elif instruction.name == "LOADKX":
            index = instruction.aux if instruction.aux is not None else -1
        else:
            return None
        if not 0 <= index < len(self.proto.constants):
            return None
        if self.proto.constants[index].kind not in _SCALAR_CONSTANT_KINDS:
            return None
        return source_expr(legacy._constant_expr(self.proto, index))

    def _legacy_value_expression(
        self,
        value: SSAValue,
        seen: frozenset[SSAValue] = frozenset(),
    ) -> Expr | None:
        if value in seen or value.kind != "instruction" or value.origin_pc is None:
            return None
        direct = self.inline_expressions.get(value)
        if direct is not None:
            return direct
        instruction = self.instruction_by_pc.get(value.origin_pc)
        if instruction is None:
            return None

        scalar = self._legacy_constant_expression(instruction)
        if scalar is not None:
            return scalar

        next_seen = seen | frozenset({value})
        if instruction.name == "MOVE":
            return self._legacy_operand_expression(
                instruction.pc,
                instruction.b,
                next_seen,
            )

        if instruction.name in legacy._BINARY_OPS:
            left = self._legacy_operand_expression(instruction.pc, instruction.b, next_seen)
            right = self._legacy_operand_expression(instruction.pc, instruction.c, next_seen)
            if left is not None and right is not None:
                return BinaryExpr(left, legacy._BINARY_OPS[instruction.name], right)
            return None

        if instruction.name in legacy._BINARY_CONST_OPS:
            left = self._legacy_operand_expression(instruction.pc, instruction.b, next_seen)
            if left is None or not 0 <= instruction.c < len(self.proto.constants):
                return None
            constant = self.proto.constants[instruction.c]
            if constant.kind not in _SCALAR_CONSTANT_KINDS:
                return None
            right = source_expr(legacy._constant_expr(self.proto, instruction.c))
            return BinaryExpr(left, legacy._BINARY_CONST_OPS[instruction.name], right)

        if instruction.name in {"SUBRK", "DIVRK"}:
            if not 0 <= instruction.b < len(self.proto.constants):
                return None
            constant = self.proto.constants[instruction.b]
            if constant.kind not in _SCALAR_CONSTANT_KINDS:
                return None
            right = self._legacy_operand_expression(instruction.pc, instruction.c, next_seen)
            if right is None:
                return None
            left = source_expr(legacy._constant_expr(self.proto, instruction.b))
            operator = "-" if instruction.name == "SUBRK" else "/"
            return BinaryExpr(left, operator, right)

        if instruction.name in legacy._UNARY_OPS:
            operand = self._legacy_operand_expression(instruction.pc, instruction.b, next_seen)
            if operand is not None:
                return UnaryExpr(legacy._UNARY_OPS[instruction.name].strip(), operand)
        return None

    def _ref_expr(self, register: int, pc: int) -> Expr:
        if self._legacy_stripped():
            value = self.ssa.value_at_use(pc, register)
            if value is not None:
                direct = self.inline_expressions.get(value)
                if direct is not None:
                    return direct
                name = self._name(register, pc)
                if name not in self.declared:
                    reconstructed = self._legacy_value_expression(value)
                    if reconstructed is not None:
                        return reconstructed
        return super()._ref_expr(register, pc)


def decompile_module(
    module: LuauBytecodeModule,
    options: dict[str, bool],
    filename: str | None,
) -> str:
    previous_lifter = legacy._FunctionLifter
    legacy._FunctionLifter = _SafeCompatibilityQualityFunctionLifter  # type: ignore[misc]
    try:
        cleaned = quality._clean_output(legacy.decompile_module(module, options, filename))
        if module.version <= 6:
            cleaned = _rewrite_legacy_short_circuit_booleans(cleaned)
        return cleaned
    finally:
        legacy._FunctionLifter = previous_lifter  # type: ignore[misc]


disassemble_module = legacy.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
