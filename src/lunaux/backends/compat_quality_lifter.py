from __future__ import annotations

from dataclasses import replace
from typing import cast

import lunaux.backends.lifter as legacy
import lunaux.backends.quality_lifter as quality
from lunaux.backends.bytecode import LuauBytecodeModule


class _CompatibilityQualityFunctionLifter(quality._QualityFunctionLifter):
    """Conservative source emission for legacy Luau bytecode used by the 0.18 gate.

    The modern quality pass is tuned around newer bytecode and aggressively folds
    temporaries/tables. On v3-v6 that can lose the identity of entry parameters or
    materialize an SSA temporary after its definition was intentionally suppressed.
    This subclass keeps the modern path unchanged while preferring explicit,
    semantics-first source for the legacy compatibility window.
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
        return super()._name(register, pc)

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
                reconstruct_table_literals=False,
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
