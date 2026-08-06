from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"expected one match in {path}, found {count}: {old[:120]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: Path, start: str, end: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"start marker not found in {path}: {start!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"end marker not found in {path}: {end!r}")
    path.write_text(
        text[:start_index] + replacement + text[end_index:],
        encoding="utf-8",
    )


pyproject = ROOT / "pyproject.toml"
lifter = ROOT / "src/lunaux/backends/lifter.py"
if (
    'version = "0.13.0"' in pyproject.read_text(encoding="utf-8")
    and "pending_open_table_values" in lifter.read_text(encoding="utf-8")
):
    print("v0.13 table reconstruction is already applied")
    raise SystemExit(0)


table_recovery = ROOT / "src/lunaux/backends/table_recovery.py"
table_recovery.write_text(
    '''from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Final

from lunaux.backends.analysis import register_access
from lunaux.backends.ast import Expr, LiteralExpr, TableExpr, TableField, render_expression
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
        "DUPTABLE",
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
            if (
                isinstance(decoded, float)
                and decoded.is_integer()
                and decoded > 0
            ):
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

    def can_add_open_tail(self, start_index: int) -> bool:
        if self.open_tail is not None or start_index <= 0:
            return False
        numeric_indices = {
            entry.array_index
            for entry in self.entries
            if entry.array_index is not None
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
        return instruction.a
    return None


def table_write_source_registers(instruction: DecodedInstruction) -> frozenset[int]:
    if instruction.name == "SETTABLE":
        return frozenset({instruction.a, instruction.c})
    if instruction.name in {"SETTABLEKS", "SETUDATAKS", "SETTABLEN"}:
        return frozenset({instruction.a})
    if instruction.name == "SETLIST":
        count = instruction.c - 1 if instruction.c > 0 else 1
        return frozenset(range(instruction.b, instruction.b + count))
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
''',
    encoding="utf-8",
)

replace_once(
    lifter,
    '''from lunaux.backends.table_recovery import (
    PendingTableLiteral,
    is_table_write,
    should_flush_tables_before,
    table_write_target_register,
)
''',
    '''from lunaux.backends.table_recovery import (
    PendingTableLiteral,
    is_safe_table_gap,
    is_table_write,
    table_write_source_registers,
    table_write_target_register,
)
''',
)
replace_once(
    lifter,
    '''        self.pending_tables: dict[SSAValue, PendingTableLiteral] = {}
''',
    '''        self.pending_tables: dict[SSAValue, PendingTableLiteral] = {}
        self.pending_open_table_values: dict[
            int,
            tuple[Expr, frozenset[SSAValue], int],
        ] = {}
''',
)
replace_once(
    lifter,
    '''        self.previous_by_next_pc = {
            instruction.pc + instruction.size: instruction
            for instruction in self.instructions
        }
''',
    '''        self.previous_by_next_pc = {
            instruction.pc + instruction.size: instruction
            for instruction in self.instructions
        }
        self.next_instruction_by_pc = {
            instruction.pc: next_instruction
            for instruction, next_instruction in zip(
                self.instructions,
                self.instructions[1:],
                strict=False,
            )
        }
''',
)

