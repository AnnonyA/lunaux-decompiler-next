from __future__ import annotations

import re
from collections import defaultdict
from typing import cast

import lunaux.backends.quality_lifter as quality
from lunaux.backends import lifter as legacy
from lunaux.backends.ast import Expr, NameExpr
from lunaux.backends.compat_quality_safe import _SafeCompatibilityQualityFunctionLifter
from lunaux.backends.opcodes import DecodedInstruction
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
    """Bind SSA values and their phi components to unambiguous debug identities.

    A source local can start after the instruction that initializes it, and boolean or
    loop lowering can place that value behind one or more phi nodes.  Direct PC lookups
    then name the definition and the later use differently.  Collect lexical evidence
    from actual uses/definitions and propagate a name only when an entire phi component
    contains one unambiguous debug identity.
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
                    include_next_definition_boundary=True,
                )
                if name is not None:
                    candidates[value].add(name)

    result = {value: next(iter(names)) for value, names in candidates.items() if len(names) == 1}

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
            parent[right_root] = left_root

    for phi in lifter.ssa.phis:
        find(phi.result)
        for operand in phi.operands.values():
            union(phi.result, operand)

    components: defaultdict[SSAValue, list[SSAValue]] = defaultdict(list)
    for value in tuple(parent):
        components[find(value)].append(value)
    for members in components.values():
        names = {name for member in members for name in candidates.get(member, ())}
        if len(names) != 1:
            continue
        name = next(iter(names))
        for member in members:
            result[member] = name

    setattr(lifter, "_full_corpus_debug_value_names", result)  # noqa: B010
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


def _replace_identifier_reference(line: str, name: str, replacement: str) -> str:
    """Replace a variable reference without touching fields, strings, or comments."""

    output: list[str] = []
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(line):
        char = line[index]
        if quote is not None:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            output.append(char)
            index += 1
            continue
        if char == "-" and index + 1 < len(line) and line[index + 1] == "-":
            output.append(line[index:])
            break
        if line.startswith(name, index):
            before = line[index - 1] if index else ""
            after_index = index + len(name)
            after = line[after_index] if after_index < len(line) else ""
            before_identifier = bool(before and (before.isalnum() or before == "_"))
            after_identifier = bool(after and (after.isalnum() or after == "_"))
            if not before_identifier and not after_identifier and before not in {".", ":"}:
                output.append(replacement)
                index = after_index
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _safe_inline_simple_aliases(lines: list[str]) -> list[str]:
    """Inline field aliases without rewriting property-name tokens.

    The previous word-level substitution could turn ``record.Stats.Score`` into
    ``record.Stats.Stats.Score`` when a local alias happened to be named ``Stats``.
    That is a semantic change, not a readability issue.  Replace only lexical variable
    references and leave ``.field``/``:method`` selectors and quoted strings intact.
    """

    result = list(lines)
    aliases: list[tuple[int, str, str]] = []

    def scope_end(index: int, indent: str) -> int:
        if not indent:
            return len(result)
        for following in range(index + 1, len(result)):
            candidate = result[following]
            if not candidate.strip():
                continue
            candidate_indent = candidate[: len(candidate) - len(candidate.lstrip())]
            if len(candidate_indent) < len(indent):
                return following
        return len(result)

    for index, line in enumerate(result):
        match = quality._SIMPLE_ALIAS.fullmatch(line)
        if match is None:
            continue
        lhs = match.group("lhs")
        rhs = match.group("rhs")
        if "." not in rhs and lhs != rhs:
            continue
        end = scope_end(index, match.group("indent"))
        assigned_later = any(
            re.match(rf"^\s*{re.escape(lhs)}\s*=", candidate)
            for candidate in result[index + 1 : end]
        )
        if assigned_later:
            continue
        aliases.append((index, lhs, rhs))

    removed: set[int] = set()
    for index, lhs, rhs in aliases:
        removed.add(index)
        # Earlier aliases may already have rewritten this declaration.  Use its
        # current RHS so a chain such as ``leaf = branch.leaf`` expands through
        # ``branch = root.branch`` instead of reintroducing the removed ``branch``.
        current = quality._SIMPLE_ALIAS.fullmatch(result[index])
        if current is not None:
            rhs = current.group("rhs")
        if lhs == rhs:
            continue
        indent_match = quality._SIMPLE_ALIAS.fullmatch(result[index])
        indent = indent_match.group("indent") if indent_match is not None else ""
        for following in range(index + 1, scope_end(index, indent)):
            if following in removed:
                continue
            result[following] = _replace_identifier_reference(
                result[following],
                lhs,
                rhs,
            )
    return [line for index, line in enumerate(result) if index not in removed]


def _numeric_for_visible_register(
    lifter: _SafeCompatibilityQualityFunctionLifter,
    instruction: DecodedInstruction,
    end_pc: int,
) -> tuple[int, int]:
    """Choose the numeric-for register that is actually visible to the loop body.

    Luau reserves ``A+2`` for the internal index and ``A+3`` for the nominal source
    variable.  The compiler can however read the immutable internal index directly and
    immediately reuse ``A+3`` for an unrelated body local.  In that shape, blindly
    forcing ``A+3`` to the loop-variable name aliases the unrelated local and leaves
    body reads attached to the pre-loop initializer.

    Prefer the nominal source register whenever its incoming value is read.  Otherwise,
    if the internal index is read before any body definition while ``A+3`` is overwritten
    first, the internal index is the source-visible value for this lowered loop.
    """

    internal = instruction.a + 2
    nominal = instruction.a + 3
    first_use: dict[int, int] = {}
    first_definition: dict[int, int] = {}

    for candidate in lifter.instructions:
        if not (instruction.pc < candidate.pc < end_pc):
            continue
        if candidate.name == "FORNLOOP":
            continue
        access = lifter.analysis.register_accesses[candidate.pc]
        for register in (internal, nominal):
            if register in access.uses:
                first_use.setdefault(register, candidate.pc)
            if register in access.definitions:
                first_definition.setdefault(register, candidate.pc)

    def incoming_value_is_used(register: int) -> bool:
        use_pc = first_use.get(register)
        if use_pc is None:
            return False
        definition_pc = first_definition.get(register)
        return definition_pc is None or use_pc <= definition_pc

    nominal_live = incoming_value_is_used(nominal)
    internal_live = incoming_value_is_used(internal)
    if nominal_live:
        return nominal, first_use[nominal]
    if internal_live:
        return internal, first_use[internal]
    return nominal, instruction.pc


def install_full_corpus_semantics_fix() -> None:
    """Install semantics fixes orthogonal to the proven v6/g0 Medal gate."""

    global _INSTALLED
    if _INSTALLED:
        return

    lifter_type = _SafeCompatibilityQualityFunctionLifter
    original_name = lifter_type._name
    original_definition_name = lifter_type._definition_name
    original_ref_expr = lifter_type._ref_expr
    original_open_structured_loop = lifter_type._open_structured_loop
    original_handle_loop_prep = lifter_type._handle_loop_prep
    original_lift = lifter_type.lift

    def _name(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> str:
        # Numeric/generic loop variables are explicit source bindings.  Their forced
        # structural identity must outrank debug/phi heuristics, especially when the
        # compiler reuses the loop-variable register as a temporary later in a body.
        if self._structural_name(register, pc) is not None:
            return original_name(self, register, pc)

        value = self.ssa.value_at_use(pc, register)
        if value is not None and value in self._captured_reference_names():
            return original_name(self, register, pc)
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

        if register < self.proto.num_params and value is not None and value.kind == "entry":
            existing = self.register_names.get(register)
            if existing is not None:
                return existing
        return original_name(self, register, pc)

    def _definition_name(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> str:
        if self._structural_name(register, pc) is not None:
            return original_definition_name(self, register, pc)

        value = self.ssa.value_defined_at(pc, register)
        if value is not None and value in self._captured_reference_names():
            return original_definition_name(self, register, pc)

        debug_value = value
        if debug_value is None:
            # Delayed synthetic emission (notably reconstructed table literals) uses
            # the final write PC instead of the original defining PC.  At that point
            # the table value is a use, not a definition, so recover its SSA identity.
            debug_value = self.ssa.value_at_use(pc, register)

        if debug_value is not None and debug_value not in self._captured_reference_names():
            debug_name = _debug_value_names(self).get(debug_value)
            if debug_name is not None:
                self._forced_value_names()[debug_value] = debug_name
                self.register_names[register] = debug_name
                return debug_name

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

    def _ref_expr(
        self: _SafeCompatibilityQualityFunctionLifter,
        register: int,
        pc: int,
    ) -> Expr:
        structural = self._structural_name(register, pc)
        if structural is not None:
            self.register_names[register] = structural
            return NameExpr(structural)
        return original_ref_expr(self, register, pc)

    def _open_structured_loop(
        self: _SafeCompatibilityQualityFunctionLifter,
        instruction: DecodedInstruction,
    ) -> bool:
        opened = original_open_structured_loop(self, instruction)
        if not opened:
            return False
        # Opening a repeat/infinite/advanced while region can happen at an ordinary
        # value-producing first body instruction.  Returning True makes lift() skip
        # that instruction entirely (for example LOADN 3 at the head of a repeat),
        # leaving an undefined register in the reconstructed source.  Only a real
        # conditional header is consumed by the structured loop syntax itself.
        return instruction.name in legacy._CONDITIONAL_OPS

    def _handle_loop_prep(
        self: _SafeCompatibilityQualityFunctionLifter,
        instruction: DecodedInstruction,
    ) -> bool:
        if instruction.name != "FORNPREP":
            return original_handle_loop_prep(self, instruction)

        target = legacy._jump_target(instruction)
        # Capture the initializer expressions before forcing the body-visible register;
        # A+2 can itself be the optimized visible loop value, and forcing it first would
        # turn a correct initializer into ``for index = index, ...`` accidentally.
        start = self._ref(instruction.a + 2, instruction.pc)
        limit = self._ref(instruction.a, instruction.pc)
        step = self._ref(instruction.a + 1, instruction.pc)

        register, use_pc = _numeric_for_visible_register(self, instruction, target)
        proposed = self._friendly_name(self._name(register, use_pc))
        variable = "index" if proposed.startswith("value") else proposed
        self._force_register_name(register, instruction.pc, target, variable)
        self.register_names[register] = variable
        self.declared.add(variable)

        header = f"for {variable} = {start}, {limit}"
        if self.options.preserve_for_step or step not in ("1", "1.0"):
            header += f", {step}"
        return self._open_until(target, header + " do")

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
    setattr(lifter_type, "_ref_expr", _ref_expr)  # noqa: B010
    setattr(lifter_type, "_open_structured_loop", _open_structured_loop)  # noqa: B010
    setattr(lifter_type, "_handle_loop_prep", _handle_loop_prep)  # noqa: B010
    setattr(lifter_type, "lift", _lift)  # noqa: B010
    setattr(quality, "_inline_simple_aliases", _safe_inline_simple_aliases)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_full_corpus_semantics_fix"]
