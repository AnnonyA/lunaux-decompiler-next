from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from lunaux.backends.analysis import register_access
from lunaux.backends.ast import Expr, LiteralExpr, TableExpr, TableField, render_expression
from lunaux.backends.bytecode import LuauProto
from lunaux.backends.callframe import CallFramePlan, CallResultShape
from lunaux.backends.opcodes import DecodedInstruction, setlist_semantics
from lunaux.backends.ssa import (
    SSAProgram,
    SSAUse,
    SSAValue,
    fastcall_for_fallback_call,
)

_TABLE_WRITE_OPS: Final[frozenset[str]] = frozenset(
    {"SETTABLE", "SETTABLEKS", "SETUDATAKS", "SETTABLEN", "SETLIST"}
)
_SAFE_GAP_OPS: Final[frozenset[str]] = frozenset(
    {
        "NOP",
        "COVERAGE",
        "LOADNIL",
        "LOADB",
        "LOADN",
        "LOADK",
        "LOADKX",
        "MOVE",
        "GETGLOBAL",
        "GETIMPORT",
        "GETUPVAL",
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
        "NEWCLOSURE",
        "DUPCLOSURE",
        "CAPTURE",
    }
)

TableIdentity = tuple[str, str | int]


@dataclass(frozen=True, slots=True)
class TableCallOwnership:
    call_pc: int
    consumer_pc: int
    owner_value: SSAValue
    result_value: SSAValue | None
    result_shape: CallResultShape
    protected_values: frozenset[SSAValue]


@dataclass(frozen=True, slots=True)
class TableBuildPlan:
    table_identity_by_value: Mapping[SSAValue, SSAValue]
    parent_by_table: Mapping[SSAValue, SSAValue]
    calls: Mapping[int, TableCallOwnership]
    fastcall_bridges: Mapping[int, TableCallOwnership]
    rejection_counts: Mapping[str, int]

    def table_identity(self, value: SSAValue | None) -> SSAValue | None:
        return self.table_identity_by_value.get(value) if value is not None else None

    def call_at(self, pc: int) -> TableCallOwnership | None:
        return self.calls.get(pc) or self.fastcall_bridges.get(pc)

    def is_in_transaction(
        self,
        value: SSAValue,
        protected_values: frozenset[SSAValue],
    ) -> bool:
        identity = self.table_identity(value)
        seen: set[SSAValue] = set()
        while identity is not None and identity not in seen:
            if identity in protected_values:
                return True
            seen.add(identity)
            identity = self.parent_by_table.get(identity)
        return False

    @classmethod
    def empty(cls) -> TableBuildPlan:
        return cls(
            table_identity_by_value=MappingProxyType({}),
            parent_by_table=MappingProxyType({}),
            calls=MappingProxyType({}),
            fastcall_bridges=MappingProxyType({}),
            rejection_counts=MappingProxyType({}),
        )


@dataclass(frozen=True, slots=True)
class TableEntry:
    key: Expr | None
    value: Expr
    name: str | None = None
    array_index: int | None = None
    dependencies: frozenset[SSAValue] = frozenset()

    @property
    def identity(self) -> TableIdentity:
        if self.name is not None:
            return ("name", self.name)
        if self.array_index is not None:
            return ("index", self.array_index)
        if self.key is None:
            return ("open", "tail")
        return ("expr", render_expression(self.key))


