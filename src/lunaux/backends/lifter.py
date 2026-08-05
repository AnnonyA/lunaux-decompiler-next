from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import cast

from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.opcodes import DecodedInstruction, decode_words

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = {
    "and", "break", "continue", "do", "else", "elseif", "end", "export",
    "false", "for", "function", "if", "in", "local", "nil", "not", "or",
    "repeat", "return", "then", "true", "type", "typeof", "until", "while",
}
_BINARY_OPS = {
    "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%", "POW": "^",
    "IDIV": "//", "AND": "and", "OR": "or",
}
_BINARY_CONST_OPS = {
    "ADDK": "+", "SUBK": "-", "MULK": "*", "DIVK": "/", "MODK": "%",
    "POWK": "^", "IDIVK": "//", "ANDK": "and", "ORK": "or",
}
_UNARY_OPS = {"NOT": "not ", "MINUS": "-", "LENGTH": "#"}
_COMPARISON_FALLTHROUGH = {
    "JUMPIFEQ": "~=",
    "JUMPIFLE": ">",
    "JUMPIFLT": ">=",
    "JUMPIFNOTEQ": "==",
    "JUMPIFNOTLE": "<=",
    "JUMPIFNOTLT": "<",
}
_CAPTURE_NAMES = {0: "value", 1: "reference", 2: "upvalue"}


@dataclass(frozen=True, slots=True)
class _Options:
    semicolons: bool
    upvalue_comment: bool
    show_line_defined: bool
    show_function_id: bool
    preserve_for_step: bool

    @classmethod
    def from_backend(cls, options: dict[str, bool]) -> _Options:
        return cls(
            semicolons=options.get("Semicolons", False),
            upvalue_comment=options.get("UpvalueComment", True),
            show_line_defined=options.get("ShowLineDefined", True),
            show_function_id=options.get("ShowFunctionId", False),
            preserve_for_step=options.get("PreserveForStep", False),
        )


