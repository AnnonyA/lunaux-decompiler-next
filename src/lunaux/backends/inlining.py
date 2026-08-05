from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lunaux.backends.bytecode import LuauProto
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAProgram, SSAValue

_INLINEABLE_DEFINITIONS = frozenset(
    {
        "LOADNIL",
        "LOADB",
        "LOADN",
        "LOADK",
        "LOADKX",
        "MOVE",
        "GETGLOBAL",
        "GETIMPORT",
        "GETUPVAL",
        "GETTABLE",
        "GETTABLEKS",
        "GETUDATAKS",
        "GETTABLEN",
        "ADD",
        "SUB",
        "MUL",
        "DIV",
        "MOD",
        "POW",
        "IDIV",
        "AND",
        "OR",
        "ADDK",
        "SUBK",
        "MULK",
        "DIVK",
        "MODK",
        "POWK",
        "IDIVK",
        "ANDK",
        "ORK",
        "SUBRK",
        "DIVRK",
        "NOT",
        "MINUS",
        "LENGTH",
        "CONCAT",
        "NEWTABLE",
        "DUPTABLE",
        "DUPCLOSURE",
        "CALL",
        "CALLFB",
    }
)
_SUPPORTED_CONSUMERS = frozenset(
    {
        "MOVE",
        "SETGLOBAL",
        "SETUPVAL",
        "GETTABLE",
        "SETTABLE",
        "GETTABLEKS",
        "GETUDATAKS",
        "SETTABLEKS",
        "SETUDATAKS",
        "GETTABLEN",
        "SETTABLEN",
        "NAMECALL",
        "NAMECALLUDATA",
        "ADD",
        "SUB",
        "MUL",
        "DIV",
        "MOD",
        "POW",
        "IDIV",
        "AND",
        "OR",
        "ADDK",
        "SUBK",
        "MULK",
        "DIVK",
        "MODK",
        "POWK",
        "IDIVK",
        "ANDK",
        "ORK",
        "SUBRK",
        "DIVRK",
        "NOT",
        "MINUS",
        "LENGTH",
        "CONCAT",
        "SETLIST",
        "CALL",
        "CALLFB",
        "RETURN",
        "JUMPIF",
        "JUMPIFNOT",
        "JUMPIFEQ",
        "JUMPIFLE",
        "JUMPIFLT",
        "JUMPIFNOTEQ",
        "JUMPIFNOTLE",
        "JUMPIFNOTLT",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "FORNPREP",
        "FORGPREP",
        "FORGPREP_INEXT",
        "FORGPREP_NEXT",
        "CMPPROTO",
        "NEWCLASS",
        "NEWCLASSMEMBER",
    }
)


@dataclass(frozen=True, slots=True)
class InlineCandidate:
    value: SSAValue
    definition_pc: int
    use_pc: int
    register: int


@dataclass(frozen=True, slots=True)
class ExpressionInliningPlan:
    candidates: Mapping[SSAValue, InlineCandidate]

    def candidate_for_definition(
        self,
        pc: int,
        register: int,
    ) -> InlineCandidate | None:
        for candidate in self.candidates.values():
            if candidate.definition_pc == pc and candidate.register == register:
                return candidate
        return None

    def should_inline(self, value: SSAValue | None) -> bool:
        return value is not None and value in self.candidates


def _debug_visible(proto: LuauProto, register: int, pc: int) -> bool:
    named_local = any(
        local.register == register
        and local.name is not None
        and local.start_pc <= pc < local.end_pc
        for local in proto.locals
    )
    typed_local = any(
        local.register == register and local.start_pc <= pc < local.end_pc
        for local in proto.typed_locals
    )
    return named_local or typed_local


