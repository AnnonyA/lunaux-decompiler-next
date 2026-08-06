from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from lunaux.backends.bytecode import (
    ClassShapeConstant,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
    format_type_tag,
)
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.ssa import SSAProgram, SSAValue

_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED: Final[frozenset[str]] = frozenset(
    {
        "and",
        "break",
        "class",
        "continue",
        "do",
        "else",
        "elseif",
        "end",
        "export",
        "extends",
        "false",
        "for",
        "function",
        "if",
        "in",
        "local",
        "nil",
        "not",
        "or",
        "public",
        "repeat",
        "return",
        "then",
        "true",
        "type",
        "typeof",
        "until",
        "while",
    }
)

_TYPE_FAMILIES: Final[dict[str, str]] = {
    "boolean": "bool",
    "buffer": "buf",
    "function": "func",
    "integer": "int",
    "number": "num",
    "string": "str",
    "table": "tbl",
    "thread": "thread",
    "vector": "vec",
}

_GLOBAL_TYPES: Final[dict[str, str]] = {
    "game": "DataModel",
    "script": "Instance",
    "workspace": "Workspace",
}

_PROPERTY_TYPES: Final[dict[str, str]] = {
    "Active": "boolean",
    "Anchored": "boolean",
    "CanCollide": "boolean",
    "CanQuery": "boolean",
    "CanTouch": "boolean",
    "Character": "Model?",
    "ClassName": "string",
    "CFrame": "CFrame",
    "Disabled": "boolean",
    "DisplayName": "string",
    "Enabled": "boolean",
    "Health": "number",
    "LocalPlayer": "Player",
    "MaxHealth": "number",
    "Name": "string",
    "Parent": "Instance?",
    "Position": "Vector3",
    "Text": "string",
    "Transparency": "number",
    "Value": "any",
    "Velocity": "Vector3",
    "Visible": "boolean",
    "WalkSpeed": "number",
}

_STRING_METHODS: Final[frozenset[str]] = frozenset(
    {
        "GetDebugId",
        "GetFullName",
        "GetRoleInGroup",
        "GetAttributeChangedSignal",
    }
)
_NUMBER_METHODS: Final[frozenset[str]] = frozenset(
    {
        "DistanceFromCharacter",
        "GetMass",
        "GetRankInGroup",
        "GetServerTimeNow",
    }
)
_BOOLEAN_METHODS: Final[frozenset[str]] = frozenset(
    {
        "IsA",
        "IsAncestorOf",
        "IsDescendantOf",
        "IsFriendsWith",
        "IsLoaded",
    }
)


@dataclass(frozen=True, slots=True)
class RecoveredSymbol:
    value: SSAValue
    name: str
    type_name: str | None
    confidence: int
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SymbolRecovery:
    program: SSAProgram
    symbols: Mapping[SSAValue, RecoveredSymbol]
    entry_names: Mapping[int, str]
    entry_types: Mapping[int, str]
    return_type: str | None

    def symbol_for(self, value: SSAValue | None) -> RecoveredSymbol | None:
        return self.symbols.get(value) if value is not None else None

    def name_at_definition(self, pc: int, register: int) -> str | None:
        symbol = self.symbol_for(self.program.value_defined_at(pc, register))
        return symbol.name if symbol is not None else None

    def name_at_use(self, pc: int, register: int) -> str | None:
        symbol = self.symbol_for(self.program.value_at_use(pc, register))
        return symbol.name if symbol is not None else None

    def type_at_definition(self, pc: int, register: int) -> str | None:
        symbol = self.symbol_for(self.program.value_defined_at(pc, register))
        return symbol.type_name if symbol is not None else None

    def type_at_use(self, pc: int, register: int) -> str | None:
        symbol = self.symbol_for(self.program.value_at_use(pc, register))
        return symbol.type_name if symbol is not None else None

    def report_lines(self, *, limit: int = 64) -> tuple[str, ...]:
        ordered = sorted(
            self.symbols.values(),
            key=lambda item: (
                item.value.origin_pc is not None,
                item.value.origin_pc if item.value.origin_pc is not None else -1,
                item.value.register,
                item.value.version,
            ),
        )
        lines: list[str] = []
        for symbol in ordered:
            if symbol.confidence < 45 and symbol.type_name is None:
                continue
            annotation = f": {symbol.type_name}" if symbol.type_name else ""
            evidence = "; ".join(symbol.evidence[:3]) or "generated fallback"
            lines.append(
                f"{symbol.value.name} -> {symbol.name}{annotation} [{evidence}]"
            )
            if len(lines) >= limit:
                break
        return tuple(lines)


