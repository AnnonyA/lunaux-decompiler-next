from __future__ import annotations

from dataclasses import replace
from typing import cast

import lunaux.backends.lifter as legacy
import lunaux.backends.quality_lifter as quality
from lunaux.backends.ast import NameExpr, render_expression
from lunaux.backends.bytecode import LuauBytecodeModule
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAValue
from lunaux.backends.table_recovery import PendingTableLiteral


class _CompatibilityQualityFunctionLifter(quality._QualityFunctionLifter):
    """Semantics-first source emission for legacy Luau bytecode used by the 0.18 gate.

    Modern quality recovery deliberately performs aggressive SSA destruction and
    source-level renaming. That is useful on current bytecode, but on v3-v6 the
    allocator reuses physical registers much more aggressively and those cosmetic
    rewrites can accidentally merge unrelated lifetimes. The compatibility path
    therefore keeps physical-register identity stable and only applies structural
    names when they are tied to a concrete SSA definition.

    Legacy SETLIST stores a one-based first array index in AUX for fixed lists.
    Open SETLIST tails already carry the correct first index and must not be shifted;
    changing their AUX makes ``{...}`` look non-contiguous and silently drops values.
    """

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

    def _loop_carried_names(self) -> dict[SSAValue, str]:
        if self.module.version <= 6:
            return {}
        return super()._loop_carried_names()

    def _all_phi_names(self) -> dict[SSAValue, str]:
        if self.module.version <= 6:
            return {}
        return super()._all_phi_names()

    def _name(self, register: int, pc: int) -> str:
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

    def _legacy_setlist(self, instruction: DecodedInstruction) -> DecodedInstruction:
        if (
            self.module.version <= 6
            and instruction.name == "SETLIST"
            and instruction.c > 0
            and instruction.aux is not None
        ):
            return replace(instruction, aux=max(0, instruction.aux - 1))
        return instruction

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
        start_index = max(1, next_instruction.aux or 1)
        return pending if pending.can_add_open_tail(start_index) else None

    def _handle_loop_prep(self, instruction: DecodedInstruction) -> bool:
        if self.module.version > 6 or instruction.name != "FORNPREP":
            return super()._handle_loop_prep(instruction)

        target = legacy._jump_target(instruction)
        register = instruction.a + 3
        variable = "index"
        suffix = 2
        while variable in self.declared and self.register_names.get(register) != variable:
            variable = f"index{suffix}"
            suffix += 1

        prep_value = self.ssa.value_defined_at(instruction.pc, register)
        if prep_value is not None:
            self._forced_value_names()[prep_value] = variable
        loop_instruction = self.instruction_by_pc.get(target)
        if loop_instruction is not None and loop_instruction.name == "FORNLOOP":
            loop_value = self.ssa.value_defined_at(loop_instruction.pc, register)
            if loop_value is not None:
                self._forced_value_names()[loop_value] = variable

        self.register_names[register] = variable
        self.declared.add(variable)
        start = self._ref(instruction.a + 2, instruction.pc)
        limit = self._ref(instruction.a, instruction.pc)
        step = self._ref(instruction.a + 1, instruction.pc)
        header = f"for {variable} = {start}, {limit}"
        if self.options.preserve_for_step or step not in ("1", "1.0"):
            header += f", {step}"
        return self._open_until(target, header + " do")

    def _lift_instruction(self, instruction: DecodedInstruction) -> None:
        super()._lift_instruction(self._legacy_setlist(instruction))

    def lift(
        self,
        *,
        as_function: bool,
        function_name_override: str | None = None,
        local_function: bool = True,
        anonymous_function: bool = False,
    ) -> None:
        original_options = self.options
        if self.module.version <= 6:
            self.options = replace(
                self.options,
                inline_single_use_temporaries=False,
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
            )
        finally:
            self.options = original_options


def decompile_module(
    module: LuauBytecodeModule,
    options: dict[str, bool],
    filename: str | None,
) -> str:
    previous_lifter = legacy._FunctionLifter
    legacy._FunctionLifter = _CompatibilityQualityFunctionLifter  # type: ignore[misc]
    try:
        return quality._clean_output(legacy.decompile_module(module, options, filename))
    finally:
        legacy._FunctionLifter = previous_lifter  # type: ignore[misc]


disassemble_module = legacy.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
