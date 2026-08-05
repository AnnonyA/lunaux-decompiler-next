from __future__ import annotations

import struct

from lunaux.backends.auto import BackendMode, build_backend
from lunaux.backends.opcodes import disassemble_words
from lunaux.backends.reconstructed import ReconstructedBackend, inspect_bytecode


def test_raw_nop_disassembly() -> None:
    text = disassemble_words(struct.pack("<I", 0))
    assert "NOP" in text
    assert "0x00000000" in text


def test_reconstructed_decompile_is_explicit() -> None:
    backend = ReconstructedBackend()
    result = backend.decompile(struct.pack("<I", 0), {}, "sample.luac")
    assert "reconstructed output" in result
    assert "NOP" in result
    assert "requires a compatible native" in result


def test_serialized_input_is_not_misreported_as_raw() -> None:
    summary = inspect_bytecode(b"\x06\x03abc")
    assert summary.version == 6
    assert summary.types_version == 3
    assert not summary.raw_instruction_stream


def test_auto_backend_falls_back_when_native_is_missing() -> None:
    backend = build_backend("module_that_does_not_exist_lunaux", BackendMode.AUTO)
    assert backend.name == "python-reconstruction"
    assert backend.fallback_reason


def test_reconstructed_mode_never_imports_native() -> None:
    backend = build_backend("module_that_does_not_exist_lunaux", BackendMode.RECONSTRUCTED)
    assert backend.name == "python-reconstruction"
    assert backend.fallback_reason is None