class _Emitter:
    def __init__(self, semicolons: bool) -> None:
        self.lines: list[str] = []
        self.indent = 0
        self.semicolons = semicolons

    def line(self, text: str = "", *, statement: bool = False) -> None:
        suffix = (
            ";"
            if statement and self.semicolons and text and not text.rstrip().endswith(";")
            else ""
        )
        self.lines.append("    " * self.indent + text + suffix)

    def open(self, text: str) -> None:
        self.line(text)
        self.indent += 1

    def close(self, text: str = "end") -> None:
        self.indent = max(0, self.indent - 1)
        self.line(text)

    def render(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


def _sanitize_identifier(value: str | None, fallback: str) -> str:
    if value and _IDENTIFIER.fullmatch(value) and value not in _RESERVED:
        return value
    return fallback


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _format_number(value: float) -> str:
    if math.isnan(value):
        return "(0 / 0)"
    if math.isinf(value):
        return "math.huge" if value > 0 else "-math.huge"
    if value == 0 and math.copysign(1.0, value) < 0:
        return "-0"
    return repr(value)


def _constant(proto: LuauProto, index: int) -> LuauConstant | None:
    return proto.constants[index] if 0 <= index < len(proto.constants) else None


def _constant_expr(proto: LuauProto, index: int) -> str:
    constant = _constant(proto, index)
    if constant is None:
        return f"K{index}"
    value = constant.value
    if constant.kind == "nil":
        return "nil"
    if constant.kind == "boolean":
        return "true" if value else "false"
    if constant.kind == "number" and isinstance(value, float):
        return _format_number(value)
    if constant.kind == "integer" and isinstance(value, int):
        return str(value)
    if constant.kind == "string" and isinstance(value, str):
        return _quote(value)
    if constant.kind in ("vector", "vectord") and isinstance(value, tuple) and len(value) == 4:
        coordinates = cast(tuple[float, float, float, float], value)
        return (
            "Vector3.new("
            f"{_format_number(coordinates[0])}, "
            f"{_format_number(coordinates[1])}, "
            f"{_format_number(coordinates[2])})"
        )
    if constant.kind == "closure" and isinstance(value, int):
        return f"proto_{value}"
    if constant.kind == "table" and isinstance(value, tuple):
        entries = []
        for key_index in value:
            if isinstance(key_index, int):
                entries.append(f"[{_constant_expr(proto, key_index)}] = 0")
        return "{" + ", ".join(entries) + "}"
    if constant.kind == "table_with_constants" and isinstance(value, tuple):
        entries = []
        for pair in value:
            if isinstance(pair, tuple) and len(pair) == 2:
                key_index, value_index = pair
                if not isinstance(key_index, int) or not isinstance(value_index, int):
                    continue
                rhs = _constant_expr(proto, value_index) if value_index >= 0 else "0"
                entries.append(f"[{_constant_expr(proto, key_index)}] = {rhs}")
        return "{" + ", ".join(entries) + "}"
    if constant.kind == "import" and isinstance(value, int):
        return f"--[[ import 0x{value:08x} ]] nil"
    return f"--[[ {constant.kind} ]] nil"


def _constant_string(proto: LuauProto, index: int) -> str | None:
    constant = _constant(proto, index)
    if constant and constant.kind == "string" and isinstance(constant.value, str):
        return constant.value
    return None


def _field(base: str, key: str) -> str:
    if _IDENTIFIER.fullmatch(key) and key not in _RESERVED:
        return f"{base}.{key}"
    return f"{base}[{_quote(key)}]"


def _global(key: str) -> str:
    if _IDENTIFIER.fullmatch(key) and key not in _RESERVED:
        return key
    return f"_G[{_quote(key)}]"


def _decode_import(proto: LuauProto, aux: int | None) -> str:
    if aux is None:
        return "_G"
    count = aux >> 30
    indices = ((aux >> 20) & 1023, (aux >> 10) & 1023, aux & 1023)
    names = [_constant_string(proto, indices[index]) for index in range(min(count, 3))]
    if not names or names[0] is None:
        return f"_G --[[ import 0x{aux:08x} ]]"
    result = _global(names[0])
    for name in names[1:]:
        if name is None:
            return result + f" --[[ import 0x{aux:08x} ]]"
        result = _field(result, name)
    return result


def _jump_target(instruction: DecodedInstruction) -> int:
    offset = instruction.e if instruction.name == "JUMPX" else instruction.d
    return instruction.pc + 1 + offset


def _local_name(proto: LuauProto, register: int, pc: int) -> str | None:
    candidates = [
        item
        for item in proto.locals
        if item.register == register and item.start_pc <= pc < item.end_pc and item.name
    ]
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: item.start_pc)
    return _sanitize_identifier(selected.name, f"v{register}")


def _proto_names(module: LuauBytecodeModule) -> dict[int, str]:
    used: set[str] = set()
    result: dict[int, str] = {}
    for proto in module.protos:
        base = _sanitize_identifier(proto.debug_name, f"proto_{proto.proto_id}")
        name = base
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        result[proto.proto_id] = name
    return result


