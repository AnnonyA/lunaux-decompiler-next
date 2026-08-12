from __future__ import annotations

import re
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
    referenced_names,
    render_expression,
    source_expr,
)
from lunaux.backends.bytecode import LuauBytecodeModule
from lunaux.backends.compat_quality_lifter import (
    _CompatibilityQualityFunctionLifter,
    _rewrite_legacy_short_circuit_booleans,
)
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.roblox_recovery import closure_proto_id
from lunaux.backends.ssa import SSAValue

_SCALAR_CONSTANT_KINDS = frozenset({"nil", "boolean", "number", "integer", "string"})


class _SafeCompatibilityQualityFunctionLifter(_CompatibilityQualityFunctionLifter):
    """Narrow legacy fixes that preserve the 0.18 gate's proven semantics.

    Medal's useful behavior on legacy bytecode is explicit SSA destruction: values
    carried through loop phis and reference captures remain stable source bindings,
    while unrelated physical-register lifetimes stay separate.  Keep broad v6 phi
    coalescing disabled and recover only those identities that are directly proven by
    the SSA graph or CAPTURE instructions.
    """

    def _legacy_ssa_identity_enabled(self) -> bool:
        return False

    def _ssa_expression_folding_enabled(self) -> bool:
        # Stage 3 folds exact SSA values. It does not coalesce physical-register
        # lifetimes, so the legacy compatibility safety boundary remains intact.
        return True

    def _legacy_stripped(self) -> bool:
        return self.module.version <= 6 and not self.proto.locals

    def _phi_operand_values(self) -> frozenset[SSAValue]:
        cached = getattr(self, "_safe_phi_operand_values", None)
        if cached is not None:
            return cast(frozenset[SSAValue], cached)
        values = frozenset(operand for phi in self.ssa.phis for operand in phi.operands.values())
        self._safe_phi_operand_values = values
        return values

    def _captured_reference_names(self) -> dict[SSAValue, str]:
        cached = getattr(self, "_safe_captured_reference_names", None)
        if cached is not None:
            return cast(dict[SSAValue, str], cached)

        result: dict[SSAValue, str] = {}
        used = set().union(
            *(referenced_names(binding) for binding in self.upvalue_bindings.values())
        )
        for instruction in self.instructions:
            if instruction.name not in {"NEWCLOSURE", "DUPCLOSURE"}:
                continue
            child_id = closure_proto_id(self.proto, instruction)
            if child_id is None:
                continue
            child = self.module.protos[child_id]
            cursor = self.instruction_index_by_pc[instruction.pc] + 1
            captures = self.instructions[cursor : cursor + child.num_upvalues]
            for capture in captures:
                if capture.name != "CAPTURE" or capture.a != 1:
                    continue
                source = self.ssa.value_at_use(capture.pc, capture.b)
                if source is None or source in result:
                    continue
                base = "capturedValue"
                candidate = base
                suffix = 2
                while candidate in used:
                    candidate = f"{base}{suffix}"
                    suffix += 1
                result[source] = candidate
                used.add(candidate)
        self._safe_captured_reference_names = result
        return result

    def _value_used_by_open_tuple_consumer(self, value: SSAValue) -> bool:
        for ssa_instruction in self.ssa.instructions.values():
            if not any(use.value == value for use in ssa_instruction.uses):
                continue
            instruction = ssa_instruction.instruction
            if instruction.name in {"CALL", "CALLFB"} and instruction.b == 0:
                return True
            if instruction.name == "RETURN" and instruction.b == 0:
                return True
            if instruction.name == "SETLIST" and instruction.c == 0:
                return True
        return False

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
                # A loop/branch phi input is a source binding, not a disposable
                # temporary.  Medal materializes it before the structured region.
                and value not in self._phi_operand_values()
                # Reference captures must survive later physical-register reuse.
                and value not in self._captured_reference_names()
                # Fixed arguments adjacent to an open tuple must remain addressable;
                # v6 SELECT("#", ...) is the canonical case.
                and not self._value_used_by_open_tuple_consumer(value)
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
        value = self.ssa.value_defined_at(pc, register)
        captured_names = self._captured_reference_names()
        if value is not None and value in captured_names:
            name = captured_names[value]
            self._forced_value_names()[value] = name
            self.register_names[register] = name
            return name

        captured_identifiers = frozenset(captured_names.values())
        if (
            self._legacy_stripped()
            and value is not None
            and value not in captured_names
            and self.register_names.get(register) in captured_identifiers
        ):
            # The register was captured by reference earlier.  Reusing its lexical
            # name would mutate the closure's upvalue (e.g. replacing 0 with print).
            self.register_names.pop(register, None)

        name = super()._definition_name(register, pc)
        if not self._legacy_stripped() or name not in self._upvalue_identifier_names():
            return name

        instruction = self.instruction_by_pc.get(pc)
        if instruction is not None and instruction.name == "GETUPVAL":
            # The parent compatibility lifter already gives GETUPVAL temporaries a
            # non-shadowing name when they alias their binding.
            return name

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


