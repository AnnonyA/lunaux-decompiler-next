from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from lunaux.backends.opcodes import get_jump_target
from lunaux.backends.ssa import SSAMultiUse, SSAPhi, SSAProgram, SSAValue


class CallResultShape(StrEnum):
    FIXED_ZERO = "fixed-zero"
    FIXED_ONE = "fixed-one"
    FIXED_MANY = "fixed-many"
    OPEN = "open"


@dataclass(frozen=True, slots=True)
class CallFrame:
    pc: int
    callee_register: int
    callee: SSAValue | None
    receiver: SSAValue | None
    argument_registers: tuple[int, ...]
    arguments: tuple[SSAValue | None, ...]
    open_argument: SSAMultiUse | None
    result_registers: tuple[int, ...]
    is_open_result: bool
    namecall_pc: int | None
    dependencies: frozenset[SSAValue]

    @property
    def result_base(self) -> int:
        return self.callee_register

    @property
    def result_count(self) -> int | None:
        return None if self.is_open_result else len(self.result_registers)

    @property
    def result_shape(self) -> CallResultShape:
        if self.is_open_result:
            return CallResultShape.OPEN
        count = len(self.result_registers)
        if count == 0:
            return CallResultShape.FIXED_ZERO
        if count == 1:
            return CallResultShape.FIXED_ONE
        return CallResultShape.FIXED_MANY

    @property
    def single_result_register(self) -> int | None:
        return (
            self.result_registers[0]
            if self.result_shape == CallResultShape.FIXED_ONE
            else None
        )


@dataclass(frozen=True, slots=True)
class CallFramePlan:
    frames: Mapping[int, CallFrame]
    fastcall_result_phis: Mapping[int, SSAValue] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def at(self, pc: int) -> CallFrame | None:
        return self.frames.get(pc)

    def fastcall_result_at(self, pc: int) -> SSAValue | None:
        return self.fastcall_result_phis.get(pc)


def plan_call_frames(program: SSAProgram) -> CallFramePlan:
    frames: dict[int, CallFrame] = {}
    ordered = sorted(program.instructions)
    pending_namecalls: dict[int, int] = {}
    current_block: int | None = None

    for pc in ordered:
        ssa_instruction = program.instructions[pc]
        instruction = ssa_instruction.instruction
        block = program.analysis.block_for_pc.get(pc)
        if block != current_block:
            pending_namecalls.clear()
            current_block = block
        if instruction.name not in {"CALL", "CALLFB"}:
            if instruction.name in {"NAMECALL", "NAMECALLUDATA"}:
                pending_namecalls[instruction.a] = pc
                continue
            defined_registers = {value.register for value in ssa_instruction.definitions}
            for base_register in tuple(pending_namecalls):
                if defined_registers & {base_register, base_register + 1}:
                    pending_namecalls.pop(base_register)
            continue

        namecall_pc = pending_namecalls.pop(instruction.a, None)
        receiver: SSAValue | None = None
        if namecall_pc is not None:
            namecall = program.instructions[namecall_pc].instruction
            receiver = program.value_at_use(namecall_pc, namecall.b)

        if instruction.b == 0:
            multi_use = program.multi_use_at(pc)
            argument_registers = multi_use.prefix_registers if multi_use is not None else ()
            if namecall_pc is not None:
                argument_registers = tuple(
                    register for register in argument_registers if register >= instruction.a + 2
                )
        else:
            multi_use = None
            first_argument = instruction.a + (2 if namecall_pc is not None else 1)
            argument_count = max(
                0,
                instruction.b - (2 if namecall_pc is not None else 1),
            )
            argument_registers = tuple(range(first_argument, first_argument + argument_count))

        arguments = tuple(program.value_at_use(pc, register) for register in argument_registers)
        callee = program.value_at_use(pc, instruction.a)
        result_registers = (
            ()
            if instruction.c in {0, 1}
            else tuple(range(instruction.a, instruction.a + instruction.c - 1))
        )
        dependencies = frozenset(
            value for value in (callee, receiver, *arguments) if value is not None
        )
        frames[pc] = CallFrame(
            pc=pc,
            callee_register=instruction.a,
            callee=callee,
            receiver=receiver,
            argument_registers=argument_registers,
            arguments=arguments,
            open_argument=multi_use,
            result_registers=result_registers,
            is_open_result=instruction.c == 0,
            namecall_pc=namecall_pc,
            dependencies=dependencies,
        )

    fastcall_result_phis: dict[int, SSAValue] = {}
    phis_by_block: dict[int, list[SSAPhi]] = {}
    for phi in program.phis:
        phis_by_block.setdefault(phi.block, []).append(phi)
    for pc, frame in frames.items():
        if frame.result_shape != CallResultShape.FIXED_ONE:
            continue
        call_block = program.analysis.block_for_pc.get(pc)
        if call_block is None:
            continue
        fallback = program.analysis.block_by_start.get(call_block)
        if fallback is None or len(fallback.successors) != 1:
            continue
        join = next(iter(fallback.successors))
        result = program.value_defined_at(pc, frame.callee_register)
        if result is None:
            continue
        matching_phis = [
            phi
            for phi in phis_by_block.get(join, [])
            if phi.register == frame.callee_register
            and phi.operands.get(call_block) == result
        ]
        if len(matching_phis) != 1:
            continue
        has_fast_path = any(
            instruction.instruction.name.startswith("FASTCALL")
            and get_jump_target(instruction.instruction) == join
            and program.analysis.block_by_start[
                program.analysis.block_for_pc[instruction.pc]
            ].successors
            == frozenset({call_block, join})
            for instruction in program.instructions.values()
            if instruction.pc < pc and instruction.pc in program.analysis.block_for_pc
        )
        if has_fast_path:
            fastcall_result_phis[pc] = matching_phis[0].result

    return CallFramePlan(
        MappingProxyType(frames),
        MappingProxyType(fastcall_result_phis),
    )


__all__ = [
    "CallFrame",
    "CallFramePlan",
    "CallResultShape",
    "plan_call_frames",
]
