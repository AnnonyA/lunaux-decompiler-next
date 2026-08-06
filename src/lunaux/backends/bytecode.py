from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import TypeAlias, cast

from lunaux.backends.opcode_encoding import (
    candidate_opcode_multipliers,
    decode_multiplicative_opcode_words,
)
from lunaux.backends.opcodes import (
    DecodedInstruction,
    decode_words,
    get_jump_target,
    opcode_supported,
)

ConstantScalar: TypeAlias = bool | int | float | str | None
VectorConstant: TypeAlias = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class ClassShapeConstant:
    class_name_constant: int
    property_name_constants: tuple[int, ...]
    method_name_constants: tuple[int, ...]


ConstantValue: TypeAlias = (
    ConstantScalar
    | VectorConstant
    | tuple[int, ...]
    | tuple[tuple[int, int], ...]
    | ClassShapeConstant
)

CONSTANT_TAG_NAMES = (
    "NIL",
    "BOOLEAN",
    "NUMBER",
    "STRING",
    "IMPORT",
    "TABLE",
    "CLOSURE",
    "VECTOR",
    "TABLE_WITH_CONSTANTS",
    "INTEGER",
    "CLASS_SHAPE",
    "VECTORD",
)

_MAX_COLLECTION_ITEMS = 1_000_000
_STANDARD_VERSIONS = frozenset(range(3, 14))
_WIP_VERSIONS = frozenset({100})
SUPPORTED_BYTECODE_VERSIONS = _STANDARD_VERSIONS | _WIP_VERSIONS

_TYPE_NAMES = {
    0: "nil",
    1: "boolean",
    2: "number",
    3: "string",
    4: "table",
    5: "function",
    6: "thread",
    7: "userdata",
    8: "vector",
    9: "buffer",
    10: "integer",
    15: "any",
}


