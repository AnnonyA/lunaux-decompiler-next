from __future__ import annotations

from collections import defaultdict
from typing import cast

from lunaux.backends import lifter as legacy
from lunaux.backends.compat_quality_safe import _SafeCompatibilityQualityFunctionLifter
from lunaux.backends.scopes import Binding
from lunaux.backends.ssa import SSAValue

_INSTALLED = False


def _binding_started_by_definition(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    register: int,
    pc: int,
) -> Binding | None:
    """Return a debug binding that becomes live immediately after its definition.

    Luau debug locals commonly start at the instruction *after* the value-producing
    opcode. Looking only at the definition PC therefore gives the temporary a generated
    name while every later use resolves to the real source local. That split is not
    cosmetic: updates can become a new inner local and final reads can reference an
    identifier that was never initialized.
    """

    if not lifter.proto.locals:
        return None
    instruction = lifter.instruction_by_pc.get(pc)
    end_pc = pc + (instruction.size if instruction is not None else 1)
    candidates = [
        binding
        for scope in lifter.scope_tree.scopes.values()
        for binding in scope.bindings
        if binding.register == register and pc < binding.start_pc <= end_pc
    ]
    return min(
        candidates,
        key=lambda binding: (binding.start_pc, binding.end_pc, binding.name),
        default=None,
    )


def _debug_binding_name(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    register: int,
    pc: int,
    *,
    include_next_definition_boundary: bool,
) -> str | None:
    """Return the serialized lexical name active at a program point."""

    binding = lifter.scope_tree.binding_for_register(register, pc)
    if binding is None and include_next_definition_boundary:
        binding = _binding_started_by_definition(lifter, register, pc)
    if binding is None:
        return None
    return legacy._sanitize_identifier(binding.name, f"v{register}")


def _debug_value_names(
    lifter: _SafeCompatibilityQualityFunctionLifter,
) -> dict[SSAValue, str]:
    """Bind SSA values to debug-local identity using their actual in-scope uses.

    Debug ranges begin after initialization for many Luau constructs (tables,
    closures, optimized calls, and parameters after PREPVARARGS).  Emission can also
    be delayed past the defining opcode while a table literal is reconstructed.  A
    PC-only lookup therefore names the definition and its later uses differently.

    Instead, collect the lexical binding seen by every SSA use/definition.  If a value
    is observed under one unambiguous debug name, that name belongs to the value even
    when the source binding starts after its machine-level definition.  Conflicting
    observations are deliberately left alone rather than coalescing unrelated register
    lifetimes.
    """

    cached = getattr(lifter, "_full_corpus_debug_value_names", None)
    if cached is not None:
        return cast(dict[SSAValue, str], cached)

    candidates: defaultdict[SSAValue, set[str]] = defaultdict(set)
    if lifter.proto.locals:
        for ssa_instruction in lifter.ssa.instructions.values():
            pc = ssa_instruction.pc
            for use in ssa_instruction.uses:
                name = _debug_binding_name(
                    lifter,
                    use.register,
                    pc,
                    include_next_definition_boundary=False,
                )
                if name is not None:
                    candidates[use.value].add(name)
            for value in ssa_instruction.definitions:
                name = _debug_binding_name(
                    lifter,
                    value.register,
                    pc,
                    include_next_definition_boundary=False,
                )
                if name is not None:
                    candidates[value].add(name)

    result = {
        value: next(iter(names))
        for value, names in candidates.items()
        if len(names) == 1
    }
    lifter._full_corpus_debug_value_names = result
    return result


def _debug_parameter_names(
    lifter: _SafeCompatibilityQualityFunctionLifter,
) -> dict[int, str]:
    """Recover parameter names from the SSA entry value's debug binding."""

    value_names = _debug_value_names(lifter)
    result: dict[int, str] = {}
    for register in range(lifter.proto.num_params):
        value = lifter.ssa.entry_values.get(register)
        if value is None:
            continue
        name = value_names.get(value)
        if name is not None:
            result[register] = name
    return result


def install_full_corpus_semantics_fix() -> None:
    """Install semantics fixes orthogonal to the proven v6/g0 Medal gate."""

    global _INSTALLED
    if _INSTALLED:
        return

    lifter_type = _SafeCompatibilityQualityFunctionLifter
    original_name = lifter_type._name
    original_definition_name = lifter_type._definition_name
    original_lift = lifter_type.lift

    def _name(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> str:
        value = self.ssa.value_at_use(pc, register)
        if value is not None:
            debug_name = _debug_value_names(self).get(value)
            if debug_name is not None:
                self._forced_value_names()[value] = debug_name
                self.register_names[register] = debug_name
                return debug_name

        debug_name = _debug_binding_name(
            self,
            register,
            pc,
            include_next_definition_boundary=False,
        )
        if debug_name is not None:
            self.register_names[register] = debug_name
            return debug_name

        if (
            register < self.proto.num_params
            and value is not None
            and value.kind == "entry"
        ):
            existing = self.register_names.get(register)
            if existing is not None:
                return existing
        return original_name(self, register, pc)

    def _definition_name(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> str:
        value = self.ssa.value_defined_at(pc, register)
        debug_value = value
        if debug_value is None:
            # Delayed synthetic emission (notably reconstructed table literals) uses
            # the final write PC instead of the original defining PC.  At that point
            # the table value is a use, not a definition, so recover its SSA identity.
            debug_value = self.ssa.value_at_use(pc, register)

        if debug_value is not None:
            debug_name = _debug_value_names(self).get(debug_value)
            if debug_name is not None:
                self._forced_value_names()[debug_value] = debug_name
                self.register_names[register] = debug_name
                return debug_name

        if value is not None and value in self._captured_reference_names():
            return original_definition_name(self, register, pc)

        debug_name = _debug_binding_name(
            self,
            register,
            pc,
            include_next_definition_boundary=True,
        )
        if debug_name is not None:
            if value is not None:
                self._forced_value_names()[value] = debug_name
            self.register_names[register] = debug_name
            return debug_name
        return original_definition_name(self, register, pc)

    def _lift(
        self: _SafeCompatibilityQualityFunctionLifter,
        *,
        as_function: bool,
        function_name_override: str | None = None,
        local_function: bool = True,
        anonymous_function: bool = False,
    ) -> None:
        # Function headers are emitted before _name() is consulted.  Feed the debug
        # name attached to each SSA entry value into the existing parameter override
        # path so declarations and later reads cannot diverge (arg1 vs source name).
        debug_parameters = _debug_parameter_names(self)
        previous = dict(self.parameter_name_overrides)
        self.parameter_name_overrides.update(debug_parameters)
        try:
            original_lift(
                self,
                as_function=as_function,
                function_name_override=function_name_override,
                local_function=local_function,
                anonymous_function=anonymous_function,
            )
        finally:
            self.parameter_name_overrides.clear()
            self.parameter_name_overrides.update(previous)

    # The compatibility class is intentionally patched once because its decompile
    # wrapper is already installed dynamically by the safe backend.  setattr avoids
    # narrowing the receiver type in mypy's method-assignment check.
    setattr(lifter_type, "_name", _name)  # noqa: B010
    setattr(lifter_type, "_definition_name", _definition_name)  # noqa: B010
    setattr(lifter_type, "lift", _lift)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_full_corpus_semantics_fix"]
