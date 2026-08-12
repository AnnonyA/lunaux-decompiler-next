from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from lunaux.backends.analysis import (
    ControlFlowAnalysis,
    analyze_control_flow,
    reverse_postorder,
)
from lunaux.backends.opcodes import (
    DecodedInstruction,
    get_jump_target,
    setlist_semantics,
)

SSAValueKind = Literal["entry", "instruction", "phi"]
SSAMultiValueKind = Literal["call", "varargs"]
SSAMultiUseKind = Literal["arguments", "return", "setlist"]

@dataclass(frozen=True, order=True, slots=True)
class SSAValue:
    register: int
    version: int
    origin_pc: int | None
    kind: SSAValueKind

    @property
    def name(self) -> str:
        return f"R{self.register}.{self.version}"


@dataclass(frozen=True, order=True, slots=True)
class SSAMultiValue:
    origin_pc: int
    base_register: int
    kind: SSAMultiValueKind

    @property
    def name(self) -> str:
        return f"T{self.origin_pc}"


@dataclass(frozen=True, slots=True)
class SSAMultiUse:
    consumer_pc: int
    base_register: int
    kind: SSAMultiUseKind
    value: SSAMultiValue
    prefix_registers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SSAMultiValuePlan:
    values: tuple[SSAMultiValue, ...]
    uses: tuple[SSAMultiUse, ...]
    by_origin_pc: Mapping[int, SSAMultiValue]
    by_consumer_pc: Mapping[int, SSAMultiUse]

    @classmethod
    def empty(cls) -> SSAMultiValuePlan:
        return cls(
            values=(),
            uses=(),
            by_origin_pc=MappingProxyType({}),
            by_consumer_pc=MappingProxyType({}),
        )

    def value_at(self, pc: int) -> SSAMultiValue | None:
        return self.by_origin_pc.get(pc)

    def use_at(self, pc: int) -> SSAMultiUse | None:
        return self.by_consumer_pc.get(pc)

    @property
    def unresolved_values(self) -> tuple[SSAMultiValue, ...]:
        consumed = {use.value for use in self.uses}
        return tuple(value for value in self.values if value not in consumed)


@dataclass(frozen=True, slots=True)
class SSAUse:
    register: int
    value: SSAValue


@dataclass(frozen=True, slots=True)
class SSAInstruction:
    instruction: DecodedInstruction
    uses: tuple[SSAUse, ...]
    definitions: tuple[SSAValue, ...]

    @property
    def pc(self) -> int:
        return self.instruction.pc


@dataclass(frozen=True, slots=True)
class SSAPhi:
    block: int
    register: int
    result: SSAValue
    operands: Mapping[int, SSAValue]


@dataclass(frozen=True, slots=True)
class SSAProgram:
    analysis: ControlFlowAnalysis
    instructions: Mapping[int, SSAInstruction]
    phis: tuple[SSAPhi, ...]
    entry_values: Mapping[int, SSAValue]
    use_counts: Mapping[SSAValue, int]
    definitions: Mapping[tuple[int, int], SSAValue]
    multi_values: SSAMultiValuePlan = field(default_factory=SSAMultiValuePlan.empty)

    def instruction_at(self, pc: int) -> SSAInstruction | None:
        return self.instructions.get(pc)

    def value_at_use(self, pc: int, register: int) -> SSAValue | None:
        instruction = self.instructions.get(pc)
        if instruction is None:
            return None
        for use in instruction.uses:
            if use.register == register:
                return use.value
        return None

    def value_defined_at(self, pc: int, register: int) -> SSAValue | None:
        return self.definitions.get((pc, register))

    def multi_value_at(self, pc: int) -> SSAMultiValue | None:
        return self.multi_values.value_at(pc)

    def multi_use_at(self, pc: int) -> SSAMultiUse | None:
        return self.multi_values.use_at(pc)

    def uses_of(self, value: SSAValue) -> int:
        return self.use_counts.get(value, 0)

    def single_use_instruction_values(self) -> frozenset[SSAValue]:
        return frozenset(
            value
            for value, count in self.use_counts.items()
            if value.kind == "instruction" and count == 1
        )


