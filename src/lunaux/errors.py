from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_BASE64 = "INVALID_BASE64"
    EMPTY_BYTECODE = "EMPTY_BYTECODE"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    INVALID_FILENAME = "INVALID_FILENAME"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    BACKEND_FAILURE = "BACKEND_FAILURE"
    INVALID_OPTIONS = "INVALID_OPTIONS"


@dataclass(slots=True)
class LunaUXError(Exception):
    code: ErrorCode
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message