new_table_methods = '''    def _flush_pending_table(self, pending: PendingTableLiteral) -> None:
        if self.pending_tables.get(pending.value) is not pending:
            return
        self.pending_tables.pop(pending.value, None)
        self._assign(
            pending.register,
            pending.expression(),
            pending.emit_pc,
        )

    def _flush_pending_tables(self) -> None:
        for pending in sorted(
            tuple(self.pending_tables.values()),
            key=lambda item: (item.definition_pc, item.emit_pc),
        ):
            self._flush_pending_table(pending)

    def _pending_table_for_register(
        self,
        pc: int,
        register: int,
    ) -> PendingTableLiteral | None:
        value = self.ssa.value_at_use(pc, register)
        return self.pending_tables.get(value) if value is not None else None

    def _pending_table_for_write(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        target = table_write_target_register(instruction)
        if target is None:
            return None
        return self._pending_table_for_register(instruction.pc, target)

    def _pending_table_for_move(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        if instruction.name != "MOVE":
            return None
        source_value = self.ssa.value_at_use(instruction.pc, instruction.b)
        destination_value = self.ssa.value_defined_at(instruction.pc, instruction.a)
        if source_value is None or destination_value is None:
            return None
        pending = self.pending_tables.get(source_value)
        if pending is None or self.ssa.uses_of(source_value) != 1:
            return None
        if instruction.a in pending.dependency_registers:
            return None
        return pending

    def _open_table_parent_for_producer(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        next_instruction = self.next_instruction_by_pc.get(instruction.pc)
        if (
            next_instruction is None
            or next_instruction.name != "SETLIST"
            or next_instruction.c != 0
            or next_instruction.b != instruction.a
        ):
            return None
        pending = self._pending_table_for_write(next_instruction)
        if pending is None:
            return None
        access = self.analysis.register_accesses[instruction.pc]
        if pending.register in access.uses:
            return None
        start_index = (next_instruction.aux or 0) + 1
        return pending if pending.can_add_open_tail(start_index) else None

    def _flush_tables_before(self, instruction: DecodedInstruction) -> None:
        if not self.options.reconstruct_table_literals or not self.pending_tables:
            return
        access = self.analysis.register_accesses[instruction.pc]
        target_pending = (
            self._pending_table_for_write(instruction)
            if is_table_write(instruction)
            else None
        )
        transfer_pending = self._pending_table_for_move(instruction)
        open_parent = (
            self._open_table_parent_for_producer(instruction)
            if instruction.name in {"CALL", "CALLFB", "GETVARARGS"}
            else None
        )
        write_sources = (
            table_write_source_registers(instruction)
            if target_pending is not None
            else frozenset()
        )

        for pending in sorted(
            tuple(self.pending_tables.values()),
            key=lambda item: (item.definition_pc, item.emit_pc),
        ):
            if pending is transfer_pending:
                continue
            if pending is target_pending:
                continue
            if pending is open_parent:
                continue
            if target_pending is not None and pending.register in write_sources:
                continue
            if access.definitions & (
                frozenset({pending.register}) | pending.dependency_registers
            ):
                self._flush_pending_table(pending)
                continue
            if pending.register in access.uses:
                self._flush_pending_table(pending)
                continue
            if is_table_write(instruction):
                if target_pending is None:
                    self._flush_pending_table(pending)
                continue
            if not is_safe_table_gap(instruction):
                self._flush_pending_table(pending)

    def _capture_register_expression(
        self,
        owner: PendingTableLiteral,
        register: int,
        pc: int,
        *,
        allow_nested: bool,
    ) -> tuple[Expr, frozenset[SSAValue]] | None:
        value = self.ssa.value_at_use(pc, register)
        child = self.pending_tables.get(value) if value is not None else None
        if child is owner:
            return None
        if child is not None:
            if (
                allow_nested
                and value is not None
                and self.ssa.uses_of(value) == 1
                and owner.can_adopt(child)
            ):
                self.pending_tables.pop(child.value, None)
                expression = child.expression()
                if not owner.adopt(child):
                    return None
                return expression, frozenset()
            self._flush_pending_table(child)
        expression = self._ref_expr(register, pc)
        dependencies = frozenset({value}) if value is not None else frozenset()
        return expression, dependencies

    def _record_table_write(self, instruction: DecodedInstruction) -> bool:
        pending = self._pending_table_for_write(instruction)
        if pending is None:
            return False
        pc = instruction.pc
        target = table_write_target_register(instruction)
        source_registers = table_write_source_registers(instruction)
        if target is not None and target in source_registers:
            self._flush_pending_table(pending)
            return False

        success = False
        if instruction.name in {"SETTABLEKS", "SETUDATAKS"}:
            captured = self._capture_register_expression(
                pending,
                instruction.a,
                pc,
                allow_nested=True,
            )
            if captured is not None:
                value, dependencies = captured
                success = pending.add_named(
                    self._table_key(instruction),
                    value,
                    dependencies,
                )
        elif instruction.name == "SETTABLEN":
            captured = self._capture_register_expression(
                pending,
                instruction.a,
                pc,
                allow_nested=True,
            )
            if captured is not None:
                value, dependencies = captured
                success = pending.add_index(
                    instruction.c + 1,
                    value,
                    dependencies,
                )
        elif instruction.name == "SETTABLE":
            captured_key = self._capture_register_expression(
                pending,
                instruction.c,
                pc,
                allow_nested=False,
            )
            captured_value = self._capture_register_expression(
                pending,
                instruction.a,
                pc,
                allow_nested=True,
            )
            if captured_key is not None and captured_value is not None:
                key, key_dependencies = captured_key
                value, value_dependencies = captured_value
                success = pending.add_dynamic(
                    key,
                    value,
                    key_dependencies | value_dependencies,
                )
        elif instruction.name == "SETLIST" and instruction.c > 0:
            count = instruction.c - 1
            start_index = (instruction.aux or 0) + 1
            entries: list[tuple[int, Expr, frozenset[SSAValue]]] = []
            for index in range(count):
                captured = self._capture_register_expression(
                    pending,
                    instruction.b + index,
                    pc,
                    allow_nested=True,
                )
                if captured is None:
                    break
                value, dependencies = captured
                entries.append((start_index + index, value, dependencies))
            if len(entries) == count:
                success = pending.add_indices(tuple(entries))
        elif instruction.name == "SETLIST" and instruction.c == 0:
            captured = self.pending_open_table_values.pop(instruction.b, None)
            if captured is not None and captured[2] == pc:
                value, dependencies, _consumer_pc = captured
                start_index = (instruction.aux or 0) + 1
                success = pending.add_open_tail(
                    start_index,
                    value,
                    dependencies,
                )
                if success:
                    self._flush_pending_table(pending)
                    return True

        if success:
            return True
        self._flush_pending_table(pending)
        return False

    def _transfer_pending_table(self, instruction: DecodedInstruction) -> bool:
        pending = self._pending_table_for_move(instruction)
        if pending is None:
            return False
        destination = self.ssa.value_defined_at(instruction.pc, instruction.a)
        if destination is None:
            return False
        self.pending_tables.pop(pending.value, None)
        pending.rebind(destination, instruction.a, instruction.pc)
        self.pending_tables[destination] = pending
        self.register_names.setdefault(instruction.a, f"v{instruction.a}")
        return True

    def _start_pending_table(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        value = self.ssa.value_defined_at(instruction.pc, instruction.a)
        if value is None:
            return None
        template_kind: str | None = None
        pending = PendingTableLiteral(
            value=value,
            register=instruction.a,
            definition_pc=instruction.pc,
        )
        if instruction.name == "DUPTABLE":
            constant = _constant(self.proto, instruction.d)
            if constant is None or constant.kind not in {"table", "table_with_constants"}:
                return None
            template_kind = constant.kind
            pending.template_kind = template_kind
            if constant.kind == "table_with_constants" and isinstance(
                constant.value,
                tuple,
            ):
                pairs = cast(tuple[tuple[int, int], ...], constant.value)
                for key_index, value_index in pairs:
                    if value_index < 0:
                        continue
                    key = source_expr(_constant_expr(self.proto, key_index))
                    item = source_expr(_constant_expr(self.proto, value_index))
                    if not pending.add_dynamic(key, item):
                        return None
        self.pending_tables[value] = pending
        self.register_names.setdefault(instruction.a, f"v{instruction.a}")
        return pending

    def _capture_open_table_value(
        self,
        instruction: DecodedInstruction,
        expression: Expr,
    ) -> bool:
        parent = self._open_table_parent_for_producer(instruction)
        next_instruction = self.next_instruction_by_pc.get(instruction.pc)
        if parent is None or next_instruction is None:
            return False
        dependencies = frozenset(
            value
            for register in self.analysis.register_accesses[instruction.pc].uses
            if (value := self.ssa.value_at_use(instruction.pc, register)) is not None
        )
        self.pending_open_table_values[instruction.a] = (
            expression,
            dependencies,
            next_instruction.pc,
        )
        return True

'''
replace_between(
    lifter,
    "    def _flush_pending_table(self, pending: PendingTableLiteral) -> None:\n",
    "    def _close_blocks(self, pc: int) -> None:\n",
    new_table_methods,
)

