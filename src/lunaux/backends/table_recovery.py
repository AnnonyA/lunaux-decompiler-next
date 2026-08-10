from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Final

from lunaux.backends.analysis import register_access
from lunaux.backends.ast import Expr, LiteralExpr, TableExpr, TableField, render_expression
from lunaux.backends.opcodes import DecodedInstruction, setlist_semantics
from lunaux.backends.ssa import SSAValue

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
