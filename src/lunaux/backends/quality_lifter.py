from __future__ import annotations

import re
from collections import defaultdict
from typing import cast

import lunaux.backends.lifter as legacy
from lunaux.backends.ast import Expr, LiteralExpr, UnaryExpr, render_expression
from lunaux.backends.multret_lifter import _MultiRetFunctionLifter
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAMultiUse, SSAMultiValue, SSAValue

_GENERATED_NAME = re.compile(
    r"^(?P<prefix>r|reg|v|var|temp|tmp|local|arg|num|bool|str|tbl|table|"
    r"func|function|upvalue|upval)_?(?P<number>\d+)$",
    re.IGNORECASE,
)
_FRIENDLY_STEMS = {
    "r": "value",
    "reg": "value",
    "v": "value",
    "var": "item",
    "temp": "value",
    "tmp": "value",
    "local": "value",
    "arg": "value",
    "num": "value",
    "bool": "flag",
    "str": "text",
    "tbl": "data",
    "table": "data",
    "func": "callback",
    "function": "callback",
    "upvalue": "captured",
    "upval": "captured",
}
_SIMPLE_ALIAS = re.compile(
    r"^(?P<indent>\s*)local\s+(?P<lhs>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<rhs>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*$"
)
_TOP_LEVEL_RETURN = re.compile(r"^return(?:\s|$)")
_FLOAT_INTEGER = re.compile(r"(?<![A-Za-z0-9_])(-?\d+)\.0(?![A-Za-z0-9_])")
_NOT_COMPARISON = re.compile(
    r"not \((?P<left>[^()\n]+?)\s*(?P<op>==|~=|<=|>=|<|>)\s*(?P<right>[^()\n]+?)\)"
)
_INVERTED_COMPARISONS = {
    "==": "~=",
    "~=": "==",
    "<=": ">",
    ">=": "<",
    "<": ">=",
    ">": "<=",
}


