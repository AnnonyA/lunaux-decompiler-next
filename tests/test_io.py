from __future__ import annotations

import base64

import pytest

from lunaux.errors import ErrorCode, LunaUXError
from lunaux.io import InputFormat, decode_input


def test_raw_input_is_preserved() -> None:
    data = b"\x00\x01\x02bytecode"
    assert decode_input(data, InputFormat.RAW) == data


def test_explicit_base64_is_decoded() -> None:
    original = b"binary bytecode"
    assert decode_input(base64.b64encode(original), InputFormat.BASE64) == original


def test_auto_detects_canonical_base64() -> None:
    original = b"binary bytecode"
    assert decode_input(base64.b64encode(original), InputFormat.AUTO) == original


def test_invalid_base64_has_stable_error_code() -> None:
    with pytest.raises(LunaUXError) as error:
        decode_input(b"not base64!", InputFormat.BASE64)
    assert error.value.code is ErrorCode.INVALID_BASE64
