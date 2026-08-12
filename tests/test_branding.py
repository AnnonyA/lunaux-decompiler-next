from __future__ import annotations

from lunaux import __version__
from lunaux.branding import decompilation_header


def test_decompilation_header_reports_reproducible_version_metadata(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")

    header = decompilation_header(bytes((9, 3)))

    assert header == (
        f"-- [[ ByteWeft v{__version__} | decompiled at 1970-01-01T00:00:00Z | "
        "bytecode v9 | types v3 ]]\n"
    )


def test_decompilation_header_labels_raw_instruction_stream(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")

    header = decompilation_header(b"raw instructions")

    assert "raw instruction stream ]]" in header