@dataclass(slots=True)
class _PhiBuilder:
    block: int
    register: int
    result: SSAValue | None
    operands: dict[int, SSAValue]


def _multi_value_producer(instruction: DecodedInstruction) -> SSAMultiValue | None:
    if instruction.name in {"CALL", "CALLFB"} and instruction.c == 0:
        return SSAMultiValue(
            origin_pc=instruction.pc,
            base_register=instruction.a,
            kind="call",
        )
    if instruction.name == "GETVARARGS" and instruction.b == 0:
        return SSAMultiValue(
            origin_pc=instruction.pc,
            base_register=instruction.a,
            kind="varargs",
        )
    return None


def _multi_value_consumer(
    instruction: DecodedInstruction,
) -> tuple[SSAMultiUseKind, int] | None:
    if instruction.name in {"CALL", "CALLFB"} and instruction.b == 0:
        return "arguments", instruction.a + 1
    if instruction.name == "RETURN" and instruction.b == 0:
        return "return", instruction.a
    semantics = setlist_semantics(instruction)
    if semantics is not None and semantics.is_open:
        return "setlist", semantics.first_value_register
    return None


def _analyze_multi_values(analysis: ControlFlowAnalysis) -> SSAMultiValuePlan:
    values = tuple(
        producer
        for block in analysis.blocks
        if block.start_pc in analysis.reachable
        for instruction in block.instructions
        if (producer := _multi_value_producer(instruction)) is not None
    )
    producer_by_pc = {value.origin_pc: value for value in values}
    block_by_start = analysis.block_by_start
    reachable_blocks = tuple(
        block for block in analysis.blocks if block.start_pc in analysis.reachable
    )

    # FASTCALL is a guarded fast path for the fallback CALL at the end of its other
    # successor.  When that CALL is open, both edges produce the same dynamic tuple
    # at the join even though only the fallback edge contains a CALL instruction.
    # Record that opcode-defined edge value explicitly; this is a CFG relation, not
    # replay of the physical result registers.
    fastcall_edge_values: dict[tuple[int, int], SSAMultiValue] = {}
    for block in reachable_blocks:
        if not block.instructions:
            continue
        fastcall = block.instructions[-1]
        if not fastcall.name.startswith("FASTCALL"):
            continue
        join = get_jump_target(fastcall)
        if join is None or join not in block.successors or len(block.successors) != 2:
            continue
        fallback_starts = tuple(successor for successor in block.successors if successor != join)
        if len(fallback_starts) != 1:
            continue
        fallback = block_by_start.get(fallback_starts[0])
        if (
            fallback is None
            or fallback.successors != frozenset({join})
            or not fallback.instructions
        ):
            continue
        fallback_call = fallback.instructions[-1]
        producer = producer_by_pc.get(fallback_call.pc)
        if producer is None or fallback_call.name not in {"CALL", "CALLFB"}:
            continue
        fastcall_edge_values[(block.start_pc, join)] = producer

    # An open Luau tuple is a semantic stack-top value.  It can survive an ordinary
    # basic-block boundary (notably the fallback edge created by FASTCALL), but only
    # while every incoming path carries the exact same producer and no instruction
    # overwrites a register in its open tail.  This is a forward must-analysis: joins
    # with different or unknown producers deliberately collapse to no value.
    incoming: dict[int, SSAMultiValue | None] = {
        block.start_pc: None for block in reachable_blocks
    }
    outgoing: dict[int, SSAMultiValue | None] = {
        block.start_pc: None for block in reachable_blocks
    }
    uses_by_pc: dict[int, SSAMultiUse] = {}

    def transfer(
        block_start: int,
        pending: SSAMultiValue | None,
    ) -> SSAMultiValue | None:
        block = block_by_start[block_start]
        for instruction in block.instructions:
            consumer = _multi_value_consumer(instruction)
            consumed = False
            if consumer is not None and pending is not None:
                kind, base_register = consumer
                if pending.base_register >= base_register:
                    uses_by_pc[instruction.pc] = SSAMultiUse(
                        consumer_pc=instruction.pc,
                        base_register=base_register,
                        kind=kind,
                        value=pending,
                        prefix_registers=tuple(
                            range(base_register, pending.base_register)
                        ),
                    )
                    consumed = True

            producer = producer_by_pc.get(instruction.pc)
            if producer is not None:
                pending = producer
            elif consumed:
                pending = None
            elif pending is not None:
                definitions = analysis.register_accesses[instruction.pc].definitions
                if any(register >= pending.base_register for register in definitions):
                    pending = None
        return pending

    changed = True
    while changed:
        changed = False
        for block in reachable_blocks:
            predecessors = tuple(
                predecessor
                for predecessor in block.predecessors
                if predecessor in analysis.reachable
            )
            if not predecessors:
                next_incoming: SSAMultiValue | None = None
            else:
                predecessor_values = tuple(
                    fastcall_edge_values.get((pc, block.start_pc), outgoing[pc])
                    for pc in predecessors
                )
                first = predecessor_values[0]
                next_incoming = (
                    first
                    if all(value == first for value in predecessor_values[1:])
                    else None
                )
            if incoming[block.start_pc] != next_incoming:
                incoming[block.start_pc] = next_incoming
                changed = True
            next_outgoing = transfer(block.start_pc, next_incoming)
            if outgoing[block.start_pc] != next_outgoing:
                outgoing[block.start_pc] = next_outgoing
                changed = True

    # Re-run transfer once in program order so the final immutable use map is not an
    # artifact of work-list iteration order.
    uses_by_pc.clear()
    for block in reachable_blocks:
        block_incoming = incoming[block.start_pc]
        transfer(block.start_pc, block_incoming)
    uses = tuple(uses_by_pc[pc] for pc in sorted(uses_by_pc))

    return SSAMultiValuePlan(
        values=values,
        uses=uses,
        by_origin_pc=MappingProxyType({value.origin_pc: value for value in values}),
        by_consumer_pc=MappingProxyType({use.consumer_pc: use for use in uses}),
    )


