from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TypeAlias

from lunaux.backends.opcodes import DecodedInstruction, decode_words

ConstantScalar: TypeAlias = None | bool | int | float | str
ConstantValue: TypeAlias = (
    ConstantScalar
    | tuple[float, float, float, float]
    | tuple[int, ...]
    | tuple[tuple[int, int], ...]
    | tuple[int, int, tuple[int, ...]]
)

_MAX_COLLECTION_ITEMS = 1_000_000
_SUPPORTED_VERSIONS = range(3, 13)


class BytecodeFormatError(ValueError):
    """Raised when a serialized Luau bytecode container is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class LuauConstant:
    kind: str
    value: ConstantValue


@dataclass(frozen=True, slots=True)
class LocalInfo:
    name: str | None
    start_pc: int
    end_pc: int
    register: int


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

    @property
    def instructions(self) -> tuple[DecodedInstruction, ...]:
        return tuple(decode_words(self.code))


@dataclass(frozen=True, slots=True)
class LuauBytecodeModule:
    version: int
    types_version: int
    strings: tuple[str, ...]
    protos: tuple[LuauProto, ...]
    main_proto_id: int
    bytes_consumed: int
    trailing_bytes: int

    @property
    def main_proto(self) -> LuauProto:
        return self.protos[self.main_proto_id]


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.offset

    def fail(self, message: str) -> BytecodeFormatError:
        return BytecodeFormatError(f"{message} at byte offset 0x{self.offset:x}")

    def read_bytes(self, size: int) -> bytes:
        if size < 0 or size > self.remaining:
            raise self.fail(f"unexpected end of bytecode while reading {size} bytes")
        start = self.offset
        self.offset += size
        return self.data[start : start + size]

    def seek(self, offset: int) -> None:
        if offset < self.offset or offset > len(self.data):
            raise self.fail(f"invalid seek target 0x{offset:x}")
        self.offset = offset

    def read_u8(self) -> int:
        return self.read_bytes(1)[0]

    def read_u32(self) -> int:
        return struct.unpack("<I", self.read_bytes(4))[0]

    def read_i32(self) -> int:
        return struct.unpack("<i", self.read_bytes(4))[0]

    def read_f32(self) -> float:
        return struct.unpack("<f", self.read_bytes(4))[0]

    def read_f64(self) -> float:
        return struct.unpack("<d", self.read_bytes(8))[0]

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


def _read_string_ref(reader: _Reader, strings: tuple[str, ...]) -> str | None:
    string_id = reader.read_varuint()
    if string_id == 0:
        return None
    index = string_id - 1
    if index >= len(strings):
        raise reader.fail(f"string reference {string_id} is out of range")
    return strings[index]


def _read_constant(reader: _Reader, strings: tuple[str, ...]) -> LuauConstant:
    tag = reader.read_u8()
    if tag == 0:
        return LuauConstant("nil", None)
    if tag == 1:
        return LuauConstant("boolean", bool(reader.read_u8()))
    if tag == 2:
        return LuauConstant("number", reader.read_f64())
    if tag == 3:
        return LuauConstant("string", _read_string_ref(reader, strings) or "")
    if tag == 4:
        return LuauConstant("import", reader.read_u32())
    if tag == 5:
        key_count = reader.read_count("table key")
        return LuauConstant("table", tuple(reader.read_varuint() for _ in range(key_count)))
    if tag == 6:
        return LuauConstant("closure", reader.read_varuint())
    if tag == 7:
        return LuauConstant(
            "vector",
            (reader.read_f32(), reader.read_f32(), reader.read_f32(), reader.read_f32()),
        )
    if tag == 8:
        key_count = reader.read_count("table-with-constants key")
        pairs = tuple((reader.read_varuint(), reader.read_i32()) for _ in range(key_count))
        return LuauConstant("table_with_constants", pairs)
    if tag == 9:
        negative = bool(reader.read_u8())
        magnitude = reader.read_varuint64()
        return LuauConstant("integer", -magnitude if negative else magnitude)
    if tag == 10:
        class_name_constant = reader.read_varuint()
        property_count = reader.read_count("class property")
        method_count = reader.read_count("class method")
        member_count = property_count + method_count
        if member_count > _MAX_COLLECTION_ITEMS:
            raise reader.fail("class member count exceeds safety limit")
        members = tuple(reader.read_varuint() for _ in range(member_count))
        return LuauConstant(
            "class_shape",
            (class_name_constant, property_count, members),
        )
    if tag == 11:
        return LuauConstant(
            "vectord",
            (reader.read_f64(), reader.read_f64(), reader.read_f64(), reader.read_f64()),
        )
    raise reader.fail(f"unsupported constant tag {tag}")


def _read_line_info(reader: _Reader, code_size: int) -> tuple[int, ...]:
    if not reader.read_u8():
        return ()
    gap_log2 = reader.read_u8()
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
) -> tuple[tuple[LocalInfo, ...], tuple[str | None, ...]]:
    if not reader.read_u8():
        return (), ()
    local_count = reader.read_count("local")
    locals_result = tuple(
        LocalInfo(
            name=_read_string_ref(reader, strings),
            start_pc=reader.read_varuint(),
            end_pc=reader.read_varuint(),
            register=reader.read_u8(),
        )
        for _ in range(local_count)
    )
    upvalue_count = reader.read_count("upvalue name")
    if upvalue_count != num_upvalues:
        raise reader.fail(
            f"debug upvalue count {upvalue_count} does not match prototype count {num_upvalues}"
        )
    upvalues = tuple(_read_string_ref(reader, strings) for _ in range(upvalue_count))
    return locals_result, upvalues


def _read_proto(
    reader: _Reader,
    strings: tuple[str, ...],
    version: int,
    types_version: int,
    proto_id: int,
) -> LuauProto:
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
    flags = 0
    type_info = b""
    if version >= 4:
        flags = reader.read_u8()
        type_size = reader.read_count("type info")
        type_info = reader.read_bytes(type_size)

    code_count = reader.read_count("instruction")
    code = tuple(reader.read_u32() for _ in range(code_count))

    constant_count = reader.read_count("constant")
    constants = tuple(_read_constant(reader, strings) for _ in range(constant_count))

    child_count = reader.read_count("child prototype")
    child_proto_ids = tuple(reader.read_varuint() for _ in range(child_count))

    line_defined = reader.read_varuint()
    debug_name = _read_string_ref(reader, strings)
    line_info = _read_line_info(reader, code_count)
    locals_result, upvalue_names = _read_debug_info(reader, strings, num_upvalues)

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
    )


def parse_bytecode(data: bytes) -> LuauBytecodeModule:
    """Parse a serialized Luau bytecode container using the public VM format."""

    reader = _Reader(data)
    if not data:
        raise BytecodeFormatError("bytecode is empty")
    version = reader.read_u8()
    if version == 0:
        message = reader.read_bytes(reader.remaining).decode("utf-8", errors="replace")
        raise BytecodeFormatError(f"compiler returned an error blob: {message}")
    if version not in _SUPPORTED_VERSIONS:
        raise reader.fail(f"unsupported Luau bytecode version {version}")

    types_version = reader.read_u8() if version >= 4 else 0
    if version >= 4 and types_version not in (1, 2, 3):
        raise reader.fail(f"unsupported Luau type information version {types_version}")

    string_count = reader.read_count("string")
    strings = tuple(
        reader.read_bytes(reader.read_count("string byte")).decode("utf-8", errors="replace")
        for _ in range(string_count)
    )

    if types_version == 3:
        while True:
            userdata_index = reader.read_u8()
            if userdata_index == 0:
                break
            _read_string_ref(reader, strings)

    proto_count = reader.read_count("prototype")
    protos = tuple(
        _read_proto(reader, strings, version, types_version, proto_id)
        for proto_id in range(proto_count)
    )
    main_proto_id = reader.read_varuint()
    if main_proto_id >= len(protos):
        raise reader.fail(f"main prototype id {main_proto_id} is out of range")

    return LuauBytecodeModule(
        version=version,
        types_version=types_version,
        strings=strings,
        protos=protos,
        main_proto_id=main_proto_id,
        bytes_consumed=reader.offset,
        trailing_bytes=reader.remaining,
    )