class _FunctionLifter:
    def __init__(
        self,
        module: LuauBytecodeModule,
        proto: LuauProto,
        proto_names: dict[int, str],
        options: _Options,
        emitter: _Emitter,
    ) -> None:
        self.module = module
        self.proto = proto
        self.proto_names = proto_names
        self.options = options
        self.out = emitter
        self.register_names: dict[int, str] = {}
        self.declared: set[str] = set()
        self.pending_namecalls: dict[int, tuple[str, str]] = {}
        self.block_closures: dict[int, list[str]] = defaultdict(list)
        self.instructions = list(decode_words(proto.code))
        self.instruction_by_pc = {
            instruction.pc: instruction for instruction in self.instructions
        }
        self.labels = self._collect_labels()

    def _collect_labels(self) -> set[int]:
        labels: set[int] = set()
        control_ops = {
            "FORNPREP",
            "FORNLOOP",
            "FORGPREP",
            "FORGPREP_INEXT",
            "FORGPREP_NEXT",
            "FORGLOOP",
            "CMPPROTO",
        }
        for instruction in self.instructions:
            if instruction.name.startswith("JUMP") or instruction.name in control_ops:
                target = _jump_target(instruction)
                if 0 <= target <= len(self.proto.code):
                    labels.add(target)
        return labels

    def _name(self, register: int, pc: int) -> str:
        active = _local_name(self.proto, register, pc)
        if active:
            self.register_names[register] = active
            return active
        return self.register_names.get(register, f"v{register}")

    def _ref(self, register: int, pc: int) -> str:
        return self._name(register, pc)

    def _assign(self, register: int, expression: str, pc: int) -> None:
        name = self._name(register, pc)
        prefix = "" if name in self.declared else "local "
        self.declared.add(name)
        self.register_names[register] = name
        self.out.line(f"{prefix}{name} = {expression}", statement=True)

    def _assign_many(self, registers: list[int], expression: str, pc: int) -> None:
        names: list[str] = []
        needs_local = False
        for register in registers:
            name = self._name(register, pc)
            names.append(name)
            if name not in self.declared:
                needs_local = True
                self.declared.add(name)
            self.register_names[register] = name
        prefix = "local " if needs_local else ""
        self.out.line(f"{prefix}{', '.join(names)} = {expression}", statement=True)

    def _close_blocks(self, pc: int) -> None:
        for close_text in reversed(self.block_closures.pop(pc, [])):
            self.out.close(close_text)

    def _open_until(self, target: int, header: str, close_text: str = "end") -> bool:
        if target <= 0 or target > len(self.proto.code):
            return False
        self.out.open(header)
        self.block_closures[target].append(close_text)
        return True

    def _global_key(self, instruction: DecodedInstruction) -> str:
        index = instruction.aux if instruction.aux is not None else -1
        key = _constant_string(self.proto, index)
        return _global(key) if key is not None else f"_G[K{instruction.aux}]"

    def _table_key(self, instruction: DecodedInstruction) -> str:
        index = instruction.aux if instruction.aux is not None else -1
        key = _constant_string(self.proto, index)
        return key if key is not None else f"K{instruction.aux}"

    def _call_expression(self, instruction: DecodedInstruction) -> str:
        if instruction.a in self.pending_namecalls:
            base, method = self.pending_namecalls.pop(instruction.a)
            start = instruction.a + 2
            count = max(0, instruction.b - 2) if instruction.b else 0
            args = [self._ref(start + index, instruction.pc) for index in range(count)]
            method_expr = (
                method
                if _IDENTIFIER.fullmatch(method) and method not in _RESERVED
                else f"[{_quote(method)}]"
            )
            if method_expr.startswith("["):
                return f"{base}{method_expr}({', '.join(args)})"
            return f"{base}:{method_expr}({', '.join(args)})"
        function = self._ref(instruction.a, instruction.pc)
        if instruction.b == 0:
            args_text = "..."
        else:
            args = [
                self._ref(instruction.a + index, instruction.pc)
                for index in range(1, instruction.b)
            ]
            args_text = ", ".join(args)
        return f"{function}({args_text})"

    def _conditional_body(self, instruction: DecodedInstruction) -> str | None:
        name = instruction.name
        if name == "JUMPIF":
            return f"not {self._ref(instruction.a, instruction.pc)}"
        if name == "JUMPIFNOT":
            return self._ref(instruction.a, instruction.pc)
        if name in _COMPARISON_FALLTHROUGH:
            rhs_register = (instruction.aux or 0) & 0xFF
            return (
                f"{self._ref(instruction.a, instruction.pc)} "
                f"{_COMPARISON_FALLTHROUGH[name]} "
                f"{self._ref(rhs_register, instruction.pc)}"
            )
        if name.startswith("JUMPXEQK"):
            if name == "JUMPXEQKNIL":
                rhs = "nil"
            elif name == "JUMPXEQKB":
                rhs = "true" if (instruction.aux or 0) & 1 else "false"
            else:
                rhs = _constant_expr(self.proto, (instruction.aux or 0) & 0xFFFFFF)
            not_flag = bool((instruction.aux or 0) & 0x80000000)
            fallthrough_operator = "==" if not_flag else "~="
            return (
                f"{self._ref(instruction.a, instruction.pc)} "
                f"{fallthrough_operator} {rhs}"
            )
        return None

    def _handle_loop_prep(self, instruction: DecodedInstruction) -> bool:
        if instruction.name == "FORNPREP":
            target = _jump_target(instruction)
            variable = self._name(instruction.a + 3, instruction.pc)
            self.declared.add(variable)
            start = self._ref(instruction.a + 2, instruction.pc)
            limit = self._ref(instruction.a, instruction.pc)
            step = self._ref(instruction.a + 1, instruction.pc)
            header = f"for {variable} = {start}, {limit}"
            if self.options.preserve_for_step or step not in ("1", "1.0"):
                header += f", {step}"
            header += " do"
            return self._open_until(target, header)

        generic_prep = {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}
        if instruction.name in generic_prep:
            loop_pc = _jump_target(instruction)
            loop_instruction = self.instruction_by_pc.get(loop_pc)
            variable_count = 2
            close_pc = loop_pc + 1
            if loop_instruction and loop_instruction.name == "FORGLOOP":
                variable_count = max(1, (loop_instruction.aux or 1) & 0xFF)
                close_pc = loop_pc + loop_instruction.size
            variables = [
                self._name(instruction.a + 3 + index, instruction.pc)
                for index in range(variable_count)
            ]
            self.declared.update(variables)
            iterator = self._ref(instruction.a, instruction.pc)
            state = self._ref(instruction.a + 1, instruction.pc)
            index = self._ref(instruction.a + 2, instruction.pc)
            return self._open_until(
                close_pc,
                f"for {', '.join(variables)} in {iterator}, {state}, {index} do",
            )
        return False

    def lift(self, *, as_function: bool) -> None:
        parameters = []
        for register in range(self.proto.num_params):
            name = _local_name(self.proto, register, 0) or f"arg{register + 1}"
            name = _sanitize_identifier(name, f"arg{register + 1}")
            parameters.append(name)
            self.register_names[register] = name
            self.declared.add(name)
        if self.proto.is_vararg:
            parameters.append("...")

        if as_function:
            function_name = self.proto_names[self.proto.proto_id]
            self.out.open(f"local function {function_name}({', '.join(parameters)})")
        if self.options.show_function_id:
            self.out.line(f"-- function id: {self.proto.proto_id}")
        if self.options.show_line_defined:
            self.out.line(f"-- line defined: {self.proto.line_defined}")
        if self.options.upvalue_comment and self.proto.num_upvalues:
            names = [
                name or f"upvalue_{index}"
                for index, name in enumerate(self.proto.upvalue_names)
            ]
            if len(names) < self.proto.num_upvalues:
                names.extend(
                    f"upvalue_{index}"
                    for index in range(len(names), self.proto.num_upvalues)
                )
            self.out.line("-- upvalues: " + ", ".join(names))

        for instruction in self.instructions:
            self._close_blocks(instruction.pc)
            if instruction.pc in self.labels:
                self.out.line(f"-- L{instruction.pc:04d}")
            self._lift_instruction(instruction)

        self._close_blocks(len(self.proto.code))
        for target in sorted(self.block_closures):
            self._close_blocks(target)
        if as_function:
            self.out.close()
            self.out.line()

    def _lift_instruction(self, instruction: DecodedInstruction) -> None:
        name = instruction.name
        pc = instruction.pc
        if name in {"NOP", "BREAK", "COVERAGE", "NATIVECALL", "PREPVARARGS"}:
            return
        if name == "LOADNIL":
            self._assign(instruction.a, "nil", pc)
        elif name == "LOADB":
            self._assign(instruction.a, "true" if instruction.b else "false", pc)
        elif name == "LOADN":
            self._assign(instruction.a, str(instruction.d), pc)
        elif name == "LOADK":
            self._assign(instruction.a, _constant_expr(self.proto, instruction.d), pc)
        elif name == "LOADKX":
            index = instruction.aux if instruction.aux is not None else 0
            self._assign(instruction.a, _constant_expr(self.proto, index), pc)
        elif name == "MOVE":
            self._assign(instruction.a, self._ref(instruction.b, pc), pc)
        elif name == "GETGLOBAL":
            self._assign(instruction.a, self._global_key(instruction), pc)
        elif name == "SETGLOBAL":
            self.out.line(
                f"{self._global_key(instruction)} = {self._ref(instruction.a, pc)}",
                statement=True,
            )
        elif name == "GETIMPORT":
            self._assign(instruction.a, _decode_import(self.proto, instruction.aux), pc)
        elif name == "GETUPVAL":
            upvalue = (
                self.proto.upvalue_names[instruction.b]
                if instruction.b < len(self.proto.upvalue_names)
                else None
            )
            self._assign(
                instruction.a,
                _sanitize_identifier(upvalue, f"upvalue_{instruction.b}"),
                pc,
            )
        elif name == "SETUPVAL":
            upvalue = (
                self.proto.upvalue_names[instruction.b]
                if instruction.b < len(self.proto.upvalue_names)
                else None
            )
            lhs = _sanitize_identifier(upvalue, f"upvalue_{instruction.b}")
            self.out.line(f"{lhs} = {self._ref(instruction.a, pc)}", statement=True)
        elif name == "GETTABLE":
            expression = (
                f"{self._ref(instruction.b, pc)}"
                f"[{self._ref(instruction.c, pc)}]"
            )
            self._assign(instruction.a, expression, pc)
        elif name == "SETTABLE":
            self.out.line(
                f"{self._ref(instruction.b, pc)}"
                f"[{self._ref(instruction.c, pc)}] = "
                f"{self._ref(instruction.a, pc)}",
                statement=True,
            )
        elif name in {"GETTABLEKS", "GETUDATAKS"}:
            expression = _field(
                self._ref(instruction.b, pc),
                self._table_key(instruction),
            )
            self._assign(instruction.a, expression, pc)
        elif name in {"SETTABLEKS", "SETUDATAKS"}:
            self.out.line(
                f"{_field(self._ref(instruction.b, pc), self._table_key(instruction))} "
                f"= {self._ref(instruction.a, pc)}",
                statement=True,
            )
        elif name == "GETTABLEN":
            self._assign(
                instruction.a,
                f"{self._ref(instruction.b, pc)}[{instruction.c + 1}]",
                pc,
            )
        elif name == "SETTABLEN":
            self.out.line(
                f"{self._ref(instruction.b, pc)}[{instruction.c + 1}] "
                f"= {self._ref(instruction.a, pc)}",
                statement=True,
            )
        elif name in _BINARY_OPS:
            expression = (
                f"{self._ref(instruction.b, pc)} {_BINARY_OPS[name]} "
                f"{self._ref(instruction.c, pc)}"
            )
            self._assign(instruction.a, expression, pc)
        elif name in _BINARY_CONST_OPS:
            expression = (
                f"{self._ref(instruction.b, pc)} {_BINARY_CONST_OPS[name]} "
                f"{_constant_expr(self.proto, instruction.c)}"
            )
            self._assign(instruction.a, expression, pc)
        elif name in {"SUBRK", "DIVRK"}:
            operator = "-" if name == "SUBRK" else "/"
            expression = (
                f"{_constant_expr(self.proto, instruction.b)} {operator} "
                f"{self._ref(instruction.c, pc)}"
            )
            self._assign(instruction.a, expression, pc)
        elif name in _UNARY_OPS:
            self._assign(
                instruction.a,
                f"{_UNARY_OPS[name]}{self._ref(instruction.b, pc)}",
                pc,
            )
        elif name == "CONCAT":
            values = [
                self._ref(register, pc)
                for register in range(instruction.b, instruction.c + 1)
            ]
            self._assign(instruction.a, " .. ".join(values), pc)
        elif name == "NEWTABLE":
            self._assign(instruction.a, "{}", pc)
        elif name == "DUPTABLE":
            self._assign(instruction.a, _constant_expr(self.proto, instruction.d), pc)
        elif name == "SETLIST":
            count = max(0, instruction.c - 1) if instruction.c else 0
            start_index = instruction.aux or 0
            for index in range(count):
                self.out.line(
                    f"{self._ref(instruction.a, pc)}[{start_index + index + 1}] "
                    f"= {self._ref(instruction.b + index, pc)}",
                    statement=True,
                )
        elif name in {"NEWCLOSURE", "DUPCLOSURE"}:
            child_id: int | None = None
            if name == "NEWCLOSURE" and 0 <= instruction.d < len(self.proto.child_proto_ids):
                child_id = self.proto.child_proto_ids[instruction.d]
            elif name == "DUPCLOSURE":
                constant = _constant(self.proto, instruction.d)
                if (
                    constant
                    and constant.kind == "closure"
                    and isinstance(constant.value, int)
                ):
                    child_id = constant.value
            if child_id is not None:
                expression = self.proto_names.get(child_id, f"proto_{child_id}")
            else:
                expression = "function() end"
            self._assign(instruction.a, expression, pc)
        elif name in {"NAMECALL", "NAMECALLUDATA"}:
            self.pending_namecalls[instruction.a] = (
                self._ref(instruction.b, pc),
                self._table_key(instruction),
            )
            self.register_names[instruction.a + 1] = self._ref(instruction.b, pc)
        elif name in {"CALL", "CALLFB"}:
            expression = self._call_expression(instruction)
            if instruction.c == 1:
                self.out.line(expression, statement=True)
            elif instruction.c == 0:
                self._assign(
                    instruction.a,
                    expression + " --[[ multiple returns ]]",
                    pc,
                )
            else:
                registers = list(
                    range(instruction.a, instruction.a + instruction.c - 1)
                )
                self._assign_many(registers, expression, pc)
        elif name == "RETURN":
            if instruction.b == 1:
                self.out.line("return", statement=True)
            elif instruction.b == 0:
                self.out.line(
                    f"return {self._ref(instruction.a, pc)} "
                    "--[[ multiple returns ]]",
                    statement=True,
                )
            else:
                values = [
                    self._ref(instruction.a + index, pc)
                    for index in range(instruction.b - 1)
                ]
                self.out.line("return " + ", ".join(values), statement=True)
        elif name == "GETVARARGS":
            if instruction.b <= 2:
                self._assign(instruction.a, "...", pc)
            else:
                registers = list(
                    range(instruction.a, instruction.a + instruction.b - 1)
                )
                self._assign_many(registers, "...", pc)
        elif name == "CAPTURE":
            if self.options.upvalue_comment:
                capture_kind = _CAPTURE_NAMES.get(
                    instruction.a,
                    f"type {instruction.a}",
                )
                self.out.line(f"-- capture {capture_kind} from {instruction.b}")
        elif self._handle_loop_prep(instruction):
            return
        elif name in {"FORNLOOP", "FORGLOOP"}:
            return
        elif name in {
            "JUMPIF",
            "JUMPIFNOT",
            *_COMPARISON_FALLTHROUGH,
            "JUMPXEQKNIL",
            "JUMPXEQKB",
            "JUMPXEQKN",
            "JUMPXEQKS",
        }:
            target = _jump_target(instruction)
            condition = self._conditional_body(instruction)
            if condition is None or target <= pc:
                self.out.line(f"-- {name} to L{target:04d}")
            elif not self._open_until(target, f"if {condition} then"):
                self.out.line(f"-- if {condition}, continue at L{target:04d}")
        elif name in {"JUMP", "JUMPBACK", "JUMPX", "CMPPROTO"}:
            target = _jump_target(instruction)
            self.out.line(f"-- {name.lower()} to L{target:04d}")
        elif name.startswith("FASTCALL"):
            self.out.line(f"-- optimized builtin call {name}")
        elif name == "CLOSEUPVALS":
            self.out.line(f"-- close upvalues from register {instruction.a}")
        else:
            self.out.line(f"-- unsupported {instruction.render()}")


