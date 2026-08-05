from __future__ import annotations

import pytest

from lunaux.backends.bytecode import (
    LuauBytecodeModule,
    LuauProto,
    _recover_opcode_encoding,
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