def _register_operands(instruction: DecodedInstruction) -> list[int]:
    name = instruction.name
    if name == "MOVE":
        return [instruction.b]
    if name in {"SETGLOBAL", "SETUPVAL"}:
        return [instruction.a]
    if name == "GETTABLE":
        return [instruction.b, instruction.c]
    if name == "SETTABLE":
        return [instruction.a, instruction.b, instruction.c]
    if name in {"GETTABLEKS", "GETUDATAKS", "GETTABLEN"}:
        return [instruction.b]
    if name in {"SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
        return [instruction.a, instruction.b]
    if name in {"NAMECALL", "NAMECALLUDATA"}:
        return [instruction.b]
    if name in {"ADD", "SUB", "MUL", "DIV", "MOD", "POW", "IDIV", "AND", "OR"}:
        return [instruction.b, instruction.c]
    if name in {
        "ADDK",
        "SUBK",
        "MULK",
        "DIVK",
        "MODK",
        "POWK",
        "IDIVK",
        "ANDK",
        "ORK",
    }:
        return [instruction.b]
    if name in {"SUBRK", "DIVRK"}:
        return [instruction.c]
    if name in {"NOT", "MINUS", "LENGTH"}:
        return [instruction.b]
    if name == "CONCAT":
        return list(range(instruction.b, instruction.c + 1))
    if name in {
        "JUMPIF",
        "JUMPIFNOT",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "CMPPROTO",
    }:
        return [instruction.a]
    if name in {
        "JUMPIFEQ",
        "JUMPIFLE",
        "JUMPIFLT",
        "JUMPIFNOTEQ",
        "JUMPIFNOTLE",
        "JUMPIFNOTLT",
    }:
        return [instruction.a, (instruction.aux or 0) & 0xFF]
    if name in {"CALL", "CALLFB"}:
        if instruction.b == 0:
            return [instruction.a]
        return list(range(instruction.a, instruction.a + instruction.b))
    if name == "RETURN":
        if instruction.b == 0:
            return [instruction.a]
        return list(range(instruction.a, instruction.a + max(0, instruction.b - 1)))
    if name == "SETLIST":
        values = [instruction.a]
        count = instruction.c - 1 if instruction.c > 0 else 1
        values.extend(range(instruction.b, instruction.b + count))
        return values
    if name == "FORNPREP":
        return list(range(instruction.a, instruction.a + 3))
    if name in {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}:
        return list(range(instruction.a, instruction.a + 3))
    if name == "NEWCLASS":
        return [] if instruction.b == 0xFF else [instruction.b]
    if name == "NEWCLASSMEMBER":
        return [instruction.a, instruction.c]
    return []


def _use_sites(program: SSAProgram) -> Mapping[SSAValue, tuple[int, ...]]:
    sites: dict[SSAValue, list[int]] = defaultdict(list)
    for pc, instruction in program.instructions.items():
        for use in instruction.uses:
            sites[use.value].append(pc)
    return MappingProxyType(
        {
            value: tuple(sorted(set(pcs)))
            for value, pcs in sites.items()
        }
    )


def plan_expression_inlining(
    program: SSAProgram,
    proto: LuauProto,
) -> ExpressionInliningPlan:
    sites = _use_sites(program)
    candidates: dict[SSAValue, InlineCandidate] = {}

    for value in program.single_use_instruction_values():
        definition_pc = value.origin_pc
        if definition_pc is None:
            continue
        definition = program.instructions.get(definition_pc)
        if definition is None or definition.instruction.name not in _INLINEABLE_DEFINITIONS:
            continue
        if len(definition.definitions) != 1:
            continue
        if definition.instruction.name == "LOADB" and definition.instruction.c:
            continue
        if definition.instruction.name in {"CALL", "CALLFB"}:
            if definition.instruction.c != 2:
                continue
        if _debug_visible(proto, value.register, definition_pc):
            continue

        value_sites = sites.get(value, ())
        if len(value_sites) != 1:
            continue
        use_pc = value_sites[0]
        consumer = program.instructions.get(use_pc)
        if consumer is None or consumer.instruction.name not in _SUPPORTED_CONSUMERS:
            continue
        if definition_pc + definition.instruction.size != use_pc:
            continue
        definition_block = program.analysis.block_for_pc.get(definition_pc)
        use_block = program.analysis.block_for_pc.get(use_pc)
        if definition_block is None or definition_block != use_block:
            continue
        if _register_operands(consumer.instruction).count(value.register) != 1:
            continue

        candidates[value] = InlineCandidate(
            value=value,
            definition_pc=definition_pc,
            use_pc=use_pc,
            register=value.register,
        )

    return ExpressionInliningPlan(candidates=MappingProxyType(candidates))


def parenthesize_inlined_expression(expression: str) -> str:
    stripped = expression.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped
    return f"({stripped})"
