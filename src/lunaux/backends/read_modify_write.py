from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from lunaux.backends.bytecode import LuauProto
from lunaux.backends.effects import is_transparent_instruction
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.scopes import ScopeTree
from lunaux.backends.ssa import SSAProgram, SSAValue


class StorageKind(StrEnum):
    LOCAL = "local"
    GLOBAL = "global"
    UPVALUE = "upvalue"
    FIELD = "field"
    INDEX = "index"


@dataclass(frozen=True, slots=True)
class StorageLocation:
    kind: StorageKind
    base: SSAValue | None = None
    key_value: SSAValue | None = None
    key_constant: object | None = None
    binding_name: str | None = None


@dataclass(frozen=True, slots=True)
class ReadModifyWrite:
    operation_pc: int
    write_pc: int
    read_pc: int | None
    operator: str
    location: StorageLocation
    old_value: SSAValue
    result_value: SSAValue
    rhs_register: int | None
    rhs_constant_index: int | None
    folded_lvalue_values: frozenset[SSAValue]


@dataclass(frozen=True, slots=True)
class ReadModifyWritePlan:
    by_operation: Mapping[int, ReadModifyWrite]
    by_write: Mapping[int, ReadModifyWrite]
    folded_values: frozenset[SSAValue]

    def at_operation(self, pc: int) -> ReadModifyWrite | None:
        return self.by_operation.get(pc)

    def at_write(self, pc: int) -> ReadModifyWrite | None:
        return self.by_write.get(pc)

    def should_capture(self, value: SSAValue | None) -> bool:
        return value is not None and value in self.folded_values


_BINARY_OPERATORS = {
    "ADD": "+",
    "SUB": "-",
    "MUL": "*",
    "DIV": "/",
    "MOD": "%",
    "POW": "^",
    "IDIV": "//",
    "ADDK": "+",
    "SUBK": "-",
    "MULK": "*",
    "DIVK": "/",
    "MODK": "%",
    "POWK": "^",
    "IDIVK": "//",
}
_REGISTER_BINARY = frozenset({"ADD", "SUB", "MUL", "DIV", "MOD", "POW", "IDIV"})
_CONSTANT_BINARY = frozenset({"ADDK", "SUBK", "MULK", "DIVK", "MODK", "POWK", "IDIVK"})
_READS = frozenset({"GETGLOBAL", "GETUPVAL", "GETTABLE", "GETTABLEKS", "GETUDATAKS", "GETTABLEN"})
_WRITES = frozenset({"SETGLOBAL", "SETUPVAL", "SETTABLE", "SETTABLEKS", "SETUDATAKS", "SETTABLEN"})
_LVALUE_FOLDABLE = frozenset(
    {
        "MOVE",
        "GETGLOBAL",
        "GETIMPORT",
        "GETUPVAL",
        "GETTABLE",
        "GETTABLEKS",
        "GETUDATAKS",
        "GETTABLEN",
        "CALL",
        "CALLFB",
    }
)


def _constant_identity(proto: LuauProto, index: int) -> object:
    if not 0 <= index < len(proto.constants):
        return ("invalid", index)
    constant = proto.constants[index]
    return (constant.kind, constant.value)


def _constant_key_index(instruction: DecodedInstruction) -> int:
    if instruction.name in {"GETUDATAKS", "SETUDATAKS"}:
        return (instruction.aux or 0) & 0xFFFF
    return instruction.aux if instruction.aux is not None else -1


def _read_location(
    program: SSAProgram,
    proto: LuauProto,
    instruction: DecodedInstruction,
) -> StorageLocation | None:
    pc = instruction.pc
    if instruction.name == "GETGLOBAL":
        index = instruction.aux if instruction.aux is not None else -1
        return StorageLocation(StorageKind.GLOBAL, key_constant=_constant_identity(proto, index))
    if instruction.name == "GETUPVAL":
        return StorageLocation(StorageKind.UPVALUE, key_constant=instruction.b)
    if instruction.name in {"GETTABLEKS", "GETUDATAKS"}:
        return StorageLocation(
            StorageKind.FIELD,
            base=program.value_at_use(pc, instruction.b),
            key_constant=_constant_identity(proto, _constant_key_index(instruction)),
        )
    if instruction.name == "GETTABLEN":
        return StorageLocation(
            StorageKind.INDEX,
            base=program.value_at_use(pc, instruction.b),
            key_constant=("integer", instruction.c + 1),
        )
    if instruction.name == "GETTABLE":
        return StorageLocation(
            StorageKind.INDEX,
            base=program.value_at_use(pc, instruction.b),
            key_value=program.value_at_use(pc, instruction.c),
        )
    return None


