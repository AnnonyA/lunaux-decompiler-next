from __future__ import annotations

import re

from typer.testing import CliRunner

from lunaux import __version__
from lunaux.cli import app
from lunaux.service import DecompilerService
from tests.fakes import FakeBackend

runner = CliRunner()


def test_help_supports_short_flag_and_lists_classic_commands() -> None:
    result = runner.invoke(app, ["-h"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "decomp" in result.stdout
    assert "disasm" in result.stdout


def test_global_version_flag() -> None:
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_global_hash_flag() -> None:
    result = runner.invoke(app, ["-ih"])
    assert result.exit_code == 0
    assert re.fullmatch(r"[0-9a-f]{64}", result.stdout.strip()) is not None


def test_decomp_accepts_positional_output_directory(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "Example.luac"
    output_directory = tmp_path / "output"
    input_path.write_bytes(b"abc")
    service = DecompilerService(FakeBackend(), max_bytecode_bytes=100)
    monkeypatch.setattr("lunaux.cli._service", lambda: service)

    result = runner.invoke(
        app,
        ["decomp", str(input_path), str(output_directory), "--input-format", "raw"],
    )

    assert result.exit_code == 0
    output_path = output_directory / "Example.luau"
    assert output_path.read_text(encoding="utf-8").startswith("decompiled:Example.luac:3")