class _QualityFunctionLifter(_MultiRetFunctionLifter):
    """Final SSA-destruction and source-quality pass used by the portable backend."""

    def _friendly_name_cache(self) -> dict[str, str]:
        cache = getattr(self, "_quality_friendly_names", None)
        if cache is None:
            cache = {}
            self._quality_friendly_names = cache
        return cast(dict[str, str], cache)

    def _friendly_name(self, name: str) -> str:
        match = _GENERATED_NAME.fullmatch(name)
        if match is None:
            return name
        cache = self._friendly_name_cache()
        cached = cache.get(name)
        if cached is not None:
            return cached
        prefix = match.group("prefix").lower()
        ordinal = int(match.group("number"))
        stem = _FRIENDLY_STEMS.get(prefix, "value")
        candidate = stem if ordinal <= 1 else f"{stem}{ordinal}"
        occupied = set(cache.values()) | set(self.declared)
        if candidate in occupied and cache.get(name) != candidate:
            suffix = max(2, ordinal)
            while f"{stem}{suffix}" in occupied:
                suffix += 1
            candidate = f"{stem}{suffix}"
        cache[name] = candidate
        return candidate

    def _structural_register_names(self) -> list[tuple[int, int, int, str]]:
        values = getattr(self, "_quality_structural_register_names", None)
        if values is None:
            values = []
            self._quality_structural_register_names = values
        return cast(list[tuple[int, int, int, str]], values)

    def _force_register_name(
        self,
        register: int,
        start_pc: int,
        end_pc: int,
        name: str,
    ) -> None:
        self._structural_register_names().append((register, start_pc, end_pc, name))

    def _structural_name(self, register: int, pc: int) -> str | None:
        for forced_register, start_pc, end_pc, name in reversed(
            self._structural_register_names()
        ):
            if forced_register == register and start_pc <= pc <= end_pc:
                return name
        return None

    def _loop_carried_register(self, register: int, pc: int) -> bool:
        block = self.analysis.block_for_pc.get(pc)
        if block is None:
            return False
        for loop in self.analysis.loops:
            if block not in loop.body:
                continue
            if register not in self.analysis.live_in.get(loop.header, frozenset()):
                continue
            if any(
                phi.block == loop.header and phi.register == register
                for phi in self.ssa.phis
            ):
                return True
            if register in self.analysis.live_out.get(loop.latch, frozenset()):
                return True
        return False

    def _all_phi_names(self) -> dict[SSAValue, str]:
        cached = getattr(self, "_quality_all_phi_names", None)
        if cached is not None:
            return cast(dict[SSAValue, str], cached)

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

        for phi in self.ssa.phis:
            find(phi.result)
            for operand in phi.operands.values():
                union(phi.result, operand)

        groups: defaultdict[SSAValue, list[SSAValue]] = defaultdict(list)
        for value in tuple(parent):
            groups[find(value)].append(value)

        loop_names = super()._loop_carried_names()
        result: dict[SSAValue, str] = {}
        used: set[str] = set()
        for values in groups.values():
            existing = next(
                (loop_names[value] for value in values if value in loop_names),
                None,
            )
            if existing is not None:
                name = self._friendly_name(existing)
            else:
                ordered = sorted(
                    values,
                    key=lambda value: (
                        value.origin_pc is None,
                        value.origin_pc if value.origin_pc is not None else 1 << 30,
                        value.version,
                    ),
                )
                name = None
                if self.symbols is not None:
                    for value in ordered:
                        symbol = self.symbols.symbol_for(value)
                        if symbol is not None:
                            name = self._friendly_name(symbol.name)
                            break
                if name is None:
                    register = ordered[0].register
                    name = self._friendly_name(
                        self.register_names.get(register, f"value{register + 1}")
                    )
            base = name
            suffix = 2
            while name in used:
                name = f"{base}{suffix}"
                suffix += 1
            used.add(name)
            for value in values:
                result[value] = name

        self._quality_all_phi_names = result
        return result

    def _name(self, register: int, pc: int) -> str:
        structural = self._structural_name(register, pc)
        if structural is not None:
            self.register_names[register] = structural
            return structural
        value = self.ssa.value_at_use(pc, register)
        if value is not None:
            phi_name = self._all_phi_names().get(value)
            if phi_name is not None:
                self.register_names[register] = phi_name
                return phi_name
        return self._friendly_name(super()._name(register, pc))

    def _definition_name(self, register: int, pc: int) -> str:
        structural = self._structural_name(register, pc)
        if structural is not None:
            self.register_names[register] = structural
            return structural
        value = self.ssa.value_defined_at(pc, register)
        if value is not None:
            phi_name = self._all_phi_names().get(value)
            if phi_name is not None:
                self.register_names[register] = phi_name
                return phi_name
        existing = self.register_names.get(register)
        if (
            existing is not None
            and existing in self.declared
            and self._loop_carried_register(register, pc)
        ):
            return existing
        return self._friendly_name(super()._definition_name(register, pc))

    def _annotated_name(self, register: int, name: str, pc: int) -> str:
        serialized_type = legacy._local_type(self.module, self.proto, register, pc)
        if serialized_type and serialized_type != "any":
            return f"{name}: {serialized_type}"
        return name

    def _resolve_phi_expression(
        self,
        value: SSAValue,
        seen: frozenset[SSAValue] = frozenset(),
    ) -> Expr | None:
        if value in seen:
            return None
        direct = self.inline_expressions.get(value)
        if direct is not None:
            return direct
        if value.kind != "phi":
            return None
        phi = next((item for item in self.ssa.phis if item.result == value), None)
        if phi is None or not phi.operands:
            return None
        rendered: str | None = None
        selected: Expr | None = None
        for operand in phi.operands.values():
            expression = self.inline_expressions.get(operand)
            if expression is None and operand.kind == "phi":
                expression = self._resolve_phi_expression(
                    operand,
                    seen | frozenset({value}),
                )
            if expression is None:
                return None
            current = render_expression(expression)
            if rendered is None:
                rendered = current
                selected = expression
            elif current != rendered:
                return None
        return selected

    def _ref_expr(self, register: int, pc: int) -> Expr:
        value = self.ssa.value_at_use(pc, register)
        if value is not None:
            expression = self._resolve_phi_expression(value)
            if expression is not None:
                return expression
        return super()._ref_expr(register, pc)

    def _persistent_multret_plan(
        self,
    ) -> tuple[dict[int, SSAMultiValue], dict[int, SSAMultiUse]]:
        cached = getattr(self, "_quality_persistent_multret_plan", None)
        if cached is not None:
            return cast(
                tuple[dict[int, SSAMultiValue], dict[int, SSAMultiUse]],
                cached,
            )

        values: dict[int, SSAMultiValue] = {}
        uses: dict[int, SSAMultiUse] = {}
        pending: SSAMultiValue | None = None
        reachable = self.analysis.reachable
        for instruction in self.instructions:
            block = self.analysis.block_for_pc.get(instruction.pc)
            if block is None or block not in reachable:
                continue

            consumer: tuple[str, int] | None = None
            if instruction.name in {"CALL", "CALLFB"} and instruction.b == 0:
                consumer = ("arguments", instruction.a + 1)
            elif instruction.name == "RETURN" and instruction.b == 0:
                consumer = ("return", instruction.a)
            elif instruction.name == "SETLIST" and instruction.c == 0:
                consumer = ("setlist", instruction.b)

            consumed = False
            if consumer is not None and pending is not None:
                kind, base_register = consumer
                if pending.base_register >= base_register:
                    uses[instruction.pc] = SSAMultiUse(
                        consumer_pc=instruction.pc,
                        base_register=base_register,
                        kind=kind,  # type: ignore[arg-type]
                        value=pending,
                        prefix_registers=tuple(
                            range(base_register, pending.base_register)
                        ),
                    )
                    consumed = True

            producer: SSAMultiValue | None = None
            if instruction.name in {"CALL", "CALLFB"} and instruction.c == 0:
                producer = SSAMultiValue(instruction.pc, instruction.a, "call")
            elif instruction.name == "GETVARARGS" and instruction.b == 0:
                producer = SSAMultiValue(instruction.pc, instruction.a, "varargs")

            if producer is not None:
                values[instruction.pc] = producer
                pending = producer
            elif consumed:
                pending = None
            elif pending is not None:
                access = self.analysis.register_accesses[instruction.pc]
                if any(
                    register >= pending.base_register
                    for register in access.definitions
                ):
                    pending = None

        plan = (values, uses)
        self._quality_persistent_multret_plan = plan
        return plan

    def _generic_iterator_expressions(self) -> dict[int, Expr]:
        values = getattr(self, "_quality_generic_iterator_expressions", None)
        if values is None:
            values = {}
            self._quality_generic_iterator_expressions = values
        return cast(dict[int, Expr], values)

    def _feeds_generic_for(self, instruction: DecodedInstruction) -> bool:
        if instruction.name not in {"CALL", "CALLFB"} or instruction.c != 4:
            return False
        index = self.instruction_index_by_pc[instruction.pc]
        for candidate in self.instructions[index + 1 : index + 5]:
            if candidate.name in {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}:
                return candidate.a == instruction.a
            access = self.analysis.register_accesses[candidate.pc]
            if instruction.a in access.definitions:
                return False
        return False

    def _boolean_load_plan(
        self,
    ) -> tuple[dict[int, tuple[int, int, int]], frozenset[int]]:
        cached = getattr(self, "_quality_boolean_load_plan", None)
        if cached is not None:
            return cast(
                tuple[dict[int, tuple[int, int, int]], frozenset[int]],
                cached,
            )
        plan: dict[int, tuple[int, int, int]] = {}
        skipped: set[int] = set()
        instructions = self.instructions
        for index, condition in enumerate(instructions[:-2]):
            if condition.name not in legacy._CONDITIONAL_OPS:
                continue
            first = instructions[index + 1]
            second = instructions[index + 2]
            if (
                first.name == "LOADB"
                and first.c
                and second.name == "LOADB"
                and first.a == second.a
            ):
                target = legacy._jump_target(first)
                if target not in {second.pc, second.pc + second.size}:
                    continue
                plan[condition.pc] = (first.a, first.b, second.b)
                skipped.update({first.pc, second.pc})
        result = (plan, frozenset(skipped))
        self._quality_boolean_load_plan = result
        return result

    def _emit_boolean_pair(self, instruction: DecodedInstruction) -> bool:
        entry = self._boolean_load_plan()[0].get(instruction.pc)
        if entry is None:
            return False
        register, fallthrough_value, taken_value = entry
        condition = self._conditional_expr(instruction)
        if condition is None:
            return False
        if fallthrough_value == taken_value:
            expression: Expr = LiteralExpr(
                "true" if fallthrough_value else "false"
            )
        elif fallthrough_value and not taken_value:
            expression = condition
        else:
            expression = UnaryExpr("not", condition)
        first_pc = self.instructions[
            self.instruction_index_by_pc[instruction.pc] + 1
        ].pc
        name = self._definition_name(register, first_pc)
        if name not in self.declared:
            self.out.line(
                f"local {name} = {render_expression(expression)}",
                statement=True,
            )
            self.declared.add(name)
        else:
            self.out.line(
                f"{name} = {render_expression(expression)}",
                statement=True,
            )
        self.register_names[register] = name
        return True

    def _branch_phi_declarations(self, instruction: DecodedInstruction) -> None:
        if instruction.name not in legacy._CONDITIONAL_OPS:
            return
        block_start = self.analysis.block_for_pc.get(instruction.pc)
        if block_start is None:
            return
        branch = next(
            (item for item in self.analysis.branches if item.header == block_start),
            None,
        )
        if branch is None or branch.join is None:
            return
        names: list[str] = []
        for phi in self.ssa.phis:
            if phi.block != branch.join:
                continue
            name = self._all_phi_names().get(phi.result)
            if name is None or name in self.declared:
                continue
            dominating_operand = False
            for operand in phi.operands.values():
                if operand.origin_pc is None:
                    dominating_operand = True
                    break
                origin_block = self.analysis.block_for_pc.get(operand.origin_pc)
                if (
                    origin_block is not None
                    and self.analysis.dominates(origin_block, branch.header)
                ):
                    dominating_operand = True
                    break
            if not dominating_operand:
                names.append(name)
        for name in dict.fromkeys(names):
            self.out.line(f"local {name}", statement=True)
            self.declared.add(name)

    def _handle_loop_prep(self, instruction: DecodedInstruction) -> bool:
        if instruction.name == "FORNPREP":
            target = legacy._jump_target(instruction)
            register = instruction.a + 3
            proposed = self._friendly_name(
                super()._definition_name(register, instruction.pc)
            )
            variable = "index" if proposed.startswith("value") else proposed
            self._force_register_name(register, instruction.pc, target, variable)
            self.register_names[register] = variable
            self.declared.add(variable)
            start = self._ref(instruction.a + 2, instruction.pc)
            limit = self._ref(instruction.a, instruction.pc)
            step = self._ref(instruction.a + 1, instruction.pc)
            header = f"for {variable} = {start}, {limit}"
            if self.options.preserve_for_step or step not in ("1", "1.0"):
                header += f", {step}"
            return self._open_until(target, header + " do")

        if instruction.name in {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}:
            loop_pc = legacy._jump_target(instruction)
            loop_instruction = self.instruction_by_pc.get(loop_pc)
            variable_count = 2
            close_pc = loop_pc + 1
            if loop_instruction is not None and loop_instruction.name == "FORGLOOP":
                variable_count = max(1, (loop_instruction.aux or 1) & 0xFF)
                close_pc = loop_pc + loop_instruction.size
            variables: list[str] = []
            preferred = ("index", "value", "item")
            for offset in range(variable_count):
                register = instruction.a + 3 + offset
                base = (
                    preferred[offset]
                    if offset < len(preferred)
                    else f"item{offset + 1}"
                )
                variable = base
                suffix = 2
                while (
                    variable in self.declared
                    and self.register_names.get(register) != variable
                ):
                    variable = f"{base}{suffix}"
                    suffix += 1
                variables.append(variable)
                self._force_register_name(
                    register,
                    instruction.pc,
                    close_pc,
                    variable,
                )
                self.register_names[register] = variable
                self.declared.add(variable)

            iterator_expression = self._generic_iterator_expressions().pop(
                instruction.a,
                None,
            )
            if iterator_expression is not None:
                iterator_text = render_expression(iterator_expression)
            else:
                iterator = self._ref(instruction.a, instruction.pc)
                state = self._ref(instruction.a + 1, instruction.pc)
                control = self._ref(instruction.a + 2, instruction.pc)
                iterator_text = f"{iterator}, {state}, {control}"
            return self._open_until(
                close_pc,
                f"for {', '.join(variables)} in {iterator_text} do",
            )
        return False

    def _lift_instruction(self, instruction: DecodedInstruction) -> None:
        if instruction.pc in self._boolean_load_plan()[1]:
            return
        if self._emit_boolean_pair(instruction):
            return
        if self._feeds_generic_for(instruction):
            self._generic_iterator_expressions()[instruction.a] = (
                self._call_expression(instruction)
            )
            return
        if instruction.name in legacy._CONDITIONAL_OPS:
            self._branch_phi_declarations(instruction)
        super()._lift_instruction(instruction)


