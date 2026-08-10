from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lunaux.backends.ssa import SSAMultiUse, SSAProgram, SSAValue


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


@dataclass(frozen=True, slots=True)
class CallFramePlan:
    frames: Mapping[int, CallFrame]

    def at(self, pc: int) -> CallFrame | None:
        return self.frames.get(pc)


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

    return CallFramePlan(MappingProxyType(frames))


__all__ = ["CallFrame", "CallFramePlan", "plan_call_frames"]