def _normalize_boolean_operand(expression: str) -> str:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    return expression


def _rewrite_legacy_boolean_ladders(text: str) -> str:
    """Recover v3-v6 short-circuit boolean ladders after CFG structuring.

    O0 legacy Luau stores the boolean result in a register that can have an unrelated
    lifetime immediately before the branch.  The structured emitter can therefore
    leave that stale value on the false edge.  Recognize the exact LOADB-style ladder
    and express the same boolean selection directly, matching Medal's SSA destruction
    without depending on benchmark constants or variable names.
    """

    lines = text.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        outer = re.fullmatch(r"(?P<indent>\s*)if\s+(.+)\s+then", lines[index])
        if outer is None or index + 8 >= len(lines):
            result.append(lines[index])
            index += 1
            continue

        indent = outer.group("indent")
        child = indent + "    "
        grandchild = child + "    "
        first = re.fullmatch(
            rf"{re.escape(child)}(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*not\s+(.+)",
            lines[index + 1],
        )
        if first is None:
            result.append(lines[index])
            index += 1
            continue
        name = first.group("name")
        empty_guard = lines[index + 2] == f"{child}if not {name} then"
        empty_end = lines[index + 3] == f"{child}end"
        second = re.fullmatch(
            rf"{re.escape(child)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 4],
        )
        positive_guard = lines[index + 5] == f"{child}if {name} then"
        third = re.fullmatch(
            rf"{re.escape(grandchild)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 6],
        )
        inner_end = lines[index + 7] == f"{child}end"
        outer_end = lines[index + 8] == f"{indent}end"
        if not (
            empty_guard
            and empty_end
            and second is not None
            and positive_guard
            and third is not None
            and inner_end
            and outer_end
        ):
            result.append(lines[index])
            index += 1
            continue

        negated_operand = _normalize_boolean_operand(first.group(2))
        second_operand = _normalize_boolean_operand(second.group(1))
        if negated_operand != second_operand:
            result.append(lines[index])
            index += 1
            continue

        declared = any(
            re.search(rf"\blocal\b[^\n]*\b{re.escape(name)}\b", previous)
            for previous in lines[:index]
        )
        prefix = "" if declared else "local "
        condition = outer.group(2).strip()
        tail = third.group(1).strip()
        result.append(
            f"{indent}{prefix}{name} = "
            f"({condition} and not ({second_operand})) or "
            f"({second_operand} and ({tail}))"
        )
        index += 9

    return "\n".join(result).rstrip() + "\n"


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
            cleaned = _rewrite_legacy_boolean_ladders(cleaned)
        return cleaned
    finally:
        legacy._FunctionLifter = previous_lifter  # type: ignore[misc]


disassemble_module = legacy.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
