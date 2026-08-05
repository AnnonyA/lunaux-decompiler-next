from __future__ import annotations

import struct

import pytest

from lunaux.backends.bytecode import (
    LuauBytecodeModule,
    LuauProto,
    _recover_opcode_encoding,
    parse_bytecode,
)
from lunaux.backends.opcode_encoding import decode_multiplicative_opcode_words
from lunaux.backends.opcodes import opcode_names


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _ad(name: str, a: int, d: int) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _abc(name: str, a: int, b: int, c: int) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _encoded(word: int, multiplier: int = 227) -> int:
    opcode = word & 0xFF
    return (word & 0xFFFFFF00) | ((opcode * multiplier) & 0xFF)


def _module(code: tuple[int, ...]) -> LuauBytecodeModule:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=2,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=(),
        child_proto_ids=(),
        line_defined=0,
        debug_name="encoded",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    return LuauBytecodeModule(
        version=9,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def _serialized_v9_module(code: tuple[int, ...]) -> bytes:
    data = bytearray(
        (
            9,  # bytecode version
            3,  # type information version
            0,  # string count
            0,  # userdata type terminator
            1,  # prototype count
            2,  # max stack size
            0,  # parameter count
            0,  # upvalue count
            0,  # is vararg
            0,  # flags
            0,  # type information size
            len(code),
        )
    )
    data.extend(struct.pack(f"<{len(code)}I", *code))
    data.extend(
        (
            0,  # constant count
            0,  # child prototype count
            0,  # line defined
            0,  # debug name
            0,  # no line information
            0,  # no debug information
            0,  # main prototype id
        )
    )
    return bytes(data)


def test_decodes_roblox_multiplier_without_touching_operands() -> None:
    original = _ad("LOADN", 1, -42)
    encoded = _encoded(original)

    decoded = decode_multiplicative_opcode_words(
        (encoded,),
        227,
        bytecode_version=9,
    )

    assert encoded & 0xFF == 140
    assert decoded == (original,)
    assert decoded[0] & 0xFFFFFF00 == original & 0xFFFFFF00


def test_preserves_aux_words_verbatim() -> None:
    instruction = _abc("GETGLOBAL", 0, 0, 0)
    aux = 0xDEADBEEF
    return_word = _abc("RETURN", 0, 1, 0)

    decoded = decode_multiplicative_opcode_words(
        (_encoded(instruction), aux, _encoded(return_word)),
        227,
        bytecode_version=9,
    )

    assert decoded == (instruction, aux, return_word)


def test_rejects_noninvertible_multiplier() -> None:
    with pytest.raises(ValueError, match="must be odd"):
        decode_multiplicative_opcode_words((), 228, bytecode_version=9)


def test_recovers_and_validates_an_encoded_module() -> None:
    original = (
        _ad("LOADN", 0, 42),
        _abc("RETURN", 0, 2, 0),
    )
    module = _module(tuple(_encoded(word) for word in original))

    recovered = _recover_opcode_encoding(module)

    assert recovered is not None
    assert recovered.opcode_encoding == "multiplicative:227"
    assert recovered.main_proto.code == original


def test_parser_recovers_a_complete_serialized_v9_container() -> None:
    original = (
        _ad("LOADN", 0, 42),
        _abc("RETURN", 0, 2, 0),
    )
    encoded = tuple(_encoded(word) for word in original)

    module = parse_bytecode(_serialized_v9_module(encoded))

    assert module.version == 9
    assert module.types_version == 3
    assert module.opcode_encoding == "multiplicative:227"
    assert module.main_proto.code == original