def _write_location(
    program: SSAProgram,
    proto: LuauProto,
    instruction: DecodedInstruction,
) -> StorageLocation | None:
    pc = instruction.pc
    if instruction.name == "SETGLOBAL":
        index = instruction.aux if instruction.aux is not None else -1
        return StorageLocation(StorageKind.GLOBAL, key_constant=_constant_identity(proto, index))
    if instruction.name == "SETUPVAL":
        return StorageLocation(StorageKind.UPVALUE, key_constant=instruction.b)
    if instruction.name in {"SETTABLEKS", "SETUDATAKS"}:
        return StorageLocation(
            StorageKind.FIELD,
            base=program.value_at_use(pc, instruction.b),
            key_constant=_constant_identity(proto, _constant_key_index(instruction)),
        )
    if instruction.name == "SETTABLEN":
        return StorageLocation(
            StorageKind.INDEX,
            base=program.value_at_use(pc, instruction.b),
            key_constant=("integer", instruction.c + 1),
        )
    if instruction.name == "SETTABLE":
        return StorageLocation(
            StorageKind.INDEX,
            base=program.value_at_use(pc, instruction.b),
            key_value=program.value_at_use(pc, instruction.c),
        )
    return None


def _debug_visible(proto: LuauProto, value: SSAValue) -> bool:
    pc = value.origin_pc
    if pc is None:
        return False
    return any(
        local.register == value.register
        and local.name is not None
        and local.start_pc <= pc < local.end_pc
        for local in proto.locals
    ) or any(
        local.register == value.register and local.start_pc <= pc < local.end_pc
        for local in proto.typed_locals
    )


def _use_sites(program: SSAProgram) -> Mapping[SSAValue, tuple[int, ...]]:
    sites: defaultdict[SSAValue, list[int]] = defaultdict(list)
    for pc, instruction in program.instructions.items():
        for use in instruction.uses:
            sites[use.value].append(pc)
    return MappingProxyType({value: tuple(sorted(site_list)) for value, site_list in sites.items()})


def _dataflow_pcs(
    program: SSAProgram,
    value: SSAValue,
    stop: frozenset[SSAValue],
    seen: frozenset[SSAValue] = frozenset(),
) -> frozenset[int]:
    if value in stop or value in seen or value.kind != "instruction" or value.origin_pc is None:
        return frozenset()
    instruction = program.instructions.get(value.origin_pc)
    if instruction is None:
        return frozenset()
    result = {value.origin_pc}
    next_seen = seen | frozenset({value})
    for use in instruction.uses:
        result.update(_dataflow_pcs(program, use.value, stop, next_seen))
    return frozenset(result)


def _lvalue_fold_graph(
    program: SSAProgram,
    proto: LuauProto,
    sites: Mapping[SSAValue, tuple[int, ...]],
    value: SSAValue | None,
    read_pc: int,
    write_pc: int,
    seen: frozenset[SSAValue] = frozenset(),
) -> tuple[SSAValue, ...]:
    if value is None or value in seen or value.kind != "instruction" or value.origin_pc is None:
        return ()
    if sites.get(value) != (read_pc, write_pc) or _debug_visible(proto, value):
        return ()
    definition = program.instructions.get(value.origin_pc)
    if definition is None or definition.instruction.name not in _LVALUE_FOLDABLE:
        return ()
    if definition.instruction.name in {"CALL", "CALLFB"} and definition.instruction.c != 2:
        return ()
    block = program.analysis.block_for_pc.get(value.origin_pc)
    if block is None or block != program.analysis.block_for_pc.get(read_pc):
        return ()
    if value.origin_pc >= read_pc:
        return ()

    nested: list[SSAValue] = []
    next_seen = seen | frozenset({value})
    for use in definition.uses:
        child_sites = sites.get(use.value, ())
        if child_sites == (value.origin_pc,):
            child = _lvalue_fold_graph(
                program,
                proto,
                sites,
                use.value,
                value.origin_pc,
                value.origin_pc,
                next_seen,
            )
            nested.extend(child)
    nested.append(value)
    allowed = {item.origin_pc for item in nested if item.origin_pc is not None}
    if any(
        value.origin_pc <= pc < read_pc
        and pc not in allowed
        and not is_transparent_instruction(ssa_instruction.instruction)
        for pc, ssa_instruction in program.instructions.items()
    ):
        return ()
    return tuple(nested)


def _rhs_shape(
    program: SSAProgram,
    instruction: DecodedInstruction,
) -> tuple[SSAValue | None, int | None, int | None] | None:
    if instruction.name in _REGISTER_BINARY:
        return (
            program.value_at_use(instruction.pc, instruction.b),
            instruction.c,
            None,
        )
    if instruction.name in _CONSTANT_BINARY:
        return (
            program.value_at_use(instruction.pc, instruction.b),
            None,
            instruction.c,
        )
    if instruction.name == "CONCAT" and instruction.c == instruction.b + 1:
        return (
            program.value_at_use(instruction.pc, instruction.b),
            instruction.c,
            None,
        )
    return None


