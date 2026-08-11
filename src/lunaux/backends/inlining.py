from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lunaux.backends.bytecode import LuauProto
from lunaux.backends.callframe import CallFramePlan, plan_call_frames
from lunaux.backends.effects import (
    EffectKind,
    InstructionEffect,
    classify_instruction,
    is_transparent_instruction,
)
from lunaux.backends.opcodes import DecodedInstruction, get_jump_target, setlist_semantics
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
        "GETTABLEKS",
        "GETUDATAKS",
        "GETTABLEN",
        "SETTABLE",
        "SETTABLEKS",
        "SETUDATAKS",
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
_CONDITION_CONSUMERS = frozenset(
    {
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
    }
)
_ATOMIC_EXPRESSION = re.compile(
    r"^(?:nil|true|false|-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    r'|"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z0-9_]*)$'
)


@dataclass(frozen=True, slots=True)
class InlineCandidate:
    value: SSAValue
    definition_pc: int
    use_pc: int
    register: int
    dependencies: frozenset[SSAValue]
    evaluation_pcs: tuple[int, ...]
    effect: InstructionEffect


@dataclass(frozen=True, slots=True)
class ExpressionInliningPlan:
    candidates: Mapping[SSAValue, InlineCandidate]
    by_definition: Mapping[tuple[int, int], InlineCandidate]
    call_frames: CallFramePlan

    def candidate_for_definition(
        self,
        pc: int,
        register: int,
    ) -> InlineCandidate | None:
        return self.by_definition.get((pc, register))

    def should_inline(self, value: SSAValue | None) -> bool:
        return value is not None and value in self.candidates


def _debug_visible(proto: LuauProto, register: int, pc: int) -> bool:
    return any(
        local.register == register
        and local.name is not None
        and local.start_pc <= pc < local.end_pc
        for local in proto.locals
    ) or any(
        local.register == register and local.start_pc <= pc < local.end_pc
        for local in proto.typed_locals
    )


def _use_sites(program: SSAProgram) -> Mapping[SSAValue, tuple[int, ...]]:
    sites: dict[SSAValue, list[int]] = defaultdict(list)
    for pc, instruction in program.instructions.items():
        if instruction.instruction.name.startswith("FASTCALL"):
            continue
        for use in instruction.uses:
            sites[use.value].append(pc)
    return MappingProxyType({value: tuple(sorted(set(pcs))) for value, pcs in sites.items()})


def _use_occurrences(program: SSAProgram, value: SSAValue) -> int:
    return sum(
        use.value == value
        for instruction in program.instructions.values()
        if not instruction.instruction.name.startswith("FASTCALL")
        for use in instruction.uses
    )


def _debug_visible_through(
    proto: LuauProto,
    register: int,
    definition_pc: int,
    use_pc: int,
) -> bool:
    return any(
        local.register == register
        and local.start_pc <= use_pc
        and local.end_pc > definition_pc
        for local in proto.locals
    ) or any(
        local.register == register
        and local.start_pc <= use_pc
        and local.end_pc > definition_pc
        for local in proto.typed_locals
    )


def _fastcall_bridge(
    program: SSAProgram,
    definition_pc: int,
    consumer_pc: int,
) -> bool:
    definition_block = program.analysis.block_for_pc.get(definition_pc)
    consumer_block = program.analysis.block_for_pc.get(consumer_pc)
    if definition_block is None or consumer_block is None:
        return False
    fallback = program.analysis.block_by_start.get(definition_block)
    if fallback is None or fallback.successors != frozenset({consumer_block}):
        return False
    return any(
        instruction.instruction.name.startswith("FASTCALL")
        and get_jump_target(instruction.instruction) == consumer_block
        and definition_block
        in program.analysis.block_by_start[
            program.analysis.block_for_pc[instruction.pc]
        ].successors
        and consumer_block
        in program.analysis.block_by_start[
            program.analysis.block_for_pc[instruction.pc]
        ].successors
        for instruction in program.instructions.values()
        if instruction.pc < definition_pc
        and instruction.pc in program.analysis.block_for_pc
    )