def is_fastcall_fallback_bridge(
    program: SSAProgram,
    producer_pc: int,
    consumer_pc: int,
) -> bool:
    """Whether an open fallback CALL and its consumer meet at a FASTCALL join."""

    fastcall_pc = fastcall_for_fallback_call(program, producer_pc)
    if fastcall_pc is None:
        return False
    fastcall = program.instructions[fastcall_pc].instruction
    consumer_block = program.analysis.block_for_pc.get(consumer_pc)
    return consumer_block is not None and get_jump_target(fastcall) == consumer_block


def fastcall_for_fallback_call(program: SSAProgram, producer_pc: int) -> int | None:
    """Return the opcode-verified FASTCALL paired with a fallback CALL."""

    producer_block = program.analysis.block_for_pc.get(producer_pc)
    if producer_block is None:
        return None
    fallback = program.analysis.block_by_start.get(producer_block)
    if (
        fallback is None
        or len(fallback.successors) != 1
        or not fallback.instructions
        or fallback.instructions[-1].pc != producer_pc
    ):
        return None
    join = next(iter(fallback.successors))
    matches = tuple(
        block.instructions[-1].pc
        for block in program.analysis.blocks
        if block.start_pc in program.analysis.reachable
        and block.instructions
        and block.instructions[-1].name.startswith("FASTCALL")
        and get_jump_target(block.instructions[-1]) == join
        and block.successors == frozenset({producer_block, join})
    )
    return matches[0] if len(matches) == 1 else None


