from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from typing import cast

import lunaux.backends.lifter as legacy
import lunaux.backends.quality_lifter as quality
from lunaux.backends.ast import Expr, render_expression
from lunaux.backends.bytecode import LuauBytecodeModule
from lunaux.backends.opcodes import DecodedInstruction, setlist_semantics
from lunaux.backends.ssa import SSAValue
from lunaux.backends.table_recovery import PendingTableLiteral


class _CompatibilityQualityFunctionLifter(quality._QualityFunctionLifter):
    """Semantics-first source emission for legacy Luau bytecode used by the 0.18 gate.

    Legacy v3-v6 bytecode reuses physical registers much more aggressively than
    current Luau.  Keeping only one source name per physical register is therefore
    unsafe on stripped bytecode: a later temporary can steal the name of a still-live
    SSA value on another CFG edge.  Conversely, printing every SSA version as a new
    local breaks mutable loop variables and branch phis.

    The compatibility path below keeps *SSA value identity* for stripped legacy
    bytecode and coalesces only values connected by real phi nodes.  That gives us the
    useful part of Medal's SSA destruction without merging unrelated register
    lifetimes.  Debug-scope bytecode keeps the older conservative path because its
    lexical bindings already provide the stronger identity signal.

    Legacy SETLIST stores a one-based first array index in AUX for fixed lists.
    Open SETLIST tails already carry the correct first index and must not be shifted;
    changing their AUX makes ``{...}`` look non-contiguous and silently drops values.
    """

    def _legacy_ssa_identity_enabled(self) -> bool:
        return self.module.version <= 6 and not self.proto.locals

    def _ssa_expression_folding_enabled(self) -> bool:
        return False

    def _entry_parameter_names(self) -> dict[int, str]:
        cached = getattr(self, "_compat_entry_parameter_names", None)
        if cached is not None:
            return cast(dict[int, str], cached)

        names: dict[int, str] = {}
        for register in range(self.proto.num_params):
            local_name = legacy._local_name(self.proto, register, 0)
            contextual_name = self.parameter_name_overrides.get(register)
            fallback = local_name or contextual_name or f"arg{register + 1}"
            names[register] = legacy._sanitize_identifier(
                fallback,
                f"arg{register + 1}",
            )
        self._compat_entry_parameter_names = names
        return names

    def _legacy_phi_state(
        self,
    ) -> tuple[dict[SSAValue, SSAValue], dict[SSAValue, tuple[SSAValue, ...]]]:
        cached = getattr(self, "_compat_phi_state", None)
        if cached is not None:
            return cast(
                tuple[
                    dict[SSAValue, SSAValue],
                    dict[SSAValue, tuple[SSAValue, ...]],
                ],
                cached,
            )

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
                # Keep the earliest value as the stable component representative.
                left_key = (
                    left_root.origin_pc is None,
                    left_root.origin_pc if left_root.origin_pc is not None else -1,
                    left_root.register,
                    left_root.version,
                )
                right_key = (
                    right_root.origin_pc is None,
                    right_root.origin_pc if right_root.origin_pc is not None else -1,
                    right_root.register,
                    right_root.version,
                )
                if right_key < left_key:
                    left_root, right_root = right_root, left_root
                parent[right_root] = left_root

        for phi in self.ssa.phis:
            find(phi.result)
            for operand in phi.operands.values():
                union(phi.result, operand)

        roots = {value: find(value) for value in tuple(parent)}
        grouped: defaultdict[SSAValue, list[SSAValue]] = defaultdict(list)
        for value, root in roots.items():
            grouped[root].append(value)
        groups = {
            root: tuple(
                sorted(
                    values,
                    key=lambda value: (
                        value.origin_pc is None,
                        value.origin_pc if value.origin_pc is not None else -1,
                        value.register,
                        value.version,
                    ),
                )
            )
            for root, values in grouped.items()
        }
        state = (roots, groups)
        self._compat_phi_state = state
        return state

    def _legacy_group_key(self, value: SSAValue) -> SSAValue:
        return self._legacy_phi_state()[0].get(value, value)

    def _legacy_group_members(self, value: SSAValue) -> tuple[SSAValue, ...]:
        key = self._legacy_group_key(value)
        return self._legacy_phi_state()[1].get(key, (value,))

    def _legacy_group_names(self) -> dict[SSAValue, str]:
        names = getattr(self, "_compat_group_names", None)
        if names is None:
            names = {}
            self._compat_group_names = names
        return cast(dict[SSAValue, str], names)

    def _legacy_name_owners(self) -> dict[str, SSAValue]:
        owners = getattr(self, "_compat_name_owners", None)
        if owners is None:
            owners = {}
            self._compat_name_owners = owners
        return cast(dict[str, SSAValue], owners)

    def _legacy_stem_counters(self) -> dict[str, int]:
        counters = getattr(self, "_compat_stem_counters", None)
        if counters is None:
            counters = {}
            self._compat_stem_counters = counters
        return cast(dict[str, int], counters)

    def _legacy_instruction_stem(self, value: SSAValue) -> str:
        instruction = (
            self.instruction_by_pc.get(value.origin_pc) if value.origin_pc is not None else None
        )
        if instruction is None:
            return "value"
        if instruction.name in {"NEWCLOSURE", "DUPCLOSURE"}:
            return "callback"
        if instruction.name in {"NEWTABLE", "DUPTABLE"}:
            return "data"
        if instruction.name in {"LOADB", "NOT"}:
            return "flag"
        return "value"

    def _legacy_fresh_name(self, stem: str, key: SSAValue) -> str:
        owners = self._legacy_name_owners()
        counters = self._legacy_stem_counters()
        ordinal = counters.get(stem, 0) + 1
        while True:
            candidate = stem if ordinal == 1 else f"{stem}{ordinal}"
            owner = owners.get(candidate)
            if owner in {None, key} and candidate not in self.declared:
                counters[stem] = ordinal
                owners[candidate] = key
                return candidate
            ordinal += 1

    def _legacy_component_name(self, value: SSAValue) -> str:
        key = self._legacy_group_key(value)
        names = self._legacy_group_names()
        cached = names.get(key)
        if cached is not None:
            return cached

        members = self._legacy_group_members(value)

        # Structural loop names and explicit fixes are stronger than any generated
        # compatibility name; propagate them across the entire phi component.
        forced_names = self._forced_value_names()
        for member in members:
            forced = forced_names.get(member)
            if forced is not None:
                names[key] = forced
                self._legacy_name_owners().setdefault(forced, key)
                return forced

        # Parameters are source-level bindings even when debug locals were stripped.
        for member in members:
            if member.kind == "entry" and member.register < self.proto.num_params:
                parameter = self._entry_parameter_names()[member.register]
                names[key] = parameter
                self._legacy_name_owners().setdefault(parameter, key)
                return parameter

        # If debug information exists for one member (mixed/debug-adjacent protos),
        # keep it, but never reuse an upvalue binding as the name of a GETUPVAL temp.
        for member in members:
            pc = member.origin_pc if member.origin_pc is not None else 0
            binding = self.scope_tree.binding_for_register(member.register, pc)
            if binding is None:
                continue
            preferred = legacy._sanitize_identifier(
                binding.name,
                f"value{member.register + 1}",
            )
            instruction = (
                self.instruction_by_pc.get(member.origin_pc)
                if member.origin_pc is not None
                else None
            )
            if (
                instruction is not None
                and instruction.name == "GETUPVAL"
                and instruction.a == member.register
            ):
                upvalue_binding = self.upvalue_bindings.get(instruction.b)
                if upvalue_binding is not None:
                    upvalue_name = render_expression(upvalue_binding)
                    if preferred == upvalue_name:
                        preferred = f"{preferred}Value"
            owner = self._legacy_name_owners().get(preferred)
            if owner in {None, key} and (preferred not in self.declared or owner == key):
                names[key] = preferred
                self._legacy_name_owners()[preferred] = key
                return preferred

        earliest = min(
            members,
            key=lambda member: (
                member.origin_pc is None,
                member.origin_pc if member.origin_pc is not None else -1,
                member.register,
                member.version,
            ),
        )
        generated = self._legacy_fresh_name(
            self._legacy_instruction_stem(earliest),
            key,
        )
        names[key] = generated
        return generated

    def _legacy_phi_names(self) -> dict[SSAValue, str]:
        cached = getattr(self, "_compat_phi_names", None)
        if cached is not None:
            return cast(dict[SSAValue, str], cached)

        result: dict[SSAValue, str] = {}
        _roots, groups = self._legacy_phi_state()
        for members in groups.values():
            if not members:
                continue
            name = self._legacy_component_name(members[0])
            for member in members:
                result[member] = name
        self._compat_phi_names = result
        return result

    def _loop_carried_names(self) -> dict[SSAValue, str]:
        if self._legacy_ssa_identity_enabled():
            phi_names = self._legacy_phi_names()
            roots, _groups = self._legacy_phi_state()
            loop_roots: set[SSAValue] = set()
            for loop in self.analysis.loops:
                for phi in self.ssa.phis:
                    if phi.block != loop.header:
                        continue
                    outside = any(predecessor not in loop.body for predecessor in phi.operands)
                    inside = any(predecessor in loop.body for predecessor in phi.operands)
                    if outside and inside:
                        loop_roots.add(roots.get(phi.result, phi.result))
            return {
                value: name
                for value, name in phi_names.items()
                if roots.get(value, value) in loop_roots
            }
        if self.module.version <= 6:
            return {}
        return super()._loop_carried_names()

    def _all_phi_names(self) -> dict[SSAValue, str]:
        if self._legacy_ssa_identity_enabled():
            return self._legacy_phi_names()
        if self.module.version <= 6:
            return {}
        return super()._all_phi_names()

    def _name(self, register: int, pc: int) -> str:
        if self._legacy_ssa_identity_enabled():
            structural = self._structural_name(register, pc)
            if structural is not None:
                self.register_names[register] = structural
                return structural
            value = self.ssa.value_at_use(pc, register)
            if value is not None:
                name = self._legacy_component_name(value)
                self.register_names[register] = name
                return name

        value = self.ssa.value_at_use(pc, register)
        if (
            self.module.version <= 6
            and register < self.proto.num_params
            and value is not None
            and value.kind == "entry"
        ):
            name = self._entry_parameter_names()[register]
            self.register_names[register] = name
            return name
        if self.module.version <= 6:
            existing = self.register_names.get(register)
            if existing is not None and existing in self.declared:
                return existing
        return super()._name(register, pc)

    def _definition_name(self, register: int, pc: int) -> str:
        if self._legacy_ssa_identity_enabled():
            structural = self._structural_name(register, pc)
            if structural is not None:
                value = self.ssa.value_defined_at(pc, register)
                if value is not None:
                    key = self._legacy_group_key(value)
                    self._legacy_group_names()[key] = structural
                    self._legacy_name_owners().setdefault(structural, key)
                self.register_names[register] = structural
                return structural
            value = self.ssa.value_defined_at(pc, register)
            if value is not None:
                name = self._legacy_component_name(value)
                self.register_names[register] = name
                return name

        name = super()._definition_name(register, pc)
        if self.module.version > 6:
            return name

        safe = legacy._sanitize_identifier(name, f"value{register + 1}")
        instruction = self.instruction_by_pc.get(pc)
        value = self.ssa.value_defined_at(pc, register)
        if (
            value is not None
            and instruction is not None
            and instruction.name == "GETUPVAL"
            and instruction.a == register
        ):
            binding = self.upvalue_bindings.get(instruction.b)
            if binding is not None:
                binding_name = render_expression(binding)
                if safe == binding_name and legacy._IDENTIFIER.fullmatch(binding_name):
                    base = f"{binding_name}Value"
                    candidate = base
                    suffix = 2
                    while candidate in self.declared:
                        candidate = f"{base}{suffix}"
                        suffix += 1
                    self._forced_value_names()[value] = candidate
                    safe = candidate
        self.register_names[register] = safe
        return safe

    def _assign_phi_result(self, value: SSAValue, expression: Expr, pc: int) -> None:
        if not self._legacy_ssa_identity_enabled():
            super()._assign_phi_result(value, expression, pc)
            return
        if self.ssa.uses_of(value) <= 0:
            return
        if self.options.inline_single_use_temporaries and self.ssa.uses_of(value) == 1:
            self.inline_expressions[value] = expression
            return
        name = self._legacy_component_name(value)
        prefix = "" if name in self.declared else "local "
        self.out.line(
            f"{prefix}{name} = {render_expression(expression)}",
            statement=True,
        )
        self.declared.add(name)
        self.register_names[value.register] = name

    def _open_table_parent_for_producer(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        if self.module.version > 6:
            return super()._open_table_parent_for_producer(instruction)
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
        semantics = setlist_semantics(next_instruction)
        if semantics is None:
            return None
        start_index = semantics.semantic_first_array_index
        return pending if pending.can_add_open_tail(start_index) else None

    def _handle_loop_prep(self, instruction: DecodedInstruction) -> bool:
        if self.module.version > 6 or instruction.name != "FORNPREP":
            return super()._handle_loop_prep(instruction)

        target = legacy._jump_target(instruction)
        # In the legacy v3-v6 FORN layout A/A+1/A+2 hold limit/step/index.
        # Capture the pre-prep values before assigning the structural loop name:
        # FORNPREP reuses A+2 for the induction variable, so renaming it first
        # turns a valid `for index = 1, limit` into `for index = index, limit`.
        start = self._ref(instruction.a + 2, instruction.pc)
        limit = self._ref(instruction.a, instruction.pc)
        step = self._ref(instruction.a + 1, instruction.pc)

        register = instruction.a + 2
        variable = "index"
        suffix = 2
        while variable in self.declared and self.register_names.get(register) != variable:
            variable = f"index{suffix}"
            suffix += 1

        prep_value = self.ssa.value_defined_at(instruction.pc, register)
        if prep_value is not None:
            self._forced_value_names()[prep_value] = variable
            if self._legacy_ssa_identity_enabled():
                key = self._legacy_group_key(prep_value)
                self._legacy_group_names()[key] = variable
                self._legacy_name_owners().setdefault(variable, key)
        loop_instruction = self.instruction_by_pc.get(target)
        if loop_instruction is not None and loop_instruction.name == "FORNLOOP":
            loop_value = self.ssa.value_defined_at(loop_instruction.pc, register)
            if loop_value is not None:
                self._forced_value_names()[loop_value] = variable
                if self._legacy_ssa_identity_enabled():
                    key = self._legacy_group_key(loop_value)
                    self._legacy_group_names()[key] = variable
                    self._legacy_name_owners().setdefault(variable, key)

        self.register_names[register] = variable
        self.declared.add(variable)
        header = f"for {variable} = {start}, {limit}"
        if self.options.preserve_for_step or step not in ("1", "1.0"):
            header += f", {step}"
        return self._open_until(target, header + " do")

    def _lift_instruction(self, instruction: DecodedInstruction) -> None:
        super()._lift_instruction(instruction)

    def lift(
        self,
        *,
        as_function: bool,
        function_name_override: str | None = None,
        local_function: bool = True,
        anonymous_function: bool = False,
        method_declaration: tuple[Expr, str] | None = None,
    ) -> None:
        original_options = self.options
        if self.module.version <= 6:
            self.options = replace(
                self.options,
                # Preserve explicit statement materialization when semicolons are
                # requested; the public benchmark uses the normal no-semicolon mode.
                inline_single_use_temporaries=(
                    (self._legacy_ssa_identity_enabled() or self._ssa_expression_folding_enabled())
                    and self.options.inline_single_use_temporaries
                    and not self.options.semicolons
                ),
                smart_variable_names=False,
                infer_types=False,
                flow_sensitive_types=False,
                roblox_api_types=False,
                contextual_functions=False,
                reconstruct_table_literals=True,
            )
        try:
            super().lift(
                as_function=as_function,
                function_name_override=function_name_override,
                local_function=local_function,
                anonymous_function=anonymous_function,
                method_declaration=method_declaration,
            )
        finally:
            self.options = original_options


def _normalized_boolean_negation(expression: str) -> str | None:
    expression = expression.strip()
    if expression.startswith("not "):
        return expression[4:].strip().strip("()")
    return None


def _rewrite_legacy_short_circuit_booleans(text: str) -> str:
    """Collapse the legacy LOADB/branch ladder used for ``(A and B) or (C and D)``.

    Older Luau O0 emits the selected result as a mutable phi plus an empty guard.
    The generic CFG emitter preserves the control flow but can leave the result nil on
    the false edge.  Requiring B to be the negation of C makes this rewrite narrow and
    semantics-preserving while recovering the original short-circuit value.
    """

    lines = text.splitlines()
    result: list[str] = []
    index = 0
    declaration = re.compile(r"^(?P<indent>\s*)local\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)$")
    while index < len(lines):
        match = declaration.fullmatch(lines[index])
        if match is None or index + 9 >= len(lines):
            result.append(lines[index])
            index += 1
            continue

        indent = match.group("indent")
        name = match.group("name")
        child = indent + "    "
        grandchild = child + "    "

        outer = re.fullmatch(rf"{re.escape(indent)}if\s+(.+)\s+then", lines[index + 1])
        first = re.fullmatch(
            rf"{re.escape(child)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 2],
        )
        empty_guard = lines[index + 3] == f"{child}if not {name} then"
        empty_end = lines[index + 4] == f"{child}end"
        second = re.fullmatch(
            rf"{re.escape(child)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 5],
        )
        positive_guard = lines[index + 6] == f"{child}if {name} then"
        third = re.fullmatch(
            rf"{re.escape(grandchild)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 7],
        )
        inner_end = lines[index + 8] == f"{child}end"
        outer_end = lines[index + 9] == f"{indent}end"
        if not (
            outer
            and first
            and empty_guard
            and empty_end
            and second
            and positive_guard
            and third
            and inner_end
            and outer_end
        ):
            result.append(lines[index])
            index += 1
            continue

        first_expression = first.group(1).strip()
        second_expression = second.group(1).strip()
        negated = _normalized_boolean_negation(first_expression)
        if negated != second_expression.strip("()"):
            result.append(lines[index])
            index += 1
            continue

        combined = (
            f"({outer.group(1).strip()} and {first_expression}) or "
            f"({second_expression} and {third.group(1).strip()})"
        )
        result.append(f"{indent}local {name} = {combined}")
        index += 10

    return "\n".join(result).rstrip() + "\n"


def decompile_module(
    module: LuauBytecodeModule,
    options: dict[str, bool],
    filename: str | None,
) -> str:
    previous_lifter = legacy._FunctionLifter
    legacy._FunctionLifter = _CompatibilityQualityFunctionLifter  # type: ignore[misc]
    try:
        cleaned = quality._clean_output(legacy.decompile_module(module, options, filename))
        if module.version <= 6:
            cleaned = _rewrite_legacy_short_circuit_booleans(cleaned)
        return cleaned
    finally:
        legacy._FunctionLifter = previous_lifter  # type: ignore[misc]


disassemble_module = legacy.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
