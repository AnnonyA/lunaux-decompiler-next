from __future__ import annotations

from lunaux.backends import lifter as legacy
from lunaux.backends.compat_quality_safe import _SafeCompatibilityQualityFunctionLifter
from lunaux.backends.scopes import Binding

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
    """Prefer serialized lexical identity over inferred/phi-friendly names.

    Debug bindings are stronger evidence than symbol heuristics.  In particular the
    quality layer can otherwise rename a real local such as ``seed`` to a friendly
    inferred name at use sites even though its definition was emitted as ``seed``.
    """

    binding = lifter.scope_tree.binding_for_register(register, pc)
    if binding is None and include_next_definition_boundary:
        binding = _binding_started_by_definition(lifter, register, pc)
    if binding is None:
        return None
    return legacy._sanitize_identifier(binding.name, f"v{register}")


def install_full_corpus_semantics_fix() -> None:
    """Install semantics fixes orthogonal to the proven v6/g0 Medal gate."""

    global _INSTALLED
    if _INSTALLED:
        return

    lifter_type = _SafeCompatibilityQualityFunctionLifter
    original_name = lifter_type._name
    original_definition_name = lifter_type._definition_name

    def _name(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> str:
        debug_name = _debug_binding_name(
            self,
            register,
            pc,
            include_next_definition_boundary=False,
        )
        if debug_name is not None:
            self.register_names[register] = debug_name
            return debug_name

        value = self.ssa.value_at_use(pc, register)
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

    # The compatibility class is intentionally patched once because its decompile
    # wrapper is already installed dynamically by the safe backend.  setattr avoids
    # narrowing the receiver type in mypy's method-assignment check.
    setattr(lifter_type, "_name", _name)  # noqa: B010
    setattr(lifter_type, "_definition_name", _definition_name)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_full_corpus_semantics_fix"]