class _SSABuilder:
    def __init__(self, analysis: ControlFlowAnalysis) -> None:
        self.analysis = analysis
        self.multi_values = _analyze_multi_values(analysis)
        self.counters: dict[int, int] = defaultdict(int)
        self.stacks: dict[int, list[SSAValue]] = defaultdict(list)
        self.entry_values: dict[int, SSAValue] = {}
        self.instructions: dict[int, SSAInstruction] = {}
        self.definitions: dict[tuple[int, int], SSAValue] = {}
        self.use_counts: dict[SSAValue, int] = defaultdict(int)
        phi_keys = {(phi.block, phi.register) for phi in analysis.phi_nodes}

        # Open SETLIST prefix registers are discovered only after the CFG open-tuple
        # analysis, so ordinary liveness cannot request their FASTCALL result phis.
        # Add exactly those opcode-defined join phis whose fallback CALL writes a
        # consumed prefix and whose join dominates that consumer.
        for use in self.multi_values.uses:
            consumer_block = analysis.block_for_pc.get(use.consumer_pc)
            if consumer_block is None:
                continue
            prefix_registers = frozenset(use.prefix_registers)
            for fallback in analysis.blocks:
                if len(fallback.successors) != 1 or not fallback.instructions:
                    continue
                call = fallback.instructions[-1]
                if (
                    call.name not in {"CALL", "CALLFB"}
                    or call.c != 2
                    or call.a not in prefix_registers
                ):
                    continue
                join = next(iter(fallback.successors))
                if not analysis.dominates(join, consumer_block):
                    continue
                fastcall_blocks = tuple(
                    block
                    for block in analysis.blocks
                    if block.instructions
                    and block.instructions[-1].name.startswith("FASTCALL")
                    and get_jump_target(block.instructions[-1]) == join
                    and block.successors == frozenset({fallback.start_pc, join})
                )
                if len(fastcall_blocks) == 1:
                    phi_keys.add((join, call.a))

        self.phis: dict[tuple[int, int], _PhiBuilder] = {
            (block, register): _PhiBuilder(
                block=block,
                register=register,
                result=None,
                operands={},
            )
            for block, register in sorted(phi_keys)
        }
        self.phis_by_block: dict[int, list[_PhiBuilder]] = defaultdict(list)
        for phi in self.phis.values():
            self.phis_by_block[phi.block].append(phi)
        for phi_builders in self.phis_by_block.values():
            phi_builders.sort(key=lambda item: item.register)

        self.children: dict[int, list[int]] = defaultdict(list)
        for block, parent in analysis.immediate_dominators.items():
            if parent is not None:
                self.children[parent].append(block)
        order = {block: index for index, block in enumerate(reverse_postorder(analysis))}
        for child_blocks in self.children.values():
            child_blocks.sort(key=lambda block: order.get(block, len(order)))

    def _entry_value(self, register: int) -> SSAValue:
        value = self.entry_values.get(register)
        if value is None:
            value = SSAValue(
                register=register,
                version=0,
                origin_pc=None,
                kind="entry",
            )
            self.entry_values[register] = value
        return value

    def _current(self, register: int) -> SSAValue:
        stack = self.stacks[register]
        if not stack:
            stack.append(self._entry_value(register))
        return stack[-1]

    def _new_value(
        self,
        register: int,
        origin_pc: int,
        kind: Literal["instruction", "phi"],
    ) -> SSAValue:
        self.counters[register] += 1
        value = SSAValue(
            register=register,
            version=self.counters[register],
            origin_pc=origin_pc,
            kind=kind,
        )
        self.stacks[register].append(value)
        return value

    def _record_phi_operands(self, predecessor: int, successor: int) -> None:
        for phi in self.phis_by_block.get(successor, []):
            value = self._current(phi.register)
            previous = phi.operands.get(predecessor)
            if previous is not None:
                self.use_counts[previous] -= 1
            phi.operands[predecessor] = value
            self.use_counts[value] += 1

    def _visit(self, block_start: int) -> None:
        block = self.analysis.block_by_start[block_start]
        pushed: list[int] = []

        for phi in self.phis_by_block.get(block_start, []):
            result = self._new_value(phi.register, block_start, "phi")
            phi.result = result
            pushed.append(phi.register)

        for instruction in block.instructions:
            access = self.analysis.register_accesses[instruction.pc]
            multi_use = self.multi_values.use_at(instruction.pc)
            use_registers = access.uses | (
                frozenset(multi_use.prefix_registers)
                if multi_use is not None
                else frozenset()
            )
            uses = tuple(
                SSAUse(register=register, value=self._current(register))
                for register in sorted(use_registers)
            )
            for use in uses:
                self.use_counts[use.value] += 1

            definitions: list[SSAValue] = []
            for register in sorted(access.definitions):
                value = self._new_value(register, instruction.pc, "instruction")
                definitions.append(value)
                pushed.append(register)
                self.definitions[(instruction.pc, register)] = value

            self.instructions[instruction.pc] = SSAInstruction(
                instruction=instruction,
                uses=uses,
                definitions=tuple(definitions),
            )

        for successor in sorted(block.successors):
            if successor in self.analysis.reachable:
                self._record_phi_operands(block_start, successor)

        for child in self.children.get(block_start, []):
            self._visit(child)

        for register in reversed(pushed):
            self.stacks[register].pop()

    def build(self) -> SSAProgram:
        if self.analysis.reachable:
            self._visit(self.analysis.entry)

        frozen_phis: list[SSAPhi] = []
        for key in sorted(self.phis):
            builder = self.phis[key]
            if builder.result is None:
                continue
            frozen_phis.append(
                SSAPhi(
                    block=builder.block,
                    register=builder.register,
                    result=builder.result,
                    operands=MappingProxyType(dict(sorted(builder.operands.items()))),
                )
            )

        return SSAProgram(
            analysis=self.analysis,
            instructions=MappingProxyType(dict(sorted(self.instructions.items()))),
            phis=tuple(frozen_phis),
            entry_values=MappingProxyType(dict(sorted(self.entry_values.items()))),
            use_counts=MappingProxyType(
                {
                    value: count
                    for value, count in sorted(
                        self.use_counts.items(),
                        key=lambda item: item[0],
                    )
                    if count > 0
                }
            ),
            definitions=MappingProxyType(dict(sorted(self.definitions.items()))),
            multi_values=self.multi_values,
        )


