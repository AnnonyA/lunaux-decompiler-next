from __future__ import annotations

import pytest

from lunaux.errors import ErrorCode, LunaUXError
from lunaux.models import DecompileOptions
from lunaux.service import DecompilerService
from tests.fakes import FakeBackend


def test_service_sanitizes_filename() -> None:
    service = DecompilerService(FakeBackend(), max_bytecode_bytes=100)
    result = service.decompile(b"abc", DecompileOptions(), "folder/Example.luau")
    assert result.startswith("decompiled:Example.luau")


def test_service_rejects_large_input() -> None:
    service = DecompilerService(FakeBackend(), max_bytecode_bytes=2)
    with pytest.raises(LunaUXError) as error:
        service.disassemble(b"abc")
    assert error.value.code is ErrorCode.INPUT_TOO_LARGE