class BytecodeFormatError(ValueError):
    """Raised when a serialized Luau bytecode container is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class LuauConstant:
    kind: str
    value: ConstantValue
    tag: int


@dataclass(frozen=True, slots=True)
class LocalInfo:
    name: str | None
    start_pc: int
    end_pc: int
    register: int


@dataclass(frozen=True, slots=True)
class TypedLocalInfo:
    type_tag: int
    register: int
    start_pc: int
    end_pc: int


@dataclass(frozen=True, slots=True)
class LuauProto:
    proto_id: int
    max_stack_size: int
    num_params: int
    num_upvalues: int
    is_vararg: bool
    flags: int
    type_info: bytes
    code: tuple[int, ...]
    constants: tuple[LuauConstant, ...]
    child_proto_ids: tuple[int, ...]
    line_defined: int
    debug_name: str | None
    line_info: tuple[int, ...]
    locals: tuple[LocalInfo, ...]
    upvalue_names: tuple[str | None, ...]
    feedback_pcs: tuple[int, ...]
    cost: int | None
    function_type_info: bytes = b""
    upvalue_types: tuple[int, ...] = ()
    typed_locals: tuple[TypedLocalInfo, ...] = ()
    type_info_trailing: bytes = b""
    serialized_size: int | None = None

    @property
    def instructions(self) -> tuple[DecodedInstruction, ...]:
        return tuple(decode_words(self.code))

    @property
    def flag_names(self) -> tuple[str, ...]:
        names = (
            (1 << 0, "native_module"),
            (1 << 1, "native_cold"),
            (1 << 2, "native_function"),
            (1 << 3, "inlinable"),
            (1 << 4, "uses_export"),
        )
        return tuple(name for bit, name in names if self.flags & bit)


@dataclass(frozen=True, slots=True)
class LuauBytecodeModule:
    version: int
    types_version: int
    strings: tuple[str, ...]
    protos: tuple[LuauProto, ...]
    main_proto_id: int
    bytes_consumed: int
    trailing_bytes: int
    userdata_types: tuple[tuple[int, str], ...] = ()
    opcode_encoding: str | None = None

    @property
    def main_proto(self) -> LuauProto:
        return self.protos[self.main_proto_id]

    @property
    def userdata_type_map(self) -> dict[int, str]:
        return dict(self.userdata_types)


class _Reader:
    def __init__(self, data: bytes, *, base_offset: int = 0) -> None:
        self.data = data
        self.offset = 0
        self.base_offset = base_offset

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def fail(self, message: str) -> BytecodeFormatError:
        absolute = self.base_offset + self.offset
        return BytecodeFormatError(f"{message} at byte offset 0x{absolute:x}")

    def read_bytes(self, size: int) -> bytes:
        if size < 0 or size > self.remaining:
            raise self.fail(f"unexpected end of bytecode while reading {size} bytes")
        start = self.offset
        self.offset += size
        return self.data[start : start + size]

    def seek(self, offset: int) -> None:
        if offset < self.offset or offset > len(self.data):
            raise self.fail(f"invalid seek target 0x{self.base_offset + offset:x}")
        self.offset = offset

    def read_u8(self) -> int:
        return self.read_bytes(1)[0]

    def read_u32(self) -> int:
        return int(struct.unpack("<I", self.read_bytes(4))[0])

    def read_i32(self) -> int:
        return int(struct.unpack("<i", self.read_bytes(4))[0])

    def read_f32(self) -> float:
        return float(struct.unpack("<f", self.read_bytes(4))[0])

    def read_f64(self) -> float:
        return float(struct.unpack("<d", self.read_bytes(8))[0])

    def read_varuint(self) -> int:
        result = 0
        shift = 0
        for _ in range(5):
            byte = self.read_u8()
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
            shift += 7
        raise self.fail("32-bit variable integer is too long")

    def read_varuint64(self) -> int:
        result = 0
        shift = 0
        for _ in range(10):
            byte = self.read_u8()
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
            shift += 7
        raise self.fail("64-bit variable integer is too long")

    def read_count(self, label: str) -> int:
        count = self.read_varuint()
        if count > _MAX_COLLECTION_ITEMS:
            raise self.fail(f"{label} count {count} exceeds safety limit")
        return count


def is_supported_bytecode_version(version: int) -> bool:
    return version in SUPPORTED_BYTECODE_VERSIONS


def format_type_tag(
    tag: int,
    userdata_types: dict[int, str] | None = None,
) -> str:
    optional = bool(tag & 0x80)
    base = tag & 0x7F
    if 64 <= base < 96:
        userdata_index = base - 64 + 1
        name = (userdata_types or {}).get(userdata_index, f"userdata_{userdata_index}")
    else:
        name = _TYPE_NAMES.get(base, f"type_{base}")
    return f"{name}?" if optional else name


def _read_string_ref(reader: _Reader, strings: tuple[str, ...]) -> str | None:
    string_id = reader.read_varuint()
    if string_id == 0:
        return None
    index = string_id - 1
    if index >= len(strings):
        raise reader.fail(f"string reference {string_id} is out of range")
    return strings[index]


def _constant_min_version(tag: int) -> int:
    return {
        7: 5,
        8: 7,
        9: 8,
        10: 10,
        11: 13,
    }.get(tag, 3)


def _read_constant(
    reader: _Reader,
    strings: tuple[str, ...],
    version: int,
) -> LuauConstant:
    tag = reader.read_u8()
    minimum = _constant_min_version(tag)
    if minimum == 13 and version not in (13, 100):
        raise reader.fail(f"constant tag {tag} requires Luau bytecode v13")
    if minimum == 10 and version != 100 and version < 10:
        raise reader.fail(f"constant tag {tag} requires Luau bytecode v10")
    if minimum not in (10, 13) and version != 100 and version < minimum:
        raise reader.fail(
            f"constant tag {tag} requires Luau bytecode v{minimum}"
        )

    if tag == 0:
        return LuauConstant("nil", None, tag)
    if tag == 1:
        return LuauConstant("boolean", bool(reader.read_u8()), tag)
    if tag == 2:
        return LuauConstant("number", reader.read_f64(), tag)
    if tag == 3:
        return LuauConstant("string", _read_string_ref(reader, strings) or "", tag)
    if tag == 4:
        return LuauConstant("import", reader.read_u32(), tag)
    if tag == 5:
        key_count = reader.read_count("table key")
        value = tuple(reader.read_varuint() for _ in range(key_count))
        return LuauConstant("table", value, tag)
    if tag == 6:
        return LuauConstant("closure", reader.read_varuint(), tag)
    if tag == 7:
        vector = (
            reader.read_f32(),
            reader.read_f32(),
            reader.read_f32(),
            reader.read_f32(),
        )
        return LuauConstant("vector", vector, tag)
    if tag == 8:
        key_count = reader.read_count("table-with-constants key")
        pairs = tuple(
            (reader.read_varuint(), reader.read_i32()) for _ in range(key_count)
        )
        return LuauConstant("table_with_constants", pairs, tag)
    if tag == 9:
        negative = bool(reader.read_u8())
        magnitude = reader.read_varuint64()
        return LuauConstant("integer", -magnitude if negative else magnitude, tag)
    if tag == 10:
        class_name_constant = reader.read_varuint()
        property_count = reader.read_count("class property")
        method_count = reader.read_count("class method")
        member_count = property_count + method_count
        if member_count > _MAX_COLLECTION_ITEMS:
            raise reader.fail("class member count exceeds safety limit")
        properties = tuple(reader.read_varuint() for _ in range(property_count))
        methods = tuple(reader.read_varuint() for _ in range(method_count))
        shape = ClassShapeConstant(class_name_constant, properties, methods)
        return LuauConstant("class_shape", shape, tag)
    if tag == 11:
        vector = (
            reader.read_f64(),
            reader.read_f64(),
            reader.read_f64(),
            reader.read_f64(),
        )
        return LuauConstant("vectord", vector, tag)
    raise reader.fail(f"unsupported constant tag {tag}")


def _read_line_info(reader: _Reader, code_size: int) -> tuple[int, ...]:
    if not reader.read_u8():
        return ()
    gap_log2 = reader.read_u8()
    if gap_log2 > 31:
        raise reader.fail(f"line info gap log2 {gap_log2} is invalid")
    relative: list[int] = []
    last_offset = 0
    for _ in range(code_size):
        last_offset = (last_offset + reader.read_u8()) & 0xFF
        relative.append(last_offset)
    intervals = ((code_size - 1) >> gap_log2) + 1 if code_size else 0
    absolute: list[int] = []
    last_line = 0
    for _ in range(intervals):
        last_line += reader.read_i32()
        absolute.append(last_line)
    return tuple(
        absolute[pc >> gap_log2] + relative[pc]
        for pc in range(code_size)
    )


def _read_debug_info(
    reader: _Reader,
    strings: tuple[str, ...],
    num_upvalues: int,
    code_size: int,
    max_stack_size: int,
) -> tuple[tuple[LocalInfo, ...], tuple[str | None, ...]]:
    if not reader.read_u8():
        return (), tuple(None for _ in range(num_upvalues))
    local_count = reader.read_count("local")
    locals_values: list[LocalInfo] = []
    for _ in range(local_count):
        item = LocalInfo(
            name=_read_string_ref(reader, strings),
            start_pc=reader.read_varuint(),
            end_pc=reader.read_varuint(),
            register=reader.read_u8(),
        )
        if item.start_pc > item.end_pc or item.end_pc > code_size:
            raise reader.fail(
                f"local range {item.start_pc}..{item.end_pc} is outside code"
            )
        if item.register >= max_stack_size:
            raise reader.fail(
                f"local register {item.register} exceeds stack size {max_stack_size}"
            )
        locals_values.append(item)

    upvalue_count = reader.read_count("upvalue name")
    if upvalue_count > num_upvalues:
        raise reader.fail(
            f"debug upvalue count {upvalue_count} exceeds prototype count "
            f"{num_upvalues}"
        )
    upvalues = [
        _read_string_ref(reader, strings) for _ in range(upvalue_count)
    ]
    upvalues.extend(None for _ in range(num_upvalues - upvalue_count))
    return tuple(locals_values), tuple(upvalues)


def _parse_type_info(
    raw: bytes,
    types_version: int,
    *,
    base_offset: int,
    max_stack_size: int,
    code_size: int,
) -> tuple[bytes, tuple[int, ...], tuple[TypedLocalInfo, ...], bytes]:
    if not raw:
        return b"", (), (), b""
    if types_version == 1:
        return raw, (), (), b""

    reader = _Reader(raw, base_offset=base_offset)
    function_size = reader.read_count("function type")
    upvalue_count = reader.read_count("typed upvalue")
    local_count = reader.read_count("typed local")
    function_type_info = reader.read_bytes(function_size)
    upvalue_types = tuple(reader.read_u8() for _ in range(upvalue_count))

    typed_locals: list[TypedLocalInfo] = []
    for _ in range(local_count):
        type_tag = reader.read_u8()
        register = reader.read_u8()
        start_pc = reader.read_varuint()
        span = reader.read_varuint()
        end_pc = start_pc + span
        if register >= max_stack_size:
            raise reader.fail(
                f"typed local register {register} exceeds stack size {max_stack_size}"
            )
        if end_pc > code_size:
            raise reader.fail(
                f"typed local range {start_pc}..{end_pc} is outside code"
            )
        typed_locals.append(
            TypedLocalInfo(
                type_tag=type_tag,
                register=register,
                start_pc=start_pc,
                end_pc=end_pc,
            )
        )
    trailing = reader.read_bytes(reader.remaining)
    return function_type_info, upvalue_types, tuple(typed_locals), trailing


def _read_proto(
    reader: _Reader,
    strings: tuple[str, ...],
    version: int,
    types_version: int,
    proto_id: int,
) -> LuauProto:
    proto_size: int | None = None
    proto_end: int | None = None
    if version >= 12:
        proto_size = reader.read_varuint()
        proto_end = reader.offset + proto_size
        if proto_end > len(reader.data):
            raise reader.fail("prototype size exceeds bytecode length")

    max_stack_size = reader.read_u8()
    num_params = reader.read_u8()
    num_upvalues = reader.read_u8()
    is_vararg = bool(reader.read_u8())
    if num_params > max_stack_size:
        raise reader.fail(
            f"parameter count {num_params} exceeds stack size {max_stack_size}"
        )

    flags = 0
    type_info = b""
    type_info_offset = reader.offset
    if version >= 4:
        flags = reader.read_u8()
        type_size = reader.read_count("type info")
        type_info_offset = reader.base_offset + reader.offset
        type_info = reader.read_bytes(type_size)

    code_count = reader.read_count("instruction")
    code = tuple(reader.read_u32() for _ in range(code_count))

    (
        function_type_info,
        upvalue_types,
        typed_locals,
        type_info_trailing,
    ) = _parse_type_info(
        type_info,
        types_version,
        base_offset=type_info_offset,
        max_stack_size=max_stack_size,
        code_size=code_count,
    )

    constant_count = reader.read_count("constant")
    constants = tuple(
        _read_constant(reader, strings, version) for _ in range(constant_count)
    )

    child_count = reader.read_count("child prototype")
    child_proto_ids = tuple(reader.read_varuint() for _ in range(child_count))

    line_defined = reader.read_varuint()
    debug_name = _read_string_ref(reader, strings)
    line_info = _read_line_info(reader, code_count)
    locals_result, upvalue_names = _read_debug_info(
        reader,
        strings,
        num_upvalues,
        code_count,
        max_stack_size,
    )

    feedback_pcs: tuple[int, ...] = ()
    if version >= 11:
        feedback_count = reader.read_count("feedback slot")
        feedback_values: list[int] = []
        for _ in range(feedback_count):
            slot_type = reader.read_u8()
            if slot_type != 0:
                raise reader.fail(f"unsupported feedback slot type {slot_type}")
            feedback_values.append(reader.read_varuint())
        feedback_pcs = tuple(feedback_values)

    cost: int | None = None
    if version >= 12 and flags & (1 << 3):
        cost = reader.read_varuint64()

    if proto_end is not None:
        if reader.offset > proto_end:
            raise reader.fail("prototype fields exceed declared prototype size")
        reader.seek(proto_end)

    return LuauProto(
        proto_id=proto_id,
        max_stack_size=max_stack_size,
        num_params=num_params,
        num_upvalues=num_upvalues,
        is_vararg=is_vararg,
        flags=flags,
        type_info=type_info,
        code=code,
        constants=constants,
        child_proto_ids=child_proto_ids,
        line_defined=line_defined,
        debug_name=debug_name,
        line_info=line_info,
        locals=locals_result,
        upvalue_names=upvalue_names,
        feedback_pcs=feedback_pcs,
        cost=cost,
        function_type_info=function_type_info,
        upvalue_types=upvalue_types,
        typed_locals=typed_locals,
        type_info_trailing=type_info_trailing,
        serialized_size=proto_size,
    )


def _require_constant(
    proto: LuauProto,
    index: int,
    instruction: DecodedInstruction,
    kinds: frozenset[str] | None = None,
) -> LuauConstant:
    if index < 0 or index >= len(proto.constants):
        raise BytecodeFormatError(
            f"prototype {proto.proto_id} instruction {instruction.name} at word "
            f"{instruction.pc} references constant {index}, but only "
            f"{len(proto.constants)} constants exist"
        )
    constant = proto.constants[index]
    if kinds is not None and constant.kind not in kinds:
        expected = ", ".join(sorted(kinds))
        raise BytecodeFormatError(
            f"prototype {proto.proto_id} instruction {instruction.name} at word "
            f"{instruction.pc} requires constant kind {expected}; got "
            f"{constant.kind}"
        )
    return constant


def _validate_constant_graph(proto: LuauProto, proto_count: int) -> None:
    for index, constant in enumerate(proto.constants):
        value = constant.value
        if constant.kind == "closure":
            if not isinstance(value, int) or not 0 <= value < proto_count:
                raise BytecodeFormatError(
                    f"prototype {proto.proto_id} closure constant K{index} "
                    f"references invalid prototype {value}"
                )
        elif constant.kind == "table" and isinstance(value, tuple):
            keys = cast(tuple[int, ...], value)
            for key in keys:
                if not isinstance(key, int) or not 0 <= key < len(proto.constants):
                    raise BytecodeFormatError(
                        f"prototype {proto.proto_id} table constant K{index} "
                        f"references invalid key constant {key}"
                    )
        elif constant.kind == "table_with_constants" and isinstance(value, tuple):
            pairs = cast(tuple[tuple[int, int], ...], value)
            for key, item in pairs:
                if not 0 <= key < len(proto.constants):
                    raise BytecodeFormatError(
                        f"prototype {proto.proto_id} table constant K{index} "
                        f"references invalid key constant {key}"
                    )
                if item >= len(proto.constants):
                    raise BytecodeFormatError(
                        f"prototype {proto.proto_id} table constant K{index} "
                        f"references invalid value constant {item}"
                    )
        elif constant.kind == "class_shape" and isinstance(
            value, ClassShapeConstant
        ):
            members = (
                value.class_name_constant,
                *value.property_name_constants,
                *value.method_name_constants,
            )
            for member in members:
                if not 0 <= member < len(proto.constants):
                    raise BytecodeFormatError(
                        f"prototype {proto.proto_id} class shape K{index} "
                        f"references invalid string constant {member}"
                    )
                target = proto.constants[member]
                if target.kind != "string":
                    raise BytecodeFormatError(
                        f"prototype {proto.proto_id} class shape K{index} "
                        f"references non-string constant K{member}"
                    )


def _validate_instruction_constants(
    proto: LuauProto,
    instruction: DecodedInstruction,
) -> None:
    name = instruction.name
    if name in {"LOADK", "DUPTABLE", "DUPCLOSURE"}:
        kinds = None
        if name == "DUPTABLE":
            kinds = frozenset({"table", "table_with_constants"})
        elif name == "DUPCLOSURE":
            kinds = frozenset({"closure"})
        _require_constant(proto, instruction.d, instruction, kinds)
    elif name == "GETIMPORT":
        _require_constant(
            proto,
            instruction.d,
            instruction,
            frozenset({"import"}),
        )
    elif name == "LOADKX":
        _require_constant(proto, instruction.aux or 0, instruction)
    elif name in {
        "GETGLOBAL",
        "SETGLOBAL",
        "GETTABLEKS",
        "SETTABLEKS",
        "NAMECALL",
        "NEWCLASSMEMBER",
    }:
        _require_constant(
            proto,
            instruction.aux if instruction.aux is not None else -1,
            instruction,
            frozenset({"string"}),
        )
    elif name in {"GETUDATAKS", "SETUDATAKS", "NAMECALLUDATA"}:
        index = (instruction.aux or 0) & 0xFFFF
        _require_constant(proto, index, instruction, frozenset({"string"}))
    elif name in {
        "ADDK",
        "SUBK",
        "MULK",
        "DIVK",
        "MODK",
        "POWK",
        "IDIVK",
    }:
        _require_constant(
            proto,
            instruction.c,
            instruction,
            frozenset({"number", "integer"}),
        )
    elif name in {"ANDK", "ORK"}:
        _require_constant(proto, instruction.c, instruction)
    elif name in {"SUBRK", "DIVRK"}:
        _require_constant(
            proto,
            instruction.b,
            instruction,
            frozenset({"number", "integer"}),
        )
    elif name == "FASTCALL2K":
        _require_constant(proto, instruction.aux or 0, instruction)
    elif name in {"JUMPXEQKN", "JUMPXEQKS"}:
        kinds = (
            frozenset({"number", "integer"})
            if name == "JUMPXEQKN"
            else frozenset({"string"})
        )
        _require_constant(proto, (instruction.aux or 0) & 0xFFFFFF, instruction, kinds)
    elif name == "NEWCLASS":
        _require_constant(
            proto,
            instruction.aux if instruction.aux is not None else -1,
            instruction,
            frozenset({"class_shape"}),
        )


def _validate_proto_code(
    proto: LuauProto,
    version: int,
    protos: tuple[LuauProto, ...],
) -> None:
    try:
        instructions = decode_words(
            proto.code,
            strict=True,
            bytecode_version=version,
        )
    except ValueError as exc:
        raise BytecodeFormatError(
            f"prototype {proto.proto_id} has invalid instructions: {exc}"
        ) from exc

    instruction_pcs = {instruction.pc for instruction in instructions}
    valid_targets = instruction_pcs | {len(proto.code)}
    instruction_by_pc = {instruction.pc: instruction for instruction in instructions}

    for instruction in instructions:
        if not opcode_supported(instruction.opcode, version):
            raise BytecodeFormatError(
                f"prototype {proto.proto_id} uses {instruction.name}, which is "
                f"not supported by bytecode v{version}"
            )
        target = get_jump_target(instruction)
        if target is not None and target not in valid_targets:
            raise BytecodeFormatError(
                f"prototype {proto.proto_id} instruction {instruction.name} at "
                f"word {instruction.pc} jumps into invalid word {target}"
            )
        _validate_instruction_constants(proto, instruction)

        if instruction.name == "NEWCLOSURE":
            child_slot = instruction.d
            if not 0 <= child_slot < len(proto.child_proto_ids):
                raise BytecodeFormatError(
                    f"prototype {proto.proto_id} NEWCLOSURE at word "
                    f"{instruction.pc} references child slot {child_slot}"
                )
            child_id = proto.child_proto_ids[child_slot]
            if not 0 <= child_id < len(protos):
                raise BytecodeFormatError(
                    f"prototype {proto.proto_id} references invalid child "
                    f"prototype {child_id}"
                )
            expected = protos[child_id].num_upvalues
            capture_pc = instruction.pc + 1
            for capture_index in range(expected):
                capture = instruction_by_pc.get(capture_pc + capture_index)
                if capture is None or capture.name != "CAPTURE":
                    raise BytecodeFormatError(
                        f"prototype {proto.proto_id} NEWCLOSURE at word "
                        f"{instruction.pc} requires {expected} CAPTURE "
                        "instruction(s)"
                    )

        if instruction.name == "CALLFB" and instruction.aux != 0xFFFFFFFF:
            slot = instruction.aux if instruction.aux is not None else -1
            if not 0 <= slot < len(proto.feedback_pcs):
                raise BytecodeFormatError(
                    f"prototype {proto.proto_id} CALLFB at word {instruction.pc} "
                    f"references invalid feedback slot {slot}"
                )
        if instruction.name == "CMPPROTO":
            proto_id = instruction.aux if instruction.aux is not None else -1
            if not 0 <= proto_id < len(protos):
                raise BytecodeFormatError(
                    f"prototype {proto.proto_id} CMPPROTO at word "
                    f"{instruction.pc} references invalid prototype {proto_id}"
                )

    for child_id in proto.child_proto_ids:
        if not 0 <= child_id < len(protos):
            raise BytecodeFormatError(
                f"prototype {proto.proto_id} references invalid child "
                f"prototype {child_id}"
            )
    for pc in proto.feedback_pcs:
        if pc not in instruction_pcs:
            raise BytecodeFormatError(
                f"prototype {proto.proto_id} feedback slot references invalid "
                f"instruction word {pc}"
            )


def _validate_module(module: LuauBytecodeModule) -> None:
    for proto in module.protos:
        _validate_constant_graph(proto, len(module.protos))
        _validate_proto_code(proto, module.version, module.protos)


def _contains_nonstandard_opcode_stream(module: LuauBytecodeModule) -> bool:
    for proto in module.protos:
        try:
            decode_words(
                proto.code,
                strict=True,
                bytecode_version=module.version,
            )
        except ValueError:
            return True
    return False


def _module_with_opcode_multiplier(
    module: LuauBytecodeModule,
    multiplier: int,
) -> LuauBytecodeModule:
    protos = tuple(
        replace(
            proto,
            code=decode_multiplicative_opcode_words(
                proto.code,
                multiplier,
                bytecode_version=module.version,
            ),
        )
        for proto in module.protos
    )
    return replace(
        module,
        protos=protos,
        opcode_encoding=f"multiplicative:{multiplier}",
    )


def _recover_opcode_encoding(
    module: LuauBytecodeModule,
) -> LuauBytecodeModule | None:
    if not _contains_nonstandard_opcode_stream(module):
        return None

    inferred: list[LuauBytecodeModule] = []
    for multiplier in candidate_opcode_multipliers():
        try:
            candidate = _module_with_opcode_multiplier(module, multiplier)
            _validate_module(candidate)
        except (BytecodeFormatError, ValueError):
            continue

        if multiplier == 227:
            return candidate
        inferred.append(candidate)
        if len(inferred) > 1:
            return None

    return inferred[0] if len(inferred) == 1 else None


def parse_bytecode(data: bytes) -> LuauBytecodeModule:
    """Parse and validate a serialized Luau bytecode container."""

    reader = _Reader(data)
    if not data:
        raise BytecodeFormatError("bytecode is empty")
    version = reader.read_u8()
    if version == 0:
        message = reader.read_bytes(reader.remaining).decode(
            "utf-8",
            errors="replace",
        )
        raise BytecodeFormatError(f"compiler returned an error blob: {message}")
    if not is_supported_bytecode_version(version):
        raise reader.fail(f"unsupported Luau bytecode version {version}")

    types_version = reader.read_u8() if version >= 4 else 0
    if version >= 4 and types_version not in (1, 2, 3):
        raise reader.fail(
            f"unsupported Luau type information version {types_version}"
        )

    string_count = reader.read_count("string")
    strings = tuple(
        reader.read_bytes(reader.read_count("string byte")).decode(
            "utf-8",
            errors="replace",
        )
        for _ in range(string_count)
    )

    userdata_types: list[tuple[int, str]] = []
    if types_version == 3:
        seen_indices: set[int] = set()
        while True:
            userdata_index = reader.read_u8()
            if userdata_index == 0:
                break
            if userdata_index in seen_indices:
                raise reader.fail(
                    f"duplicate userdata type index {userdata_index}"
                )
            seen_indices.add(userdata_index)
            name = _read_string_ref(reader, strings)
            if name is None:
                raise reader.fail(
                    f"userdata type index {userdata_index} has no name"
                )
            userdata_types.append((userdata_index, name))

    proto_count = reader.read_count("prototype")
    protos = tuple(
        _read_proto(reader, strings, version, types_version, proto_id)
        for proto_id in range(proto_count)
    )
    main_proto_id = reader.read_varuint()
    if main_proto_id >= len(protos):
        raise reader.fail(f"main prototype id {main_proto_id} is out of range")

    module = LuauBytecodeModule(
        version=version,
        types_version=types_version,
        strings=strings,
        protos=protos,
        main_proto_id=main_proto_id,
        bytes_consumed=reader.offset,
        trailing_bytes=reader.remaining,
        userdata_types=tuple(userdata_types),
    )
    try:
        _validate_module(module)
    except BytecodeFormatError:
        recovered = _recover_opcode_encoding(module)
        if recovered is None:
            raise
        module = recovered
    return module