def build_ssa(
    instructions: Sequence[DecodedInstruction],
    code_size: int,
    *,
    analysis: ControlFlowAnalysis | None = None,
) -> SSAProgram:
    resolved_analysis = analysis or analyze_control_flow(tuple(instructions), code_size)
    return _SSABuilder(resolved_analysis).build()


def _multi_value_suffix(program: SSAProgram, pc: int) -> str:
    value = program.multi_value_at(pc)
    use = program.multi_use_at(pc)
    parts: list[str] = []
    if use is not None:
        prefix = ", ".join(f"R{register}" for register in use.prefix_registers)
        prefix_text = f" after [{prefix}]" if prefix else ""
        parts.append(f"MULTRET {use.kind} consumes {use.value.name}{prefix_text}")
    if value is not None:
        parts.append(
            f"{value.name}=MULTRET<{value.kind}> R{value.base_register}..top"
        )
    return " ; " + " ; ".join(parts) if parts else ""


def render_ssa(program: SSAProgram) -> str:
    phis_by_block: dict[int, list[SSAPhi]] = defaultdict(list)
    for phi in program.phis:
        phis_by_block[phi.block].append(phi)

    lines: list[str] = []
    for block in program.analysis.blocks:
        reachable = block.start_pc in program.analysis.reachable
        suffix = "" if reachable else " [unreachable]"
        lines.append(f"B{block.start_pc}{suffix}:")
        for phi in phis_by_block.get(block.start_pc, []):
            operands = ", ".join(
                f"B{predecessor}: {value.name}"
                for predecessor, value in phi.operands.items()
            )
            lines.append(f"  {phi.result.name} = phi({operands})")
        for instruction in block.instructions:
            ssa_instruction = program.instructions.get(instruction.pc)
            if ssa_instruction is None:
                lines.append(f"  {instruction.pc:04d} {instruction.name} [unreachable]")
                continue
            definitions = ", ".join(
                value.name for value in ssa_instruction.definitions
            )
            uses = ", ".join(
                f"R{use.register}={use.value.name}" for use in ssa_instruction.uses
            )
            assignment = f"{definitions} = " if definitions else ""
            operand_suffix = f" [{uses}]" if uses else ""
            multi_suffix = _multi_value_suffix(program, instruction.pc)
            lines.append(
                f"  {instruction.pc:04d} {assignment}{instruction.name}"
                f"{operand_suffix}{multi_suffix}"
            )
    return "\n".join(lines) + ("\n" if lines else "")