@dataclass(slots=True)
class PendingTableLiteral:
    value: SSAValue
    register: int
    definition_pc: int
    assignment_pc: int | None = None
    template_kind: str | None = None
    entries: list[TableEntry] = field(default_factory=list)
    open_tail: TableEntry | None = None
    dependencies: set[SSAValue] = field(default_factory=set)
    contained_values: set[SSAValue] = field(default_factory=set)
    _positions: dict[TableIdentity, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.contained_values.add(self.value)

    @property
    def emit_pc(self) -> int:
        return self.assignment_pc if self.assignment_pc is not None else self.definition_pc

    @property
    def dependency_registers(self) -> frozenset[int]:
        return frozenset(value.register for value in self.dependencies)

    def rebind(self, value: SSAValue, register: int, pc: int) -> None:
        previous = self.value
        self.value = value
        self.register = register
        self.assignment_pc = pc
        self.contained_values.discard(previous)
        self.contained_values.add(value)

    def can_adopt(self, child: PendingTableLiteral) -> bool:
        if child is self:
            return False
        if self.value in child.contained_values:
            return False
        return child.value not in self.contained_values

    def adopt(self, child: PendingTableLiteral) -> bool:
        if not self.can_adopt(child):
            return False
        self.dependencies.update(child.dependencies)
        self.contained_values.update(child.contained_values)
        return True

    def _store(self, entry: TableEntry) -> bool:
        if self.open_tail is not None:
            return False
        position = self._positions.get(entry.identity)
        if position is None:
            self._positions[entry.identity] = len(self.entries)
            self.entries.append(entry)
        else:
            self.entries[position] = entry
        self.dependencies.update(entry.dependencies)
        return True

    def add_named(
        self,
        key: str,
        value: Expr,
        dependencies: frozenset[SSAValue] = frozenset(),
    ) -> bool:
        return self._store(
            TableEntry(
                key=LiteralExpr(json.dumps(key, ensure_ascii=False)),
                value=value,
                name=key,
                dependencies=dependencies,
            )
        )

    def add_index(
        self,
        index: int,
        value: Expr,
        dependencies: frozenset[SSAValue] = frozenset(),
    ) -> bool:
        if index <= 0:
            return False
        return self._store(
            TableEntry(
                key=LiteralExpr(str(index)),
                value=value,
                array_index=index,
                dependencies=dependencies,
            )
        )

    def add_dynamic(
        self,
        key: Expr,
        value: Expr,
        dependencies: frozenset[SSAValue] = frozenset(),
    ) -> bool:
        if isinstance(key, LiteralExpr):
            try:
                decoded = json.loads(key.text)
            except (json.JSONDecodeError, TypeError, ValueError):
                decoded = None
            if isinstance(decoded, str):
                return self.add_named(decoded, value, dependencies)
            if isinstance(decoded, int) and not isinstance(decoded, bool) and decoded > 0:
                return self.add_index(decoded, value, dependencies)
            if isinstance(decoded, float) and decoded.is_integer() and decoded > 0:
                return self.add_index(int(decoded), value, dependencies)
        return self._store(
            TableEntry(
                key=key,
                value=value,
                dependencies=dependencies,
            )
        )

    def add_indices(
        self,
        entries: tuple[tuple[int, Expr, frozenset[SSAValue]], ...],
    ) -> bool:
        if self.open_tail is not None or any(index <= 0 for index, _value, _deps in entries):
            return False
        for index, value, dependencies in entries:
            if not self.add_index(index, value, dependencies):
                return False
        return True

    def can_add_setlist_range(self, start_index: int, count: int) -> bool:
        """Require SETLIST batches to extend the constructor's numeric prefix."""

        if self.open_tail is not None or start_index <= 0 or count < 0:
            return False
        numeric_indices = {
            entry.array_index for entry in self.entries if entry.array_index is not None
        }
        return numeric_indices == set(range(1, start_index))

    def add_setlist_entries(
        self,
        entries: tuple[tuple[int, Expr, frozenset[SSAValue]], ...],
    ) -> bool:
        if not entries:
            return True
        start_index = entries[0][0]
        if not self.can_add_setlist_range(start_index, len(entries)):
            return False
        if any(
            index != start_index + offset
            for offset, (index, _value, _deps) in enumerate(entries)
        ):
            return False
        return self.add_indices(entries)

    def can_add_open_tail(self, start_index: int) -> bool:
        if self.open_tail is not None or start_index <= 0:
            return False
        numeric_indices = {
            entry.array_index for entry in self.entries if entry.array_index is not None
        }
        return numeric_indices == set(range(1, start_index))

    def add_open_tail(
        self,
        start_index: int,
        value: Expr,
        dependencies: frozenset[SSAValue] = frozenset(),
    ) -> bool:
        if not self.can_add_open_tail(start_index):
            return False
        self.open_tail = TableEntry(
            key=None,
            value=value,
            array_index=start_index,
            dependencies=dependencies,
        )
        self.dependencies.update(dependencies)
        return True

    def add_open_setlist(
        self,
        start_index: int,
        fixed_entries: tuple[tuple[int, Expr, frozenset[SSAValue]], ...],
        tail: Expr,
        tail_dependencies: frozenset[SSAValue] = frozenset(),
    ) -> bool:
        if self.open_tail is not None:
            return False
        if any(
            index != start_index + offset
            for offset, (index, _value, _dependencies) in enumerate(fixed_entries)
        ):
            return False
        if not self.can_add_setlist_range(start_index, len(fixed_entries)):
            return False
        tail_index = start_index + len(fixed_entries)
        if not fixed_entries and not self.can_add_open_tail(tail_index):
            return False
        if fixed_entries and not self.add_setlist_entries(fixed_entries):
            return False
        return self.add_open_tail(tail_index, tail, tail_dependencies)

    def expression(self) -> TableExpr:
        fields: list[TableField] = []
        next_array_index = 1
        for entry in self.entries:
            if entry.name is not None:
                fields.append(
                    TableField(
                        key=entry.key,
                        value=entry.value,
                        name=entry.name,
                    )
                )
                continue
            if entry.array_index == next_array_index:
                fields.append(TableField(key=None, value=entry.value))
                next_array_index += 1
                continue
            fields.append(TableField(key=entry.key, value=entry.value))
        if self.open_tail is not None:
            fields.append(TableField(key=None, value=self.open_tail.value))
        return TableExpr(tuple(fields))


def table_write_target_register(instruction: DecodedInstruction) -> int | None:
    if instruction.name in {"SETTABLE", "SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
        return instruction.b
    if instruction.name == "SETLIST":
        semantics = setlist_semantics(instruction)
        return semantics.table_register if semantics is not None else None
    return None


def table_write_source_registers(instruction: DecodedInstruction) -> frozenset[int]:
    if instruction.name == "SETTABLE":
        return frozenset({instruction.a, instruction.c})
    if instruction.name in {"SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
        return frozenset({instruction.a})
    if instruction.name == "SETLIST":
        semantics = setlist_semantics(instruction)
        if semantics is None:
            return frozenset()
        return frozenset(
            range(
                semantics.first_value_register,
                semantics.first_value_register + semantics.source_register_count,
            )
        )
    return frozenset()


def table_write_value_registers(instruction: DecodedInstruction) -> frozenset[int]:
    if instruction.name in {"SETTABLE", "SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
        return frozenset({instruction.a})
    if instruction.name == "SETLIST":
        semantics = setlist_semantics(instruction)
        if semantics is None:
            return frozenset()
        return frozenset(
            range(
                semantics.first_value_register,
                semantics.first_value_register + semantics.source_register_count,
            )
        )
    return frozenset()


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


def _table_identities(program: SSAProgram) -> dict[SSAValue, SSAValue]:
    identities: dict[SSAValue, SSAValue] = {}
    for pc in sorted(program.instructions):
        ssa_instruction = program.instructions[pc]
        instruction = ssa_instruction.instruction
        if instruction.name in {"NEWTABLE", "DUPTABLE"}:
            value = program.value_defined_at(pc, instruction.a)
            if value is not None:
                identities[value] = value
        elif instruction.name == "MOVE":
            source = program.value_at_use(pc, instruction.b)
            destination = program.value_defined_at(pc, instruction.a)
            identity = identities.get(source) if source is not None else None
            if identity is not None and destination is not None:
                identities[destination] = identity
    return identities


def _matching_uses(
    program: SSAProgram,
    values: frozenset[SSAValue],
) -> tuple[tuple[int, SSAUse], ...]:
    return tuple(
        (pc, use)
        for pc in sorted(program.instructions)
        for use in program.instructions[pc].uses
        if use.value in values
    )


def _table_parents(
    program: SSAProgram,
    identities: Mapping[SSAValue, SSAValue],
    rejections: Counter[str],
) -> dict[SSAValue, SSAValue]:
    aliases: dict[SSAValue, set[SSAValue]] = defaultdict(set)
    for value, identity in identities.items():
        aliases[identity].add(value)

    parents: dict[SSAValue, SSAValue] = {}
    for identity, values in aliases.items():
        external: list[tuple[int, SSAValue]] = []
        rejected = False
        for pc, use in _matching_uses(program, frozenset(values)):
            instruction = program.instructions[pc].instruction
            if instruction.name == "MOVE" and use.register == instruction.b:
                destination = program.value_defined_at(pc, instruction.a)
                if destination is not None and identities.get(destination) == identity:
                    continue

            target_register = table_write_target_register(instruction)
            if target_register is not None and target_register == use.register:
                target = program.value_at_use(pc, target_register)
                if target is not None and identities.get(target) == identity:
                    continue

            if use.register in table_write_value_registers(instruction):
                target = (
                    program.value_at_use(pc, target_register)
                    if target_register is not None
                    else None
                )
                parent = identities.get(target) if target is not None else None
                if parent is not None and parent != identity:
                    external.append((pc, parent))
                    continue

            rejected = True

        if rejected:
            rejections["table-escaped"] += 1
            continue
        if len(external) != 1:
            if external:
                rejections["multi-use-child"] += 1
            continue
        parents[identity] = external[0][1]
    return parents


def _protected_tables(
    owner: SSAValue,
    parents: Mapping[SSAValue, SSAValue],
) -> frozenset[SSAValue]:
    result: set[SSAValue] = set()
    current: SSAValue | None = owner
    while current is not None and current not in result:
        result.add(current)
        current = parents.get(current)
    return frozenset(result)


def _single_use(program: SSAProgram, value: SSAValue) -> tuple[int, SSAUse] | None:
    uses = _matching_uses(program, frozenset({value}))
    return uses[0] if len(uses) == 1 else None


def _call_consumer(
    program: SSAProgram,
    pc: int,
    shape: CallResultShape,
    result_value: SSAValue | None,
) -> tuple[int, SSAUse | None] | None:
    if shape == CallResultShape.FIXED_ONE and result_value is not None:
        return _single_use(program, result_value)
    if shape != CallResultShape.OPEN:
        return None
    produced = program.multi_value_at(pc)
    if produced is None:
        return None
    matches = tuple(use for use in program.multi_values.uses if use.value == produced)
    if len(matches) != 1 or matches[0].kind != "setlist":
        return None
    return matches[0].consumer_pc, None


def _call_gap_is_structural(
    program: SSAProgram,
    call_pc: int,
    consumer_pc: int,
    candidate_consumers: Mapping[int, int],
) -> bool:
    for pc in sorted(program.instructions):
        if not call_pc < pc < consumer_pc:
            continue
        instruction = program.instructions[pc].instruction
        if is_safe_table_gap(instruction):
            continue
        if instruction.name in {"CALL", "CALLFB"} and candidate_consumers.get(pc) == consumer_pc:
            continue
        if instruction.name.startswith("FASTCALL") and candidate_consumers.get(pc) == consumer_pc:
            continue
        return False
    return True


def plan_table_builds(
    program: SSAProgram,
    proto: LuauProto,
    call_frames: CallFramePlan,
) -> TableBuildPlan:
    """Plan CALL ownership without treating physical registers as table identity.

    A call may stay inside a pending constructor only when its exact SSA result (or
    open SSA tuple) has one structural table-write consumer.  Parent protection is
    derived from single-owner table SSA uses, so unrelated pending tables still flush
    at the call barrier.
    """

    rejections: Counter[str] = Counter()
    identities = _table_identities(program)
    parents = _table_parents(program, identities, rejections)
    raw: dict[int, tuple[int, SSAValue, SSAValue | None, CallResultShape]] = {}

    for pc, frame in call_frames.frames.items():
        result_value = (
            program.value_defined_at(pc, frame.callee_register)
            if frame.result_shape in {CallResultShape.FIXED_ONE, CallResultShape.OPEN}
            else None
        )
        consumer_result = call_frames.fastcall_result_at(pc) or result_value
        consumer = _call_consumer(program, pc, frame.result_shape, consumer_result)
        if consumer is None:
            if frame.result_shape in {
                CallResultShape.FIXED_MANY,
                CallResultShape.OPEN,
            }:
                rejections["open-multret"] += 1
            elif frame.result_shape == CallResultShape.FIXED_ONE:
                rejections["not-single-use"] += 1
            continue
        consumer_pc, result_use = consumer
        ssa_consumer = program.instructions.get(consumer_pc)
        if ssa_consumer is None:
            rejections["non-table-consumer"] += 1
            continue
        instruction = ssa_consumer.instruction
        target_register = table_write_target_register(instruction)
        multi_use = program.multi_use_at(consumer_pc)
        is_open_prefix = (
            instruction.name == "SETLIST"
            and instruction.c == 0
            and result_use is not None
            and multi_use is not None
            and result_use.register in multi_use.prefix_registers
        )
        if (
            target_register is None
            or (
                result_use is not None
                and result_use.register not in table_write_value_registers(instruction)
                and not is_open_prefix
            )
        ):
            rejections["non-table-consumer"] += 1
            continue
        if frame.result_shape == CallResultShape.OPEN:
            semantics = setlist_semantics(instruction)
            if semantics is None or not semantics.is_open:
                rejections["open-multret"] += 1
                continue
        target = program.value_at_use(consumer_pc, target_register)
        owner = identities.get(target) if target is not None else None
        if owner is None:
            rejections["missing-table-owner"] += 1
            continue
        call_block = program.analysis.block_for_pc.get(pc)
        consumer_block = program.analysis.block_for_pc.get(consumer_pc)
        if call_block != consumer_block and fastcall_for_fallback_call(program, pc) is None:
            # A preceding fixed-one element can dominate a SETLIST that follows a
            # later FASTCALL diamond.  Its exact SSA value remains the prefix operand
            # on both paths; rejecting it solely because the later optimization split
            # the CFG makes ownership partial and drops the whole constructor batch.
            if (
                call_block is None
                or consumer_block is None
                or not program.analysis.dominates(call_block, consumer_block)
            ):
                rejections["cross-block"] += 1
                continue
        if result_value is not None and _debug_visible(proto, result_value):
            rejections["debug-binding"] += 1
            continue
        protected = _protected_tables(owner, parents)
        if any(identities.get(dependency) in protected for dependency in frame.dependencies):
            rejections["call-not-owned"] += 1
            continue
        raw[pc] = (consumer_pc, owner, consumer_result, frame.result_shape)

    candidate_consumers = {pc: item[0] for pc, item in raw.items()}
    for pc, item in raw.items():
        fastcall_pc = fastcall_for_fallback_call(program, pc)
        if fastcall_pc is not None:
            candidate_consumers[fastcall_pc] = item[0]
    calls: dict[int, TableCallOwnership] = {}
    for pc, (consumer_pc, owner, result_value, shape) in raw.items():
        if not _call_gap_is_structural(program, pc, consumer_pc, candidate_consumers):
            rejections["observable-order-conflict"] += 1
            continue
        calls[pc] = TableCallOwnership(
            call_pc=pc,
            consumer_pc=consumer_pc,
            owner_value=owner,
            result_value=result_value,
            result_shape=shape,
            protected_values=_protected_tables(owner, parents),
        )

    fastcall_bridges: dict[int, TableCallOwnership] = {}
    for call_pc, ownership in calls.items():
        fastcall_pc = fastcall_for_fallback_call(program, call_pc)
        if fastcall_pc is not None:
            fastcall_bridges[fastcall_pc] = ownership

    return TableBuildPlan(
        table_identity_by_value=MappingProxyType(dict(identities)),
        parent_by_table=MappingProxyType(dict(parents)),
        calls=MappingProxyType(dict(calls)),
        fastcall_bridges=MappingProxyType(dict(fastcall_bridges)),
        rejection_counts=MappingProxyType(dict(sorted(rejections.items()))),
    )


def is_table_write(instruction: DecodedInstruction) -> bool:
    return instruction.name in _TABLE_WRITE_OPS


def is_safe_table_gap(instruction: DecodedInstruction) -> bool:
    return instruction.name in _SAFE_GAP_OPS


def should_flush_tables_before(
    instruction: DecodedInstruction,
    pending_registers: frozenset[int],
    dependency_registers: frozenset[int] = frozenset(),
) -> bool:
    if not pending_registers:
        return False
    access = register_access(instruction)
    target = table_write_target_register(instruction)
    if access.definitions & (pending_registers | dependency_registers):
        return True
    pending_uses = access.uses & pending_registers
    if pending_uses:
        if target is None or target not in pending_registers:
            return True
        if pending_uses != frozenset({target}):
            return True
        return False
    if instruction.name in _TABLE_WRITE_OPS:
        return True
    return not is_safe_table_gap(instruction)