def decompile_module(
    module: LuauBytecodeModule,
    options: dict[str, bool],
    filename: str | None,
) -> str:
    resolved = _Options.from_backend(options)
    out = _Emitter(resolved.semicolons)
    label = filename or "<bytecode>"
    out.line(f"-- LunaUX Next reconstructed output for {label}")
    out.line(
        "-- Exact reconstruction of some advanced patterns requires "
        "a compatible native backend."
    )
    out.line(
        f"-- Luau bytecode v{module.version}, type info v{module.types_version}, "
        f"{len(module.protos)} prototype(s)"
    )
    if module.trailing_bytes:
        out.line(
            f"-- Warning: {module.trailing_bytes} trailing byte(s) were not parsed"
        )
    out.line()

    names = _proto_names(module)
    for proto in module.protos:
        if proto.proto_id == module.main_proto_id:
            continue
        _FunctionLifter(module, proto, names, resolved, out).lift(as_function=True)

    out.line("-- Main prototype")
    _FunctionLifter(
        module,
        module.main_proto,
        names,
        resolved,
        out,
    ).lift(as_function=False)
    return out.render()


def _describe_operand(proto: LuauProto, instruction: DecodedInstruction) -> str:
    name = instruction.name
    if name in {"LOADK", "DUPTABLE", "DUPCLOSURE"}:
        return f" ; K{instruction.d}={_constant_expr(proto, instruction.d)}"
    if name == "LOADKX":
        index = instruction.aux if instruction.aux is not None else 0
        return f" ; K{instruction.aux}={_constant_expr(proto, index)}"
    if name in {
        "GETGLOBAL",
        "SETGLOBAL",
        "GETTABLEKS",
        "SETTABLEKS",
        "NAMECALL",
    }:
        index = instruction.aux if instruction.aux is not None else -1
        return f" ; key={_quote(_constant_string(proto, index) or '?')}"
    if name == "GETIMPORT":
        return f" ; import={_decode_import(proto, instruction.aux)}"
    control_ops = {"FORNPREP", "FORNLOOP", "FORGPREP", "FORGLOOP"}
    if name.startswith("JUMP") or name in control_ops:
        return f" ; target=L{_jump_target(instruction):04d}"
    return ""