@dataclass(frozen=True, slots=True)
class _Candidate:
    text: str
    score: int
    reason: str
    numbered: bool = False


@dataclass(slots=True)
class _Facts:
    names: dict[str, _Candidate]
    types: dict[str, _Candidate]

    @classmethod
    def empty(cls) -> _Facts:
        return cls(names={}, types={})

    def add_name(
        self,
        text: str | None,
        score: int,
        reason: str,
        *,
        numbered: bool = False,
    ) -> bool:
        clean = _identifier(text)
        if clean is None:
            return False
        candidate = _Candidate(clean, score, reason, numbered)
        previous = self.names.get(clean)
        if previous is None or candidate.score > previous.score:
            self.names[clean] = candidate
            return True
        return False

    def add_type(self, text: str | None, score: int, reason: str) -> bool:
        if not text:
            return False
        candidate = _Candidate(text, score, reason)
        previous = self.types.get(text)
        if previous is None or candidate.score > previous.score:
            self.types[text] = candidate
            return True
        return False

    def best_name(self) -> _Candidate | None:
        return _best(self.names.values())

    def best_type(self) -> _Candidate | None:
        return _best(self.types.values())


def _best(values: Iterable[_Candidate]) -> _Candidate | None:
    candidates = list(values)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.score, -len(item.text), item.text))


