from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from lunaux.backends.bytecode import LuauProto
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.scopes import ScopeTree
from lunaux.backends.ssa import SSAProgram, SSAValue

if TYPE_CHECKING:
    from lunaux.backends.symbols import SymbolRecovery

FunctionRole = Literal["normal", "method", "recursive"]
NameSource = Literal[
    "debug-parameter",
    "debug-local",
    "context",
    "symbol",
    "field",
    "structural-role",
    "fallback",
]

_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GENERATED: Final[re.Pattern[str]] = re.compile(
    r"^(?:arg|v|value|result|callback|data|item|key|index|condition|func)_?\d*$"
)
_RESERVED: Final[frozenset[str]] = frozenset(
    {
        "and", "break", "class", "continue", "do", "else", "elseif", "end",
        "export", "extends", "false", "for", "function", "if", "in", "local",
        "nil", "not", "or", "public", "repeat", "return", "then", "true",
        "type", "typeof", "until", "while",
    }
)
_ARITHMETIC_OPS: Final[frozenset[str]] = frozenset(
    {
        "ADD", "SUB", "MUL", "DIV", "MOD", "POW", "IDIV", "ADDK", "SUBK",
        "MULK", "DIVK", "MODK", "POWK", "IDIVK", "SUBRK", "DIVRK",
    }
)


@dataclass(frozen=True, slots=True)
class NameEvidence:
    candidate: str
    source: NameSource
    confidence: int
    detail: str


@dataclass(frozen=True, slots=True)
class SemanticNamePlan:
    entry_names: Mapping[int, str]
    value_names: Mapping[SSAValue, str]
    evidence: Mapping[SSAValue, NameEvidence]
    conflicts: Mapping[str, tuple[str, ...]]
    reserved: frozenset[str]

    def name_at_use(self, program: SSAProgram, pc: int, register: int) -> str | None:
        value = program.value_at_use(pc, register)
        return self.value_names.get(value) if value is not None else None

    def name_at_definition(
        self,
        program: SSAProgram,
        pc: int,
        register: int,
    ) -> str | None:
        value = program.value_defined_at(pc, register)
        return self.value_names.get(value) if value is not None else None


def valid_identifier(value: str | None) -> bool:
    return bool(value and _IDENTIFIER.fullmatch(value) and value not in _RESERVED)


def generated_identifier(value: str | None) -> bool:
    return bool(value and _GENERATED.fullmatch(value))


def _debug_parameter_name(
    proto: LuauProto,
    program: SSAProgram,
    first_use_by_value: Mapping[SSAValue, int],
    register: int,
) -> str | None:
    entry = program.entry_values.get(register)
    first_use = first_use_by_value.get(entry, 0) if entry is not None else 0
    matches = [
        local.name
        for local in proto.locals
        if local.register == register
        and local.start_pc <= first_use < local.end_pc
        and valid_identifier(local.name)
    ]
    return matches[0] if matches else None


def _parameter_is_arithmetic(program: SSAProgram, register: int) -> bool:
    entry = program.entry_values.get(register)
    if entry is None:
        return False
    consumers = [
        instruction.instruction.name
        for instruction in program.instructions.values()
        if any(use.value == entry for use in instruction.uses)
    ]
    return bool(consumers) and any(name in _ARITHMETIC_OPS for name in consumers)


def _entry_evidence(
    proto: LuauProto,
    program: SSAProgram,
    register: int,
    overrides: Mapping[int, str],
    symbol_name: str | None,
    role: FunctionRole,
    first_use_by_value: Mapping[SSAValue, int],
) -> NameEvidence:
    debug = _debug_parameter_name(proto, program, first_use_by_value, register)
    if debug is not None:
        return NameEvidence(debug, "debug-parameter", 100, "active debug parameter")
    contextual = overrides.get(register)
    if valid_identifier(contextual) and not generated_identifier(contextual):
        assert contextual is not None
        return NameEvidence(contextual, "context", 90, "exact contextual signature")
    if valid_identifier(symbol_name) and not generated_identifier(symbol_name):
        assert symbol_name is not None
        return NameEvidence(symbol_name, "symbol", 85, "recovered entry symbol")
    if role == "method" and register == 0:
        return NameEvidence("self", "structural-role", 90, "proven method receiver")
    if (
        role == "method"
        and proto.num_params == 2
        and register == 1
        and _parameter_is_arithmetic(program, register)
    ):
        return NameEvidence(
            "amount",
            "structural-role",
            72,
            "sole non-receiver parameter participates in arithmetic",
        )
    if role == "recursive" and proto.num_params == 1 and register == 0:
        return NameEvidence("value", "structural-role", 70, "direct-recursion operand")
    if valid_identifier(contextual):
        assert contextual is not None
        return NameEvidence(contextual, "context", 60, "generated contextual signature")
    return NameEvidence(
        f"arg{register + 1}",
        "fallback",
        0,
        "deterministic parameter fallback",
    )


