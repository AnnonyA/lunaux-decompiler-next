from __future__ import annotations

import struct

import pytest

from lunaux.backends.bytecode import BytecodeFormatError, parse_bytecode
from lunaux.backends.lifter import decompile_module, disassemble_module
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
    assert "local v0 = print" in source
    assert 'local v1 = "hello"' in source
    assert "v0(v1)" in source
    assert "Exact Luau source reconstruction requires" not in source


def test_semicolon_option_is_applied() -> None:
    source = ReconstructedBackend().decompile(
        _sample_container(),
        {"Semicolons": True},
        "Example",
    )
    assert "local v0 = print;" in source
    assert "v0(v1);" in source


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
    assert "local v0 = 42" in source
    assert "return v0" in source
