from __future__ import annotations

import struct

import pytest

from lunaux.backends.bytecode import (
    BytecodeFormatError,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
    parse_bytecode,
)
from lunaux.backends.lifter import decompile_module, disassemble_module
from lunaux.backends.opcodes import (
    decode_words,
    get_jump_target,
    opcode_count,
    opcode_name,
)
from lunaux.backends.reconstructed import ReconstructedBackend


def _varuint(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        result.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(result)


def _abc(opcode: int, a: int, b: int, c: int) -> int:
    return opcode | (a << 8) | (b << 16) | (c << 24)


def _ad(opcode: int, a: int, d: int) -> int:
    return opcode | (a << 8) | ((d & 0xFFFF) << 16)


def _sample_container() -> bytes:
    # print("hello") encoded as one Luau v4 prototype.
    strings = (b"print", b"hello", b"main")
    result = bytearray((4, 2))
    result += _varuint(len(strings))
    for value in strings:
        result += _varuint(len(value)) + value

    result += _varuint(1)
    result += bytes((2, 0, 0, 0, 0))
    result += _varuint(0)

    code = (
        _abc(7, 0, 0, 0),
        0,
        _ad(5, 1, 1),
        _abc(21, 0, 2, 1),
        _abc(22, 0, 1, 0),
    )
    result += _varuint(len(code))
    result += b"".join(struct.pack("<I", word) for word in code)

    result += _varuint(2)
    result += bytes((3,)) + _varuint(1)
    result += bytes((3,)) + _varuint(2)
    result += _varuint(0)
    result += _varuint(1)
    result += _varuint(3)
    result += bytes((0, 0))
    result += _varuint(0)
    return bytes(result)


def _modern_container(
    version: int,
    code: tuple[int, ...],
    constants: bytes,
    *,
    strings: tuple[bytes, ...] = (b"main",),
    flags: int = 0,
    type_info: bytes = b"",
) -> bytes:
    result = bytearray((version, 3))
    result += _varuint(len(strings))
    for value in strings:
        result += _varuint(len(value)) + value
    result += b"\x00"  # userdata type mapping terminator
    result += _varuint(1)

    proto = bytearray((4, 0, 0, 0, flags))
    proto += _varuint(len(type_info)) + type_info
    proto += _varuint(len(code))
    proto += b"".join(struct.pack("<I", word) for word in code)
    proto += constants
    proto += _varuint(0)  # children
    proto += _varuint(1)  # line defined
    proto += _varuint(1)  # debug name
    proto += b"\x00"  # no line info
    proto += b"\x00"  # no debug info
    proto += _varuint(0)  # feedback slots
    if flags & (1 << 3):
        proto += _varuint(12)

    result += _varuint(len(proto))
    result += proto
    result += _varuint(0)
    return bytes(result)


def test_parser_reads_strings_constants_and_main_proto() -> None:
    module = parse_bytecode(_sample_container())
    assert module.version == 4
    assert module.types_version == 2
    assert module.main_proto.debug_name == "main"
    assert module.main_proto.constants[0].value == "print"
    assert module.main_proto.constants[1].value == "hello"
    assert len(module.main_proto.instructions) == 4
    assert module.trailing_bytes == 0


def test_python_engine_reconstructs_common_call() -> None:
    module = parse_bytecode(_sample_container())
    source = decompile_module(module, {}, "Example")
    assert "local print = print" in source
    assert 'local v1 = "hello"' not in source
    assert 'print("hello")' in source


def test_semicolon_option_is_applied() -> None:
    source = ReconstructedBackend().decompile(
        _sample_container(),
        {"Semicolons": True},
        "Example",
    )
    statements = [line.strip() for line in source.splitlines() if line.strip()]
    assert statements
    assert all(line.endswith(";") for line in statements)
    assert any('"hello";' in line for line in statements)


def test_disassembly_resolves_constant_names() -> None:
    text = disassemble_module(parse_bytecode(_sample_container()), "Example")
    assert 'key="print"' in text
    assert 'K1="hello"' in text
    assert ".proto 0" in text


def test_malformed_container_reports_offset() -> None:
    with pytest.raises(BytecodeFormatError, match="offset"):
        parse_bytecode(bytes((4, 2, 0x80)))


def test_raw_words_still_get_lifted() -> None:
    bytecode = struct.pack("<II", _ad(4, 0, 42), _abc(22, 0, 2, 0))
    source = ReconstructedBackend().decompile(bytecode, {}, "raw")
    assert "local v0 = 42" not in source
    assert "return 42" in source


def test_opcode_table_matches_current_official_count() -> None:
    assert opcode_count() == 90
    assert opcode_name(89) == "NEWCLASS"


def test_v13_double_vector_constant_is_parsed() -> None:
    code = (_ad(5, 0, 0), _abc(22, 0, 2, 0))
    constants = _varuint(1) + b"\x0b" + struct.pack("<dddd", 1.0, 2.0, 3.0, 4.0)
    module = parse_bytecode(_modern_container(13, code, constants))
    constant = module.main_proto.constants[0]
    assert constant.kind == "vectord"
    assert constant.value == (1.0, 2.0, 3.0, 4.0)
    assert "vector.create(1.0, 2.0, 3.0, 4.0)" in decompile_module(
        module, {}, "v13"
    )


def test_structured_type_info_recovers_typed_local() -> None:
    type_info = _varuint(1) + _varuint(0) + _varuint(1)
    type_info += b"\x02"  # function signature byte
    type_info += b"\x03\x00" + _varuint(0) + _varuint(2)
    code = (_ad(4, 0, 5), _abc(22, 0, 2, 0))
    constants = _varuint(0)
    module = parse_bytecode(
        _modern_container(13, code, constants, type_info=type_info)
    )
    typed = module.main_proto.typed_locals
    assert len(typed) == 1
    assert typed[0].register == 0
    assert "local str1: string = 5" in decompile_module(module, {}, "typed")


def test_wip_class_bytecode_and_newclass_are_supported() -> None:
    strings = (b"MyClass", b"method", b"main")
    code = (
        _abc(89, 0, 0xFF, 0),
        2,
        _abc(22, 0, 2, 0),
    )
    constants = bytearray()
    constants += _varuint(3)
    constants += b"\x03" + _varuint(1)
    constants += b"\x03" + _varuint(2)
    constants += b"\x0a" + _varuint(0) + _varuint(0) + _varuint(1) + _varuint(1)
    module = parse_bytecode(
        _modern_container(100, code, bytes(constants), strings=strings)
    )
    text = disassemble_module(module, "class")
    assert "NEWCLASS" in text
    assert "class-shape(MyClass" in text
    source = decompile_module(module, {}, "class")
    assert "class MyClass" in source


def test_userdata_aux_uses_low_16_bits_for_key() -> None:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=2,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=(
            _abc(83, 0, 1, 0),
            (7 << 16) | 0,
            _abc(22, 0, 2, 0),
        ),
        constants=(LuauConstant("string", "Name", 3),),
        child_proto_ids=(),
        line_defined=0,
        debug_name="main",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    module = LuauBytecodeModule(
        version=9,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )
    text = disassemble_module(module, "userdata")
    assert 'key="Name"' in text
    assert "cached_slot=7" in text


def test_strict_decoder_rejects_missing_aux() -> None:
    with pytest.raises(ValueError, match="missing its AUX"):
        decode_words((_abc(7, 0, 0, 0),), strict=True, bytecode_version=13)


def test_official_fastcall_jump_target_rule() -> None:
    instruction = decode_words((_abc(68, 2, 0, 5),))[0]
    assert get_jump_target(instruction) == 7