replace_once(
    lifter,
    '''        elif name == "MOVE":
            self._assign(instruction.a, self._ref_expr(instruction.b, pc), pc)
''',
    '''        elif name == "MOVE":
            if (
                self.options.reconstruct_table_literals
                and self._transfer_pending_table(instruction)
            ):
                return
            self._assign(instruction.a, self._ref_expr(instruction.b, pc), pc)
''',
)
replace_once(
    lifter,
    '''        elif name == "NEWTABLE":
            value = self.ssa.value_defined_at(pc, instruction.a)
            if self.options.reconstruct_table_literals and value is not None:
                self.pending_tables[value] = PendingTableLiteral(
                    value=value,
                    register=instruction.a,
                    definition_pc=pc,
                )
                self.register_names.setdefault(instruction.a, f"v{instruction.a}")
            else:
                self._assign(instruction.a, TableExpr(), pc)
        elif name == "DUPTABLE":
            self._assign(instruction.a, _constant_expr(self.proto, instruction.d), pc)
''',
    '''        elif name in {"NEWTABLE", "DUPTABLE"}:
            if (
                self.options.reconstruct_table_literals
                and self._start_pending_table(instruction) is not None
            ):
                return
            if name == "DUPTABLE":
                self._assign(
                    instruction.a,
                    _constant_expr(self.proto, instruction.d),
                    pc,
                )
            else:
                self._assign(instruction.a, TableExpr(), pc)
''',
)
replace_once(
    lifter,
    '''            elif instruction.c == 0:
                self._assign(
                    instruction.a,
                    RawExpr(
                        render_expression(expression)
                        + " --[[ multiple returns ]]"
                    ),
                    pc,
                )
''',
    '''            elif instruction.c == 0:
                if (
                    self.options.reconstruct_table_literals
                    and self._capture_open_table_value(instruction, expression)
                ):
                    return
                self._assign(
                    instruction.a,
                    RawExpr(
                        render_expression(expression)
                        + " --[[ multiple returns ]]"
                    ),
                    pc,
                )
''',
)
replace_once(
    lifter,
    '''        elif name == "GETVARARGS":
            if instruction.b <= 2:
                self._assign(instruction.a, "...", pc)
            else:
                registers = list(
                    range(instruction.a, instruction.a + instruction.b - 1)
                )
                self._assign_many(registers, "...", pc)
''',
    '''        elif name == "GETVARARGS":
            if (
                instruction.b == 0
                and self.options.reconstruct_table_literals
                and self._capture_open_table_value(instruction, source_expr("..."))
            ):
                return
            if instruction.b <= 2:
                self._assign(instruction.a, "...", pc)
            else:
                registers = list(
                    range(instruction.a, instruction.a + instruction.b - 1)
                )
                self._assign_many(registers, "...", pc)
''',
)

