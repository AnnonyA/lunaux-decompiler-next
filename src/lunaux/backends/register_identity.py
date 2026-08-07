from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import lunaux.backends.lifter as legacy


def install_register_identity_stability() -> None:
    """Keep a declared source name stable across SSA redefinitions of one register.

    Luau reuses a physical register for mutable loop-carried values. SSA correctly
    creates a fresh value for each definition, but source emission must not turn each
    version into a new lexical local. Debug scope bindings still take priority; this
    fallback only applies when no lexical binding exists and the register already maps
    to a declared source variable.
    """

    lifter_type = legacy._FunctionLifter
    if getattr(lifter_type, "_lunaux_register_identity_stable", False):
        return

    original_name = lifter_type._name
    original_definition_name = lifter_type._definition_name

    def stable_existing(self: Any, register: int, pc: int) -> str | None:
        if self.scope_tree.binding_for_register(register, pc) is not None:
            return None
        existing = self.register_names.get(register)
        if existing is not None and existing in self.declared:
            return cast(str, existing)
        return None

    def stable_name(self: Any, register: int, pc: int) -> str:
        existing = stable_existing(self, register, pc)
        if existing is not None:
            return existing
        method = cast(Callable[[Any, int, int], str], original_name)
        return method(self, register, pc)

    def stable_definition_name(self: Any, register: int, pc: int) -> str:
        existing = stable_existing(self, register, pc)
        if existing is not None:
            return existing
        method = cast(Callable[[Any, int, int], str], original_definition_name)
        return method(self, register, pc)

    lifter_type._name = stable_name  # type: ignore[method-assign]
    lifter_type._definition_name = stable_definition_name  # type: ignore[method-assign]
    lifter_type._lunaux_register_identity_stable = True