def disassemble_module(module: LuauBytecodeModule, filename: str | None) -> str:
    lines = [
        f"; LunaUX Next disassembly for {filename or '<bytecode>'}",
        (
            f"; bytecode={module.version} types={module.types_version} "
            f"protos={len(module.protos)} main={module.main_proto_id}"
        ),
    ]
    for proto in module.protos:
        lines.extend(
            [
                "",
                (
                    f".proto {proto.proto_id} "
                    f"name={proto.debug_name or '<anonymous>'!r} "
                    f"params={proto.num_params} "
                    f"upvalues={proto.num_upvalues} "
                    f"stack={proto.max_stack_size}"
                ),
                f".line {proto.line_defined}",
            ]
        )
        for instruction in proto.instructions:
            line_number = (
                proto.line_info[instruction.pc]
                if instruction.pc < len(proto.line_info)
                else None
            )
            prefix = f"{line_number:5d} " if line_number is not None else "      "
            lines.append(
                prefix + instruction.render() + _describe_operand(proto, instruction)
            )
        if proto.constants:
            lines.append(".constants")
            for index, constant in enumerate(proto.constants):
                lines.append(
                    f"  K{index:<4} {constant.kind:<22} "
                    f"{_constant_expr(proto, index)}"
                )
    return "\n".join(lines).rstrip() + "\n"