replace_once(pyproject, 'version = "0.12.0"', 'version = "0.13.0"')
replace_once(
    ROOT / "src/lunaux/__init__.py",
    '__version__ = "0.12.0"',
    '__version__ = "0.13.0"',
)

(ROOT / "tests/test_table_recovery_v013.py").write_text(
    '''from __future__ import annotations

from lunaux.backends.ast import CallExpr, LiteralExpr, NameExpr, render_expression
from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.ssa import SSAValue
from lunaux.backends.table_recovery import PendingTableLiteral, should_flush_tables_before


def _instruction(
    pc: int,
    name: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
) -> DecodedInstruction:
    opcode = opcode_names().index(name)
    return DecodedInstruction(
        pc=pc,
        word=opcode,
        opcode=opcode,
        name=name,
        a=a,
        b=b,
        c=c,
        d=0,
        e=0,
        aux=None,
    )


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    opcode = opcode_names().index(name)
    return opcode | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, *, a: int = 0, d: int = 0) -> int:
    opcode = opcode_names().index(name)
    return opcode | (a << 8) | ((d & 0xFFFF) << 16)


def _module(
    code: tuple[int, ...],
    constants: tuple[LuauConstant, ...] = (),
    *,
    stack: int = 8,
    vararg: bool = False,
) -> LuauBytecodeModule:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=stack,
        num_params=0,
        num_upvalues=0,
        is_vararg=vararg,
        flags=0,
        type_info=b"",
        code=code,
        constants=constants,
        child_proto_ids=(),
        line_defined=1,
        debug_name="main",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    return LuauBytecodeModule(
        version=13,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def test_dynamic_keys_overwrite_and_open_tail() -> None:
    value = SSAValue(register=0, version=1, origin_pc=0, kind="instruction")
    pending = PendingTableLiteral(value=value, register=0, definition_pc=0)

    assert pending.add_dynamic(NameExpr("key"), LiteralExpr("1"))
    assert pending.add_dynamic(NameExpr("key"), LiteralExpr("2"))
    assert pending.add_index(1, LiteralExpr('"head"'))
    assert pending.add_open_tail(2, CallExpr(NameExpr("collect"), ()))
    assert not pending.add_named("late", LiteralExpr("3"))

    assert render_expression(pending.expression()) == (
        '{[key] = 2, "head", collect()}'
    )


def test_dependency_redefinition_forces_materialization() -> None:
    pending = frozenset({0})
    dependencies = frozenset({2})

    assert should_flush_tables_before(
        _instruction(1, "LOADN", a=2),
        pending,
        dependencies,
    )
    assert not should_flush_tables_before(
        _instruction(2, "LOADN", a=3),
        pending,
        dependencies,
    )


def test_decompiles_nested_dynamic_and_fixed_list_tables() -> None:
    constants = (
        LuauConstant("string", "Value", 3),
        LuauConstant("string", "Child", 3),
        LuauConstant("string", "dynamic-key", 3),
    )
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("NEWTABLE", a=1),
        0,
        _ad("LOADN", a=2, d=7),
        _abc("SETTABLEKS", a=2, b=1),
        0,
        _abc("SETTABLEKS", a=1, b=0),
        1,
        _ad("LOADK", a=3, d=2),
        _ad("LOADN", a=4, d=9),
        _abc("SETTABLE", a=4, b=0, c=3),
        _abc("NEWTABLE", a=5),
        0,
        _ad("LOADN", a=6, d=11),
        _abc("SETLIST", a=5, b=0, c=1),
        0,
        _abc("SETLIST", a=0, b=5, c=2),
        0,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "nested.luau")

    assert "Child = {Value = 7}" in output
    assert '["dynamic-key"] = 9' in output
    assert "11" in output
    assert ".Child =" not in output
    assert "[\"dynamic-key\"] = 9" in output


def test_decompiles_duptable_template_and_deterministic_overwrite() -> None:
    constants = (
        LuauConstant("string", "Name", 3),
        LuauConstant("string", "Sword", 3),
        LuauConstant("table_with_constants", ((0, 1),), 8),
        LuauConstant("string", "Axe", 3),
        LuauConstant("string", "Damage", 3),
    )
    code = (
        _ad("DUPTABLE", a=0, d=2),
        _ad("LOADK", a=1, d=3),
        _abc("SETTABLEKS", a=1, b=0),
        0,
        _ad("LOADN", a=2, d=25),
        _abc("SETTABLEKS", a=2, b=0),
        4,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "template.luau")

    assert 'Name = "Axe"' in output
    assert 'Name = "Sword"' not in output
    assert "Damage = 25" in output
    assert ".Name =" not in output


def test_decompiles_open_call_and_vararg_setlist_tails() -> None:
    call_constants = (LuauConstant("string", "collect", 3),)
    call_code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("GETGLOBAL", a=1),
        0,
        _abc("CALL", a=1, b=1, c=0),
        _abc("SETLIST", a=0, b=1, c=0),
        0,
        _abc("RETURN", a=0, b=2),
    )
    call_output = decompile_module(
        _module(call_code, call_constants),
        {},
        "open-call.luau",
    )

    assert "{collect()}" in call_output
    assert "multiple returns" not in call_output
    assert "set all stack values" not in call_output

    vararg_code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("GETVARARGS", a=1, b=0),
        _abc("SETLIST", a=0, b=1, c=0),
        0,
        _abc("RETURN", a=0, b=2),
    )
    vararg_output = decompile_module(
        _module(vararg_code, vararg=True),
        {},
        "open-vararg.luau",
    )

    assert "{...}" in vararg_output
    assert "set all stack values" not in vararg_output


def test_transfers_single_use_table_across_move() -> None:
    constants = (LuauConstant("string", "Value", 3),)
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("MOVE", a=1, b=0),
        _ad("LOADN", a=2, d=5),
        _abc("SETTABLEKS", a=2, b=1),
        0,
        _abc("RETURN", a=1, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "move.luau")

    assert "{Value = 5}" in output
    assert "= v0" not in output
''',
    encoding="utf-8",
)

print("applied LunaUX Next 0.13 full table reconstruction")