legacy._FunctionLifter = _QualityFunctionLifter  # type: ignore[misc]


def _simplify_not_comparisons(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return (
            f"{match.group('left').strip()} "
            f"{_INVERTED_COMPARISONS[match.group('op')]} "
            f"{match.group('right').strip()}"
        )

    previous = None
    while text != previous:
        previous = text
        text = _NOT_COMPARISON.sub(replace, text)
    return text


def _inline_simple_aliases(lines: list[str]) -> list[str]:
    result = list(lines)
    aliases: list[tuple[int, str, str]] = []
    for index, line in enumerate(result):
        match = _SIMPLE_ALIAS.fullmatch(line)
        if match is None:
            continue
        lhs = match.group("lhs")
        rhs = match.group("rhs")
        if "." not in rhs and lhs != rhs:
            continue
        assigned_later = any(
            re.match(rf"^\s*{re.escape(lhs)}\s*=", candidate)
            for candidate in result[index + 1 :]
        )
        if assigned_later:
            continue
        aliases.append((index, lhs, rhs))

    removed: set[int] = set()
    for index, lhs, rhs in aliases:
        removed.add(index)
        if lhs == rhs:
            continue
        pattern = re.compile(rf"\b{re.escape(lhs)}\b")
        for following in range(index + 1, len(result)):
            if following in removed:
                continue
            result[following] = pattern.sub(rhs, result[following])
    return [
        line
        for index, line in enumerate(result)
        if index not in removed
    ]


def _remove_redundant_while_guards(lines: list[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^(?P<indent>\s*)while\s+(?P<cond>.+)\s+do$", line)
        if match is None:
            result.append(line)
            index += 1
            continue
        result.append(line)
        if index + 3 < len(lines):
            child_indent = match.group("indent") + "    "
            guard = lines[index + 1]
            break_line = lines[index + 2]
            end_line = lines[index + 3]
            guard_match = re.match(
                rf"^{re.escape(child_indent)}if\s+(.+)\s+then$",
                guard,
            )
            if (
                guard_match is not None
                and break_line == child_indent + "    break"
                and end_line == child_indent + "end"
            ):
                guard_condition = _simplify_not_comparisons(
                    guard_match.group(1)
                )
                expected = _simplify_not_comparisons(
                    f"not ({match.group('cond')})"
                )
                if guard_condition == expected:
                    index += 4
                    continue
        index += 1
    return result


def _find_matching_end(lines: list[str], start: int) -> int | None:
    indent = len(lines[start]) - len(lines[start].lstrip())
    depth = 0
    open_pattern = re.compile(
        r"^(?:if\b.+\bthen|while\b.+\bdo|for\b.+\bdo|function\b|local function\b|repeat)$"
    )
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if index == start:
            depth = 1
            continue
        if open_pattern.match(stripped):
            depth += 1
        if stripped == "end" or stripped.startswith("until "):
            depth -= 1
            if depth == 0:
                current_indent = len(lines[index]) - len(lines[index].lstrip())
                if current_indent == indent:
                    return index
    return None


def _rewrite_terminal_repeat_guards(lines: list[str]) -> list[str]:
    result = list(lines)
    index = 0
    while index < len(result):
        if not re.match(r"^\s*while true do$", result[index]):
            index += 1
            continue
        outer_end = _find_matching_end(result, index)
        if outer_end is None:
            index += 1
            continue
        outer_indent = result[index][
            : len(result[index]) - len(result[index].lstrip())
        ]
        inner_indent = outer_indent + "    "
        candidate = outer_end - 1
        while candidate > index and not result[candidate].strip():
            candidate -= 1
        while_start = None
        for probe in range(candidate, index, -1):
            if re.match(
                rf"^{re.escape(inner_indent)}while\s+.+\s+do$",
                result[probe],
            ):
                inner_end = _find_matching_end(result, probe)
                if inner_end == candidate:
                    while_start = probe
                    break
        if while_start is None:
            index = outer_end + 1
            continue
        header = re.match(
            rf"^{re.escape(inner_indent)}while\s+(?P<cond>.+)\s+do$",
            result[while_start],
        )
        if header is None:
            index = outer_end + 1
            continue
        body = result[while_start + 1 : candidate]
        exit_conditions: list[str] = [
            _simplify_not_comparisons(f"not ({header.group('cond')})")
        ]
        cursor = 0
        valid = True
        while cursor < len(body):
            if not body[cursor].strip():
                cursor += 1
                continue
            guard = re.match(
                rf"^{re.escape(inner_indent + '    ')}if\s+(.+)\s+then$",
                body[cursor],
            )
            if (
                guard is None
                or cursor + 2 >= len(body)
                or body[cursor + 1] != inner_indent + "        break"
                or body[cursor + 2] != inner_indent + "    end"
            ):
                valid = False
                break
            exit_conditions.append(
                _simplify_not_comparisons(guard.group(1))
            )
            cursor += 3
        if not valid:
            index = outer_end + 1
            continue
        deduped = list(dict.fromkeys(exit_conditions))
        result[index] = outer_indent + "repeat"
        del result[while_start : candidate + 1]
        outer_end -= candidate + 1 - while_start
        result[outer_end] = outer_indent + "until " + " or ".join(deduped)
        index = outer_end + 1
    return result


def _flatten_single_inner_while(lines: list[str]) -> list[str]:
    result = list(lines)
    index = 0
    while index < len(result):
        if not re.match(r"^\s*while true do$", result[index]):
            index += 1
            continue
        outer_end = _find_matching_end(result, index)
        if outer_end is None:
            index += 1
            continue
        outer_indent = result[index][
            : len(result[index]) - len(result[index].lstrip())
        ]
        child_indent = outer_indent + "    "
        meaningful = [
            pos
            for pos in range(index + 1, outer_end)
            if result[pos].strip()
        ]
        if not meaningful:
            index = outer_end + 1
            continue
        first = meaningful[0]
        if not re.match(
            rf"^{re.escape(child_indent)}while\s+.+\s+do$",
            result[first],
        ):
            index = outer_end + 1
            continue
        inner_end = _find_matching_end(result, first)
        if inner_end != meaningful[-1]:
            index = outer_end + 1
            continue
        replacement = [
            line[4:] if line.startswith(child_indent) else line
            for line in result[first : inner_end + 1]
        ]
        result[index : outer_end + 1] = replacement
        index += len(replacement)
    return result


def _rewrite_empty_loop_exit_ifs(lines: list[str]) -> list[str]:
    result = list(lines)
    index = 0
    while index + 2 < len(result):
        match = re.match(
            r"^(?P<indent>\s*)if\s+(?P<cond>.+)\s+then$",
            result[index],
        )
        if match is None or result[index + 1] != match.group("indent") + "end":
            index += 1
            continue
        indent = match.group("indent")
        if len(indent) < 4 or result[index + 2] != indent[:-4] + "end":
            index += 1
            continue
        condition = _simplify_not_comparisons(
            f"not ({match.group('cond')})"
        )
        result[index : index + 2] = [
            f"{indent}if {condition} then",
            f"{indent}    break",
            f"{indent}end",
        ]
        index += 3
    return result


def _clean_output(output: str) -> str:
    lines = [
        line
        for line in output.splitlines()
        if not line.lstrip().startswith("--")
    ]
    lines = [_FLOAT_INTEGER.sub(r"\1", line.rstrip()) for line in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    lines = _inline_simple_aliases(lines)
    lines = _remove_redundant_while_guards(lines)
    lines = _rewrite_terminal_repeat_guards(lines)
    lines = _flatten_single_inner_while(lines)
    lines = _rewrite_empty_loop_exit_ifs(lines)
    lines = [_simplify_not_comparisons(line) for line in lines]
    lines = [
        line
        for line in lines
        if not (
            _TOP_LEVEL_RETURN.match(line)
            and not line.startswith((" ", "\t"))
        )
    ]
    compact: list[str] = []
    for line in lines:
        if not line.strip() and (not compact or not compact[-1].strip()):
            continue
        compact.append(line)
    return "\n".join(compact).rstrip() + "\n"


def decompile_module(module, options: dict[str, bool], filename: str | None) -> str:
    return _clean_output(legacy.decompile_module(module, options, filename))


disassemble_module = legacy.disassemble_module

__all__ = ["decompile_module", "disassemble_module"]