def plan_read_modify_write(
    program: SSAProgram,
    proto: LuauProto,
    scope_tree: ScopeTree,
) -> ReadModifyWritePlan:
    sites = _use_sites(program)
    by_operation: dict[int, ReadModifyWrite] = {}
    by_write: dict[int, ReadModifyWrite] = {}
    folded: set[SSAValue] = set()

    for write_pc in sorted(program.instructions):
        write_ssa = program.instructions[write_pc]
        write = write_ssa.instruction
        if write.name not in _WRITES:
            continue
        result_value = program.value_at_use(write_pc, write.a)
        if (
            result_value is None
            or result_value.kind != "instruction"
            or result_value.origin_pc is None
            or program.uses_of(result_value) != 1
            or _debug_visible(proto, result_value)
        ):
            continue
        operation_ssa = program.instructions.get(result_value.origin_pc)
        if operation_ssa is None:
            continue
        operation = operation_ssa.instruction
        rhs_shape = _rhs_shape(program, operation)
        operator = _BINARY_OPERATORS.get(operation.name)
        if operation.name == "CONCAT":
            operator = ".."
        if rhs_shape is None or operator is None:
            continue
        old_value, rhs_register, rhs_constant = rhs_shape
        if old_value is None or old_value.kind != "instruction" or old_value.origin_pc is None:
            continue
        if program.uses_of(old_value) != 1 or _debug_visible(proto, old_value):
            continue
        read_ssa = program.instructions.get(old_value.origin_pc)
        if read_ssa is None or read_ssa.instruction.name not in _READS:
            continue
        read = read_ssa.instruction
        read_location = _read_location(program, proto, read)
        write_location = _write_location(program, proto, write)
        if read_location is None or read_location != write_location:
            continue
        block = program.analysis.block_for_pc.get(read.pc)
        if (
            block is None
            or block != program.analysis.block_for_pc.get(operation.pc)
            or block != program.analysis.block_for_pc.get(write.pc)
            or not read.pc < operation.pc < write.pc
        ):
            continue

        stop_values = frozenset(
            value
            for value in (
                old_value,
                read_location.base,
                read_location.key_value,
            )
            if value is not None
        )
        expression_pcs = set(
            _dataflow_pcs(
                program,
                result_value,
                stop_values,
            )
        )
        expression_pcs.add(read.pc)
        if any(
            read.pc < pc < write.pc
            and pc not in expression_pcs
            and not is_transparent_instruction(ssa_instruction.instruction)
            for pc, ssa_instruction in program.instructions.items()
        ):
            continue

        lvalue_values: list[SSAValue] = []
        lvalue_values.extend(
            _lvalue_fold_graph(
                program,
                proto,
                sites,
                read_location.base,
                read.pc,
                write.pc,
            )
        )
        lvalue_values.extend(
            _lvalue_fold_graph(
                program,
                proto,
                sites,
                read_location.key_value,
                read.pc,
                write.pc,
            )
        )
        item = ReadModifyWrite(
            operation_pc=operation.pc,
            write_pc=write.pc,
            read_pc=read.pc,
            operator=operator,
            location=read_location,
            old_value=old_value,
            result_value=result_value,
            rhs_register=rhs_register,
            rhs_constant_index=rhs_constant,
            folded_lvalue_values=frozenset(lvalue_values),
        )
        by_operation[operation.pc] = item
        by_write[write.pc] = item
        folded.update({old_value, result_value, *lvalue_values})

    # Local RMW is only recovered when a real debug binding proves lexical identity.
    for operation_pc in sorted(program.instructions):
        if operation_pc in by_operation:
            continue
        operation_ssa = program.instructions[operation_pc]
        operation = operation_ssa.instruction
        rhs_shape = _rhs_shape(program, operation)
        operator = _BINARY_OPERATORS.get(operation.name)
        if operation.name == "CONCAT":
            operator = ".."
        if rhs_shape is None or operator is None:
            continue
        old_value, rhs_register, rhs_constant = rhs_shape
        result_value = program.value_defined_at(operation_pc, operation.a)
        if old_value is None or result_value is None:
            continue
        destination = scope_tree.binding_for_register(operation.a, operation_pc)
        source = scope_tree.binding_for_register(old_value.register, operation_pc)
        if destination is None or source != destination or destination.start_pc >= operation_pc:
            continue
        item = ReadModifyWrite(
            operation_pc=operation_pc,
            write_pc=operation_pc,
            read_pc=None,
            operator=operator,
            location=StorageLocation(
                StorageKind.LOCAL,
                binding_name=destination.name,
            ),
            old_value=old_value,
            result_value=result_value,
            rhs_register=rhs_register,
            rhs_constant_index=rhs_constant,
            folded_lvalue_values=frozenset(),
        )
        by_operation[operation_pc] = item
        by_write[operation_pc] = item

    return ReadModifyWritePlan(
        by_operation=MappingProxyType(by_operation),
        by_write=MappingProxyType(by_write),
        folded_values=frozenset(folded),
    )


__all__ = [
    "ReadModifyWrite",
    "ReadModifyWritePlan",
    "StorageKind",
    "StorageLocation",
    "plan_read_modify_write",
]
