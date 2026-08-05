from __future__ import annotations

import base64
import binascii
import re
from enum import StrEnum

from lunaux.errors import ErrorCode, LunaUXError

_BASE64_RE = re.compile(rb"^[A-Za-z0-9+/]*={0,2}$")


class InputFormat(StrEnum):
    AUTO = "auto"
    RAW = "raw"
    BASE64 = "base64"


def decode_base64(data: bytes) -> bytes:
    compact = b"".join(data.split())
    if not compact:
        raise LunaUXError(ErrorCode.EMPTY_BYTECODE, "The input is empty.")
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LunaUXError(ErrorCode.INVALID_BASE64, "The input is not valid Base64.") from exc
    if not decoded:
        raise LunaUXError(ErrorCode.EMPTY_BYTECODE, "The decoded bytecode is empty.")
    return decoded


def _looks_like_base64(data: bytes) -> bool:
    compact = b"".join(data.split())
    if len(compact) < 8 or len(compact) % 4 != 0:
        return False
    if _BASE64_RE.fullmatch(compact) is None:
        return False
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return False
    if not decoded:
        return False
    canonical = base64.b64encode(decoded).rstrip(b"=")
    return canonical == compact.rstrip(b"=")


def decode_input(data: bytes, input_format: InputFormat) -> bytes:
    if not data:
        raise LunaUXError(ErrorCode.EMPTY_BYTECODE, "The input is empty.")
    if input_format is InputFormat.RAW:
        return data
    if input_format is InputFormat.BASE64:
        return decode_base64(data)
    return decode_base64(data) if _looks_like_base64(data) else data