def _field_hint(proto: LuauProto, instruction: DecodedInstruction) -> str | None:
    if instruction.name not in {"GETTABLEKS", "GETUDATAKS"}:
        return None
    index = (
        (instruction.aux or 0) & 0xFFFF
        if instruction.name == "GETUDATAKS"
        else instruction.aux
    )
    if index is None or not 0 <= index < len(proto.constants):
        return None
    constant = proto.constants[index]
    if constant.kind != "string" or not isinstance(constant.value, str):
        return None
    candidate = constant.value[:1].lower() + constant.value[1:]
    return candidate if valid_identifier(candidate) else None


def _debug_binding_for_value(
    scope_tree: ScopeTree,
    value: SSAValue,
    first_use_by_value: Mapping[SSAValue, int],
) -> bool:
    if value.origin_pc is None:
        return False
    direct = scope_tree.binding_for_register(value.register, value.origin_pc)
    if direct is not None:
        return True
    first_use = first_use_by_value.get(value)
    if first_use is None:
        return False
    return any(
        binding.register == value.register
        and value.origin_pc < binding.start_pc <= first_use
        for scope in scope_tree.scopes.values()
        for binding in scope.bindings
    )


def _allocate(base: str, occupied: set[str]) -> str:
    if base not in occupied:
        occupied.add(base)
        return base
    suffix = 2
    while f"{base}{suffix}" in occupied:
        suffix += 1
    result = f"{base}{suffix}"
    occupied.add(result)
    return result


def build_semantic_name_plan(
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
    scope_tree: ScopeTree,
    symbols: SymbolRecovery | None,
    *,
    parameter_overrides: Mapping[int, str] = MappingProxyType({}),
    function_role: FunctionRole = "normal",
) -> SemanticNamePlan:
    first_use_by_value: dict[SSAValue, int] = {}
    for ssa_instruction in sorted(
        program.instructions.values(),
        key=lambda item: item.pc,
    ):
        for use in ssa_instruction.uses:
            first_use_by_value.setdefault(use.value, ssa_instruction.pc)
    reserved = {
        binding.name
        for scope in scope_tree.scopes.values()
        for binding in scope.bindings
        if valid_identifier(binding.name)
    }
    entry_names: dict[int, str] = {}
    entry_occupied = set(reserved)
    for register in range(proto.num_params):
        evidence = _entry_evidence(
            proto,
            program,
            register,
            parameter_overrides,
            symbols.entry_names.get(register) if symbols is not None else None,
            function_role,
            first_use_by_value,
        )
        if evidence.source == "debug-parameter":
            name = evidence.candidate
        else:
            name = _allocate(evidence.candidate, entry_occupied)
        entry_names[register] = name
        reserved.add(name)

    occupied = set(reserved)
    value_names: dict[SSAValue, str] = {}
    evidence_by_value: dict[SSAValue, NameEvidence] = {}
    conflicts: dict[str, list[str]] = {}
    for instruction in sorted(instructions, key=lambda item: item.pc):
        for value in sorted(
            (item for item in program.instructions[instruction.pc].definitions),
            key=lambda item: (item.register, item.version),
        ):
            if program.uses_of(value) <= 0 or _debug_binding_for_value(
                scope_tree,
                value,
                first_use_by_value,
            ):
                continue
            symbol = symbols.symbol_for(value) if symbols is not None else None
            candidate: str | None = None
            source: NameSource
            confidence = 0
            detail = ""
            if symbol is not None and valid_identifier(symbol.name) and not generated_identifier(
                symbol.name
            ):
                candidate = symbol.name
                source = "symbol"
                confidence = max(75, symbol.confidence)
                detail = ", ".join(symbol.evidence)
            else:
                field = _field_hint(proto, instruction)
                if field is not None:
                    candidate = field
                    source = "field"
                    confidence = 70
                    detail = "exact GETTABLEKS field"
                elif instruction.name in {"NEWTABLE", "DUPTABLE"}:
                    candidate = "data"
                    source = "structural-role"
                    confidence = 55
                    detail = "new table value"
                elif instruction.name in {"CALL", "CALLFB"}:
                    candidate = "result"
                    source = "structural-role"
                    confidence = 50
                    detail = "call result"
            if candidate is None:
                continue
            allocated = _allocate(candidate, occupied)
            if allocated != candidate:
                conflicts.setdefault(candidate, []).append(allocated)
            value_names[value] = allocated
            evidence_by_value[value] = NameEvidence(
                allocated,
                source,
                confidence,
                detail,
            )

    return SemanticNamePlan(
        entry_names=MappingProxyType(entry_names),
        value_names=MappingProxyType(value_names),
        evidence=MappingProxyType(evidence_by_value),
        conflicts=MappingProxyType(
            {key: tuple(values) for key, values in sorted(conflicts.items())}
        ),
        reserved=frozenset(reserved),
    )
