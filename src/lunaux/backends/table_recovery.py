from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from lunaux.backends.analysis import register_access
from lunaux.backends.ast import Expr, LiteralExpr, TableExpr, TableField
from lunaux.backends.opcodes import DecodedInstruction
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
    }
)


@dataclass(frozen=True, slots=True)
class TableEntry:
    key: str | int
    value: Expr


@dataclass(slots=True)
class PendingTableLiteral:
    value: SSAValue
    register: int
    definition_pc: int
    entries: list[TableEntry] = field(default_factory=list)
    _keys: set[str | int] = field(default_factory=set)

    def add_named(self, key: str, value: Expr) -> bool:
        if key in self._keys:
            return False
        self._keys.add(key)
        self.entries.append(TableEntry(key=key, value=value))
        return True

    def add_index(self, index: int, value: Expr) -> bool:
        if index <= 0 or index in self._keys:
            return False
        self._keys.add(index)
        self.entries.append(TableEntry(key=index, value=value))
        return True

    def expression(self) -> TableExpr:
        fields: list[TableField] = []
        next_array_index = 1
        for entry in self.entries:
            if isinstance(entry.key, str):
                fields.append(TableField(key=None, value=entry.value, name=entry.key))
                continue
            if entry.key == next_array_index:
                fields.append(TableField(key=None, value=entry.value))
                next_array_index += 1
            else:
                fields.append(
                    TableField(
                        key=LiteralExpr(str(entry.key)),
                        value=entry.value,
                    )
                )
        return TableExpr(tuple(fields))


def table_write_target_register(instruction: DecodedInstruction) -> int | None:
    if instruction.name in {"SETTABLE", "SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
        return instruction.b
    if instruction.name == "SETLIST":
        return instruction.a
    return None


def is_table_write(instruction: DecodedInstruction) -> bool:
    return instruction.name in _TABLE_WRITE_OPS


def should_flush_tables_before(
    instruction: DecodedInstruction,
    pending_registers: frozenset[int],
) -> bool:
    if not pending_registers:
        return False
    access = register_access(instruction)
    target = table_write_target_register(instruction)
    pending_uses = access.uses & pending_registers
    if access.definitions & pending_registers:
        return True
    if pending_uses:
        if target is None or target not in pending_registers:
            return True
        if pending_uses != frozenset({target}):
            return True
        return False
    if instruction.name in _TABLE_WRITE_OPS:
        return True
    return instruction.name not in _SAFE_GAP_OPS