def _identifier(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if _IDENTIFIER.fullmatch(value) and value not in _RESERVED:
        return value
    value = re.sub(r"[^A-Za-z0-9_]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return None
    if value[0].isdigit():
        value = "value_" + value
    if value in _RESERVED:
        value += "Value"
    return value if _IDENTIFIER.fullmatch(value) else None


def _lower_camel(value: str) -> str:
    if not value:
        return value
    if value.isupper():
        return value.lower()
    return value[0].lower() + value[1:]


def _constant(proto: LuauProto, index: int) -> LuauConstant | None:
    return proto.constants[index] if 0 <= index < len(proto.constants) else None


def _constant_string(proto: LuauProto, index: int) -> str | None:
    constant = _constant(proto, index)
    if constant is None or constant.kind != "string":
        return None
    return constant.value if isinstance(constant.value, str) else None


def _constant_type(constant: LuauConstant | None) -> str | None:
    if constant is None:
        return None
    return {
        "boolean": "boolean",
        "closure": "function",
        "integer": "integer",
        "nil": "nil",
        "number": "number",
        "string": "string",
        "table": "table",
        "table_with_constants": "table",
        "vector": "vector",
        "vectord": "vector",
    }.get(constant.kind)


def _class_shape_name(proto: LuauProto, index: int) -> str | None:
    constant = _constant(proto, index)
    if (
        constant is None
        or constant.kind != "class_shape"
        or not isinstance(constant.value, ClassShapeConstant)
    ):
        return None
    return _constant_string(proto, constant.value.class_name_constant)


def _local_name(proto: LuauProto, register: int, pc: int) -> str | None:
    candidates = [
        item
        for item in proto.locals
        if item.register == register
        and item.start_pc <= pc < item.end_pc
        and item.name
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.start_pc).name


def _local_type(
    module: LuauBytecodeModule,
    proto: LuauProto,
    register: int,
    pc: int,
) -> str | None:
    candidates = [
        item
        for item in proto.typed_locals
        if item.register == register and item.start_pc <= pc < item.end_pc
    ]
    if not candidates:
        return None
    item = max(candidates, key=lambda candidate: candidate.start_pc)
    return format_type_tag(item.type_tag, module.userdata_type_map)


def _import_path(proto: LuauProto, aux: int | None) -> tuple[str, ...]:
    if aux is None:
        return ()
    count = aux >> 30
    indices = ((aux >> 20) & 1023, (aux >> 10) & 1023, aux & 1023)
    names: list[str] = []
    for index in range(min(count, 3)):
        name = _constant_string(proto, indices[index])
        if name is None:
            return ()
        names.append(name)
    return tuple(names)


def _instruction_constant(proto: LuauProto, instruction: DecodedInstruction) -> LuauConstant | None:
    if instruction.name == "LOADK":
        return _constant(proto, instruction.d)
    if instruction.name == "LOADKX":
        return _constant(proto, instruction.aux or 0)
    return None


def _property_type(key: str) -> str | None:
    return _PROPERTY_TYPES.get(key)


def _direct_call_type(path: str | None) -> str | None:
    if not path:
        return None
    if path in {"type", "typeof", "tostring"}:
        return "string"
    if path == "tonumber":
        return "number?"
    if path.startswith("math."):
        return "number"
    if path.startswith("string."):
        tail = path.rsplit(".", 1)[-1]
        if tail in {"byte", "find", "len"}:
            return "number"
        if tail in {"match"}:
            return "string?"
        return "string"
    if path.startswith("bit32."):
        return "number"
    if path in {"rawget"}:
        return "any"
    return None


def _type_family(type_name: str | None) -> tuple[str, bool] | None:
    if not type_name or type_name == "any":
        return None
    base = type_name.removesuffix("?")
    family = _TYPE_FAMILIES.get(base)
    if family is not None:
        return family, True
    if base.startswith("{"):
        return "list", True
    if " | " in base:
        return None
    identifier = _identifier(base)
    if identifier is not None:
        return _lower_camel(identifier), False
    return None


def _union_type(types: set[str]) -> str | None:
    values = {value for value in types if value and value != "any"}
    if not values:
        return None
    if "nil" in values and len(values) == 2:
        values.remove("nil")
        return next(iter(values)).removesuffix("?") + "?"
    if len(values) == 1:
        return next(iter(values))
    if len(values) <= 3:
        return " | ".join(sorted(values))
    return None


def build_symbol_recovery(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instructions: Sequence[DecodedInstruction],
    program: SSAProgram,
) -> SymbolRecovery:
    facts: defaultdict[SSAValue, _Facts] = defaultdict(_Facts.empty)
    relations: list[tuple[SSAValue, SSAValue, int, str]] = []
    instruction_by_pc = {instruction.pc: instruction for instruction in instructions}
    previous_by_next_pc = {
        instruction.pc + instruction.size: instruction for instruction in instructions
    }

    def add_definition_name(
        pc: int,
        register: int,
        text: str | None,
        score: int,
        reason: str,
        *,
        numbered: bool = False,
    ) -> None:
        value = program.value_defined_at(pc, register)
        if value is not None:
            facts[value].add_name(text, score, reason, numbered=numbered)

    def add_definition_type(
        pc: int,
        register: int,
        text: str | None,
        score: int,
        reason: str,
    ) -> None:
        value = program.value_defined_at(pc, register)
        if value is not None:
            facts[value].add_type(text, score, reason)

    def value_path(value: SSAValue | None, seen: set[SSAValue] | None = None) -> str | None:
        if value is None or value.origin_pc is None:
            return None
        visited = set() if seen is None else seen
        if value in visited:
            return None
        visited.add(value)
        instruction = instruction_by_pc.get(value.origin_pc)
        if instruction is None:
            return None
        if instruction.name == "GETGLOBAL":
            index = instruction.aux if instruction.aux is not None else -1
            return _constant_string(proto, index)
        if instruction.name == "GETIMPORT":
            path = _import_path(proto, instruction.aux)
            return ".".join(path) if path else None
        if instruction.name in {"GETTABLEKS", "GETUDATAKS"}:
            base = program.value_at_use(instruction.pc, instruction.b)
            key_index = (
                instruction.userdata_constant_index
                if instruction.name == "GETUDATAKS"
                else instruction.aux
            )
            key = _constant_string(proto, key_index if key_index is not None else -1)
            prefix = value_path(base, visited)
            if prefix and key:
                return prefix + "." + key
            return key
        if instruction.name == "MOVE":
            return value_path(program.value_at_use(instruction.pc, instruction.b), visited)
        if instruction.name == "NEWCLASS":
            return _class_shape_name(proto, instruction.aux or 0)
        return None

    def literal_string(value: SSAValue | None, seen: set[SSAValue] | None = None) -> str | None:
        if value is None or value.origin_pc is None:
            return None
        visited = set() if seen is None else seen
        if value in visited:
            return None
        visited.add(value)
        instruction = instruction_by_pc.get(value.origin_pc)
        if instruction is None:
            return None
        constant = _instruction_constant(proto, instruction)
        if constant and constant.kind == "string" and isinstance(constant.value, str):
            return constant.value
        if instruction.name == "MOVE":
            return literal_string(
                program.value_at_use(instruction.pc, instruction.b),
                visited,
            )
        return None

    entry_names: dict[int, str] = {}
    entry_types: dict[int, str] = {}
    for register in range(proto.num_params):
        debug_name = _local_name(proto, register, 0)
        type_name = _local_type(module, proto, register, 0)
        entry_value = program.entry_values.get(register)
        if entry_value is not None:
            facts[entry_value].add_name(debug_name, 100, "debug local parameter name")
            facts[entry_value].add_type(type_name, 100, "serialized parameter type")
        if type_name:
            entry_types[register] = type_name

    for ssa_instruction in program.instructions.values():
        instruction = ssa_instruction.instruction
        pc = instruction.pc
        name = instruction.name
        for definition in ssa_instruction.definitions:
            debug_name = _local_name(proto, definition.register, pc)
            type_name = _local_type(module, proto, definition.register, pc)
            facts[definition].add_name(debug_name, 100, "debug local name")
            facts[definition].add_type(type_name, 100, "serialized local type")

        if name == "MOVE":
            target = program.value_defined_at(pc, instruction.a)
            source = program.value_at_use(pc, instruction.b)
            if target is not None and source is not None:
                relations.append((target, source, 82, "value copied from source"))
        elif name == "LOADNIL":
            add_definition_type(pc, instruction.a, "nil", 95, "LOADNIL literal")
        elif name == "LOADB":
            add_definition_type(pc, instruction.a, "boolean", 95, "LOADB literal")
        elif name == "LOADN":
            add_definition_type(pc, instruction.a, "number", 95, "LOADN literal")
        elif name in {"LOADK", "LOADKX"}:
            constant = _instruction_constant(proto, instruction)
            add_definition_type(
                pc,
                instruction.a,
                _constant_type(constant),
                95,
                "constant table kind",
            )
        elif name == "GETGLOBAL":
            index = instruction.aux if instruction.aux is not None else -1
            key = _constant_string(proto, index)
            add_definition_name(pc, instruction.a, key, 78, "global name")
            add_definition_type(
                pc,
                instruction.a,
                _GLOBAL_TYPES.get(key or ""),
                72,
                "known global type",
            )
        elif name == "GETIMPORT":
            path = _import_path(proto, instruction.aux)
            if path:
                add_definition_name(pc, instruction.a, path[-1], 80, "import path")
                add_definition_type(
                    pc,
                    instruction.a,
                    _GLOBAL_TYPES.get(".".join(path)) or _GLOBAL_TYPES.get(path[-1]),
                    70,
                    "known import type",
                )
        elif name in {"GETTABLEKS", "GETUDATAKS"}:
            field_index = (
                instruction.userdata_constant_index
                if name == "GETUDATAKS"
                else instruction.aux
            )
            key = _constant_string(
                proto,
                field_index if field_index is not None else -1,
            )
            add_definition_name(pc, instruction.a, key, 68, "field name evidence")
            add_definition_type(
                pc,
                instruction.a,
                _property_type(key or ""),
                76,
                "known Roblox property type",
            )
        elif name in {
            "ADD",
            "SUB",
            "MUL",
            "DIV",
            "MOD",
            "POW",
            "IDIV",
            "ADDK",
            "SUBK",
            "MULK",
            "DIVK",
            "MODK",
            "POWK",
            "IDIVK",
            "SUBRK",
            "DIVRK",
            "LENGTH",
        }:
            add_definition_type(pc, instruction.a, "number", 84, "numeric opcode")
        elif name == "CONCAT":
            add_definition_type(pc, instruction.a, "string", 88, "CONCAT result")
        elif name == "NOT":
            add_definition_type(pc, instruction.a, "boolean", 88, "NOT result")
        elif name in {"NEWTABLE", "DUPTABLE"}:
            add_definition_type(pc, instruction.a, "table", 92, "table construction")
        elif name in {"NEWCLOSURE", "DUPCLOSURE"}:
            child_id: int | None = None
            if name == "NEWCLOSURE" and 0 <= instruction.d < len(proto.child_proto_ids):
                child_id = proto.child_proto_ids[instruction.d]
            elif name == "DUPCLOSURE":
                constant = _constant(proto, instruction.d)
                if constant and constant.kind == "closure" and isinstance(constant.value, int):
                    child_id = constant.value
            child_name = (
                module.protos[child_id].debug_name
                if child_id is not None and 0 <= child_id < len(module.protos)
                else None
            )
            add_definition_name(pc, instruction.a, child_name, 92, "prototype binding")
            add_definition_type(pc, instruction.a, "function", 94, "closure construction")
        elif name == "NEWCLASS":
            class_name = _class_shape_name(proto, instruction.aux or 0)
            add_definition_name(pc, instruction.a, class_name, 96, "class shape name")
            add_definition_type(pc, instruction.a, "class", 94, "NEWCLASS result")
        elif name in {"CALL", "CALLFB"}:
            previous = previous_by_next_pc.get(pc)
            if (
                previous is None
                or previous.name not in {"NAMECALL", "NAMECALLUDATA"}
                or previous.a != instruction.a
            ):
                previous = None
                for previous_instruction in reversed(instructions):
                    if previous_instruction.pc >= pc:
                        continue
                    if previous_instruction.name in {
                        "CALL",
                        "CALLFB",
                        "RETURN",
                        "JUMP",
                        "JUMPBACK",
                        "JUMPX",
                    }:
                        break
                    if (
                        previous_instruction.name
                        in {"NAMECALL", "NAMECALLUDATA"}
                        and previous_instruction.a == instruction.a
                    ):
                        previous = previous_instruction
                        break
            method: str | None = None
            if (
                previous is not None
                and previous.name in {"NAMECALL", "NAMECALLUDATA"}
                and previous.a == instruction.a
            ):
                key_index = (
                    previous.userdata_constant_index
                    if previous.name == "NAMECALLUDATA"
                    else previous.aux
                )
                method = _constant_string(
                    proto,
                    key_index if key_index is not None else -1,
                )

            result_registers = [value.register for value in ssa_instruction.definitions]
            if method == "GetService" and instruction.b > 2:
                argument = literal_string(program.value_at_use(pc, instruction.a + 2))
                for register in result_registers:
                    add_definition_name(
                        pc,
                        register,
                        argument,
                        98,
                        "GetService string argument",
                    )
                    add_definition_type(
                        pc,
                        register,
                        argument,
                        96,
                        "Roblox service class",
                    )
            elif method in {"WaitForChild", "FindFirstChild"} and instruction.b > 2:
                argument = literal_string(program.value_at_use(pc, instruction.a + 2))
                for register in result_registers:
                    add_definition_name(
                        pc,
                        register,
                        argument,
                        92,
                        f"{method} string argument",
                    )
                    add_definition_type(
                        pc,
                        register,
                        "Instance" if method == "WaitForChild" else "Instance?",
                        68,
                        f"{method} return contract",
                    )
            elif (
                method in {"FindFirstChildOfClass", "FindFirstChildWhichIsA"}
                and instruction.b > 2
            ):
                argument = literal_string(program.value_at_use(pc, instruction.a + 2))
                for register in result_registers:
                    add_definition_name(
                        pc,
                        register,
                        _lower_camel(argument) if argument else None,
                        94,
                        f"{method} class argument",
                    )
                    add_definition_type(
                        pc,
                        register,
                        argument + "?" if argument else "Instance?",
                        90,
                        f"{method} return class",
                    )
            elif method in _STRING_METHODS:
                for register in result_registers:
                    add_definition_type(pc, register, "string", 78, f"{method} return")
            elif method in _NUMBER_METHODS:
                for register in result_registers:
                    add_definition_type(pc, register, "number", 78, f"{method} return")
            elif method in _BOOLEAN_METHODS:
                for register in result_registers:
                    add_definition_type(pc, register, "boolean", 82, f"{method} return")
            elif method == "GetPlayers":
                for register in result_registers:
                    add_definition_name(pc, register, "players", 82, "GetPlayers result")
                    add_definition_type(pc, register, "{Player}", 82, "GetPlayers return")
            elif method in {"GetChildren", "GetDescendants"}:
                semantic = "children" if method == "GetChildren" else "descendants"
                for register in result_registers:
                    add_definition_name(pc, register, semantic, 78, f"{method} result")
                    add_definition_type(pc, register, "{Instance}", 80, f"{method} return")
            elif method == "Clone":
                source = program.value_at_use(pc, instruction.a + 1)
                for definition in ssa_instruction.definitions:
                    if source is not None:
                        relations.append((definition, source, 72, "Clone preserves instance type"))
                    facts[definition].add_name("clone", 58, "Clone result")
            else:
                function_value = program.value_at_use(pc, instruction.a)
                call_path = value_path(function_value)
                return_type = _direct_call_type(call_path)
                for register in result_registers:
                    add_definition_type(pc, register, return_type, 76, "known function return")

                class_name = None
                if function_value is not None and function_value.origin_pc is not None:
                    origin = instruction_by_pc.get(function_value.origin_pc)
                    if origin is not None and origin.name == "NEWCLASS":
                        class_name = _class_shape_name(proto, origin.aux or 0)
                if class_name:
                    for register in result_registers:
                        add_definition_name(
                            pc,
                            register,
                            _lower_camel(class_name),
                            86,
                            "class construction result",
                        )
                        add_definition_type(
                            pc,
                            register,
                            class_name,
                            92,
                            "class construction type",
                        )

    for phi in program.phis:
        for operand in phi.operands.values():
            relations.append((phi.result, operand, 64, "control-flow merge"))

    for _ in range(8):
        changed = False
        for target, source, score, reason in relations:
            source_name = facts[source].best_name()
            source_type = facts[source].best_type()
            if source_name is not None:
                changed |= facts[target].add_name(
                    source_name.text,
                    min(score, source_name.score - 1),
                    reason,
                    numbered=source_name.numbered,
                )
            if source_type is not None:
                changed |= facts[target].add_type(
                    source_type.text,
                    min(score, source_type.score - 1),
                    reason,
                )
        if not changed:
            break

    all_values: set[SSAValue] = set(program.entry_values.values())
    all_values.update(program.definitions.values())
    all_values.update(phi.result for phi in program.phis)

    used_names: defaultdict[str, int] = defaultdict(int)
    family_counts: defaultdict[str, int] = defaultdict(int)
    argument_count = 0
    generic_count = 0
    symbols: dict[SSAValue, RecoveredSymbol] = {}

    for value in sorted(
        all_values,
        key=lambda item: (
            item.origin_pc is not None,
            item.origin_pc if item.origin_pc is not None else -1,
            item.register,
            item.version,
        ),
    ):
        item_facts = facts[value]
        best_name = item_facts.best_name()
        best_type = item_facts.best_type()
        if best_name is None:
            family = _type_family(best_type.text if best_type else None)
            if value.kind == "entry" and value.register < proto.num_params:
                if family is None:
                    argument_count += 1
                    base = f"arg{argument_count}"
                    generated_name = _Candidate(
                        base,
                        36,
                        "untyped parameter family",
                    )
                else:
                    family_base, numbered = family
                    family_counts[family_base] += 1
                    suffix = family_counts[family_base] if numbered else ""
                    generated_name = _Candidate(
                        f"{family_base}{suffix}",
                        58,
                        "generated from parameter type",
                        numbered,
                    )
            elif family is not None:
                family_base, numbered = family
                family_counts[family_base] += 1
                suffix = family_counts[family_base] if numbered else ""
                generated_name = _Candidate(
                    f"{family_base}{suffix}",
                    48,
                    "generated from inferred type",
                    numbered,
                )
            else:
                generic_count += 1
                generated_name = _Candidate(
                    f"var{generic_count}",
                    20,
                    "generic fallback",
                    True,
                )
            best_name = generated_name

        base_name = best_name.text
        used_names[base_name] += 1
        final_name = base_name
        if used_names[base_name] > 1:
            final_name = f"{base_name}{used_names[base_name]}"

        evidence: list[str] = [best_name.reason]
        if best_type is not None and best_type.reason not in evidence:
            evidence.append(best_type.reason)
        symbols[value] = RecoveredSymbol(
            value=value,
            name=final_name,
            type_name=best_type.text if best_type is not None else None,
            confidence=max(best_name.score, best_type.score if best_type else 0),
            evidence=tuple(evidence),
        )

    for register in range(proto.num_params):
        entry_value = program.entry_values.get(register)
        symbol = symbols.get(entry_value) if entry_value is not None else None
        if symbol is not None:
            entry_names[register] = symbol.name
            if symbol.type_name:
                entry_types[register] = symbol.type_name
            continue
        type_name = entry_types.get(register)
        family = _type_family(type_name)
        debug_name = _identifier(_local_name(proto, register, 0))
        if debug_name:
            entry_names[register] = debug_name
        elif family is not None:
            family_base, numbered = family
            family_counts[family_base] += 1
            suffix = family_counts[family_base] if numbered else ""
            entry_names[register] = f"{family_base}{suffix}"
        else:
            argument_count += 1
            entry_names[register] = f"arg{argument_count}"

    return_types: set[str] = set()
    saw_empty_return = False
    unresolved_return = False
    for instruction in instructions:
        if instruction.name != "RETURN":
            continue
        if instruction.b == 1:
            saw_empty_return = True
        elif instruction.b == 2:
            return_value = program.value_at_use(instruction.pc, instruction.a)
            symbol = (
                symbols.get(return_value) if return_value is not None else None
            )
            if symbol is None or symbol.type_name is None:
                unresolved_return = True
            else:
                return_types.add(symbol.type_name)
        else:
            unresolved_return = True
    if saw_empty_return and return_types:
        return_types.add("nil")
    return_type = None if unresolved_return and not return_types else _union_type(return_types)

    return SymbolRecovery(
        program=program,
        symbols=MappingProxyType(symbols),
        entry_names=MappingProxyType(entry_names),
        entry_types=MappingProxyType(entry_types),
        return_type=return_type,
    )