def _fastcall_value_bridge(
    program: SSAProgram,
    definition_pc: int,
    use_pc: int,
) -> bool:
    definition_block = program.analysis.block_for_pc.get(definition_pc)
    use_block = program.analysis.block_for_pc.get(use_pc)
    if definition_block is None or use_block is None:
        return False
    if definition_block == use_block:
        return True
    header = program.analysis.block_by_start.get(definition_block)
    if header is None:
        return False
    return any(
        instruction.instruction.name.startswith("FASTCALL")
        and instruction.pc > definition_pc
        and use_block in header.successors
        and get_jump_target(instruction.instruction) in header.successors
        for instruction in program.instructions.values()
        if program.analysis.block_for_pc.get(instruction.pc) == definition_block
    )


def _value(program: SSAProgram, pc: int, register: int) -> SSAValue | None:
    return program.value_at_use(pc, register)


def _ordered_operand_values(
    program: SSAProgram,
    instruction: DecodedInstruction,
    call_frames: CallFramePlan,
) -> tuple[SSAValue, ...]:
    pc = instruction.pc
    name = instruction.name
    registers: tuple[int, ...]
    if name == "MOVE":
        registers = (instruction.b,)
    elif name in {"SETGLOBAL", "SETUPVAL"}:
        registers = (instruction.a,)
    elif name == "GETTABLE":
        registers = (instruction.b, instruction.c)
    elif name in {"GETTABLEKS", "GETUDATAKS", "GETTABLEN"}:
        registers = (instruction.b,)
    elif name == "SETTABLE":
        # The table owner is deliberately excluded. Dynamic constructor keys and
        # values retain their bytecode evaluation order.
        registers = (instruction.c, instruction.a)
    elif name in {"SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
        registers = (instruction.a,)
    elif name in {"NAMECALL", "NAMECALLUDATA"}:
        registers = (instruction.b,)
    elif name in {"ADD", "SUB", "MUL", "DIV", "MOD", "POW", "IDIV", "AND", "OR"}:
        registers = (instruction.b, instruction.c)
    elif name in {
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
        registers = (instruction.b,)
    elif name in {"SUBRK", "DIVRK"}:
        registers = (instruction.c,)
    elif name in {"NOT", "MINUS", "LENGTH"}:
        registers = (instruction.b,)
    elif name == "CONCAT":
        registers = tuple(range(instruction.b, instruction.c + 1))
    elif name in {"CALL", "CALLFB"}:
        frame = call_frames.at(pc)
        if frame is None:
            registers = ()
        elif frame.namecall_pc is not None:
            registers = frame.argument_registers
        else:
            registers = (frame.callee_register, *frame.argument_registers)
    elif name == "RETURN":
        if instruction.b == 0:
            multi_use = program.multi_use_at(pc)
            registers = multi_use.prefix_registers if multi_use is not None else ()
        else:
            registers = tuple(range(instruction.a, instruction.a + max(0, instruction.b - 1)))
    elif name == "SETLIST":
        semantics = setlist_semantics(instruction)
        if semantics is None:
            registers = ()
        else:
            registers = tuple(
                range(
                    semantics.first_value_register,
                    semantics.first_value_register + semantics.source_register_count,
                )
            )
    elif name in {
        "JUMPIF",
        "JUMPIFNOT",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "CMPPROTO",
    }:
        registers = (instruction.a,)
    elif name in {
        "JUMPIFEQ",
        "JUMPIFLE",
        "JUMPIFLT",
        "JUMPIFNOTEQ",
        "JUMPIFNOTLE",
        "JUMPIFNOTLT",
    }:
        registers = (instruction.a, (instruction.aux or 0) & 0xFF)
    elif name == "FORNPREP":
        registers = tuple(range(instruction.a, instruction.a + 3))
    elif name in {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}:
        registers = tuple(range(instruction.a, instruction.a + 3))
    elif name == "NEWCLASSMEMBER":
        registers = (instruction.c,)
    else:
        registers = ()

    result: list[SSAValue] = []
    for register in registers:
        value = _value(program, pc, register)
        if value is not None:
            result.append(value)
    return tuple(result)


def plan_expression_inlining(
    program: SSAProgram,
    proto: LuauProto,
    *,
    call_frames: CallFramePlan | None = None,
) -> ExpressionInliningPlan:
    sites = _use_sites(program)
    resolved_call_frames = call_frames or plan_call_frames(program)
    selected: dict[SSAValue, InlineCandidate] = {}
    memo: dict[tuple[SSAValue, int], tuple[tuple[SSAValue, ...], tuple[int, ...]] | None] = {}

    def graph_for(
        value: SSAValue,
        consumer_pc: int,
        seen: frozenset[SSAValue] = frozenset(),
    ) -> tuple[tuple[SSAValue, ...], tuple[int, ...]] | None:
        key = (value, consumer_pc)
        if not seen and key in memo:
            return memo[key]
        if value in seen or value.kind != "instruction" or value.origin_pc is None:
            return None
        definition_pc = value.origin_pc
        definition = program.instructions.get(definition_pc)
        if definition is None or definition.instruction.name not in _INLINEABLE_DEFINITIONS:
            return None
        if len(definition.definitions) != 1 or _use_occurrences(program, value) != 1:
            return None
        if sites.get(value) != (consumer_pc,):
            return None
        if definition.instruction.name == "LOADB" and definition.instruction.c:
            return None
        if definition.instruction.name in {"CALL", "CALLFB"} and definition.instruction.c != 2:
            return None
        if _debug_visible(proto, value.register, definition_pc):
            return None
        if definition_pc >= consumer_pc:
            return None
        block = program.analysis.block_for_pc.get(definition_pc)
        consumer_block = program.analysis.block_for_pc.get(consumer_pc)
        if block is None or (
            block != consumer_block
            and not (
                definition.instruction.name in {"CALL", "CALLFB"}
                and _fastcall_bridge(program, definition_pc, consumer_pc)
            )
        ):
            return None
        effect = classify_instruction(definition.instruction)
        if not effect.expression_capable:
            return None

        values: list[SSAValue] = []
        pcs: list[int] = []
        operands = _ordered_operand_values(
            program,
            definition.instruction,
            resolved_call_frames,
        )
        for operand in operands:
            if operand not in selected:
                continue
            child = graph_for(operand, definition_pc, seen | frozenset({value}))
            if child is None:
                continue
            child_values, child_pcs = child
            values.extend(child_values)
            pcs.extend(child_pcs)
        values.append(value)
        pcs.append(definition_pc)
        result = (tuple(dict.fromkeys(values)), tuple(dict.fromkeys(pcs)))
        if not seen:
            memo[key] = result
        return result

    for consumer_pc in sorted(program.instructions):
        consumer = program.instructions[consumer_pc].instruction
        if consumer.name not in _SUPPORTED_CONSUMERS:
            continue
        operands = _ordered_operand_values(program, consumer, resolved_call_frames)
        suffix: list[tuple[tuple[SSAValue, ...], tuple[int, ...]]] = []
        for operand in reversed(operands):
            graph = graph_for(operand, consumer_pc)
            if graph is None:
                break
            if consumer.name in _CONDITION_CONSUMERS:
                root_pc = operand.origin_pc
                if root_pc is None or classify_instruction(
                    program.instructions[root_pc].instruction
                ).kind != EffectKind.LITERAL:
                    break
            suffix.append(graph)
        if not suffix:
            continue
        suffix.reverse()
        values = tuple(value for graph, _pcs in suffix for value in graph)
        evaluation_pcs = tuple(pc for _graph, pcs in suffix for pc in pcs)
        if not evaluation_pcs or tuple(sorted(set(evaluation_pcs))) != evaluation_pcs:
            continue

        while evaluation_pcs:
            first_pc = evaluation_pcs[0]
            allowed = frozenset(evaluation_pcs)
            dependency_registers = {
                use.register
                for value in values
                if value.origin_pc is not None
                for use in program.instructions[value.origin_pc].uses
            }
            unexpected = tuple(
                pc
                for pc in sorted(program.instructions)
                if first_pc <= pc < consumer_pc
                and pc not in allowed
                and (
                    not is_transparent_instruction(program.instructions[pc].instruction)
                    or any(
                        definition.register in dependency_registers
                        for definition in program.instructions[pc].definitions
                    )
                )
            )
            if not unexpected:
                break
            cutoff = unexpected[-1]
            values = tuple(
                value
                for value in values
                if value.origin_pc is not None and value.origin_pc > cutoff
            )
            evaluation_pcs = tuple(
                value.origin_pc for value in values if value.origin_pc is not None
            )
        if not evaluation_pcs:
            continue

        for value in values:
            definition_pc = value.origin_pc
            if definition_pc is None:
                continue
            definition = program.instructions[definition_pc]
            use_pc = sites[value][0]
            dependencies = frozenset(use.value for use in definition.uses)
            candidate = InlineCandidate(
                value=value,
                definition_pc=definition_pc,
                use_pc=use_pc,
                register=value.register,
                dependencies=dependencies,
                evaluation_pcs=evaluation_pcs,
                effect=classify_instruction(definition.instruction),
            )
            selected[value] = candidate

    # Literals carry no evaluation, allocation, lookup, or metamethod effect.  A
    # single-use literal can therefore cross a CFG join (including FASTCALL's
    # optimized/fallback diamond) without reordering any observable operation.
    for value, use_pcs in sites.items():
        if value in selected or value.kind != "instruction" or value.origin_pc is None:
            continue
        portable_definition = program.instructions.get(value.origin_pc)
        if (
            portable_definition is None
            or classify_instruction(portable_definition.instruction).kind
            != EffectKind.LITERAL
            or (
                portable_definition.instruction.name == "LOADB"
                and portable_definition.instruction.c != 0
            )
            or len(portable_definition.definitions) != 1
            or _use_occurrences(program, value) != 1
            or len(use_pcs) != 1
        ):
            continue
        use_pc = use_pcs[0]
        if (
            _debug_visible_through(proto, value.register, value.origin_pc, use_pc)
            or not _fastcall_value_bridge(program, value.origin_pc, use_pc)
            or sum(
                operand == value
                for operand in _ordered_operand_values(
                    program,
                    program.instructions[use_pc].instruction,
                    resolved_call_frames,
                )
            )
            != 1
        ):
            continue
        if program.instructions[use_pc].instruction.name not in _SUPPORTED_CONSUMERS:
            continue
        candidate = InlineCandidate(
            value=value,
            definition_pc=value.origin_pc,
            use_pc=use_pc,
            register=value.register,
            dependencies=frozenset(),
            evaluation_pcs=(value.origin_pc,),
            effect=classify_instruction(portable_definition.instruction),
        )
        selected[value] = candidate

    # A MOVE of an entry binding is only a lexical reference.  It can cross
    # lookup/setup instructions when no call, mutation, control edge, or
    # redefinition of that entry register intervenes.
    for value, use_pcs in sites.items():
        if value in selected or value.kind != "instruction" or value.origin_pc is None:
            continue
        move_definition = program.instructions.get(value.origin_pc)
        if (
            move_definition is None
            or move_definition.instruction.name != "MOVE"
            or _use_occurrences(program, value) != 1
            or len(use_pcs) != 1
        ):
            continue
        source = program.value_at_use(value.origin_pc, move_definition.instruction.b)
        if source is None or source.kind != "entry":
            continue
        use_pc = use_pcs[0]
        if (
            _debug_visible_through(proto, value.register, value.origin_pc, use_pc)
            or sum(
                operand == value
                for operand in _ordered_operand_values(
                    program,
                    program.instructions[use_pc].instruction,
                    resolved_call_frames,
                )
            )
            != 1
        ):
            continue
        gap = [
            instruction
            for pc, instruction in program.instructions.items()
            if value.origin_pc < pc < use_pc
        ]
        if any(
            effect.writes_state
            or effect.may_call
            or effect.changes_control_flow
            or any(item.register == source.register for item in instruction.definitions)
            for instruction in gap
            for effect in (classify_instruction(instruction.instruction),)
        ):
            continue
        candidate = InlineCandidate(
            value=value,
            definition_pc=value.origin_pc,
            use_pc=use_pc,
            register=value.register,
            dependencies=frozenset({source}),
            evaluation_pcs=(value.origin_pc,),
            effect=classify_instruction(move_definition.instruction),
        )
        selected[value] = candidate

    by_definition = {
        (candidate.definition_pc, candidate.register): candidate for candidate in selected.values()
    }
    return ExpressionInliningPlan(
        candidates=MappingProxyType(selected),
        by_definition=MappingProxyType(by_definition),
        call_frames=resolved_call_frames,
    )


def parenthesize_inlined_expression(expression: str) -> str:
    stripped = expression.strip()
    if _ATOMIC_EXPRESSION.fullmatch(stripped):
        return stripped
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped
    return f"({stripped})"


__all__ = [
    "ExpressionInliningPlan",
    "InlineCandidate",
    "parenthesize_inlined_expression",
    "plan_expression_inlining",
]
