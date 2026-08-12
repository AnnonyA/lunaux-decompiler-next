from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from lunaux.backends.auto import AutoBackend, BackendMode
from lunaux.backends.unluau import UnluauBackend
from lunaux.config import Settings
from lunaux.errors import ErrorCode, LunaUXError


def test_unluau_decompile_uses_isolated_output_and_quality_flags() -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, "Unluau 1.0.9-alpha\n", "")
        input_path = Path(args[1])
        assert input_path.read_bytes() == b"compiled-bytecode"
        output_path = Path(args[args.index("--output") + 1])
        output_path.write_text("local recovered = true\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch("lunaux.backends.unluau.subprocess.run", side_effect=fake_run):
        backend = UnluauBackend(command=("fake-unluau",))
        result = backend.decompile(
            b"compiled-bytecode",
            {"StringInterpolation": False},
            "Example.luac",
        )

    assert backend.version == "Unluau 1.0.9-alpha"
    assert result == "local recovered = true\n"
    decompile_call = calls[-1]
    assert "--inline-tables" in decompile_call
    assert "--smart-variable-names" in decompile_call
    assert "--rename-upvalues" in decompile_call
    assert decompile_call[-2:] == ["--string-interpolation", "false"]
    assert "--logs" not in decompile_call


def test_unluau_disassemble_returns_stdout() -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, "Unluau 1.0.9-alpha\n", "")
        output_path = Path(args[args.index("--output") + 1])
        output_path.write_text("-- discarded\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "GETIMPORT 0 1\nRETURN 0 1\n", "")

    with patch("lunaux.backends.unluau.subprocess.run", side_effect=fake_run):
        backend = UnluauBackend(command=("fake-unluau",))
        result = backend.disassemble(b"compiled-bytecode", "Example.luac")

    assert result == "GETIMPORT 0 1\nRETURN 0 1"


def test_unluau_timeout_is_reported() -> None:
    calls = 0

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(args, 0, "Unluau test\n", "")
        raise subprocess.TimeoutExpired(args, timeout=1)

    with patch("lunaux.backends.unluau.subprocess.run", side_effect=fake_run):
        backend = UnluauBackend(timeout_seconds=1, command=("fake-unluau",))
        with pytest.raises(LunaUXError) as captured:
            backend.decompile(b"compiled-bytecode", {}, "Example.luac")

    assert captured.value.code is ErrorCode.BACKEND_FAILURE
    assert captured.value.status_code == 504


class _FailingBackend:
    name = "failing"
    version = "1"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        del bytecode, options, filename
        raise LunaUXError(ErrorCode.BACKEND_FAILURE, "failed", status_code=422)

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        del bytecode, filename
        raise LunaUXError(ErrorCode.BACKEND_FAILURE, "failed", status_code=422)


class _WorkingBackend:
    name = "working"
    version = "2"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        del bytecode, options, filename
        return "return true"

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        del bytecode, filename
        return "RETURN"


def test_auto_backend_falls_through_per_request() -> None:
    backend = AutoBackend(_FailingBackend(), (_WorkingBackend(),))

    assert backend.decompile(b"data", {}, None) == "return true"
    assert backend.disassemble(b"data", None) == "RETURN"
    assert backend.name == "auto[failing -> working]"


def test_settings_accept_unluau_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUNAUX_BACKEND_MODE", "unluau")
    monkeypatch.setenv("LUNAUX_UNLUAU_PATH", "C:/Tools/Unluau.CLI.exe")
    monkeypatch.setenv("LUNAUX_EXTERNAL_TIMEOUT_SECONDS", "90")

    settings = Settings.from_env()

    assert settings.backend_mode is BackendMode.UNLUAU
    assert settings.unluau_path == "C:/Tools/Unluau.CLI.exe"
    assert settings.external_timeout_seconds == 90


def test_byteweft_environment_names_override_legacy_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUNAUX_BACKEND_MODE", "native")
    monkeypatch.setenv("LUNAUX_UNLUAU_PATH", "C:/Legacy/Unluau.exe")
    monkeypatch.setenv("BYTEWEFT_BACKEND_MODE", "unluau")
    monkeypatch.setenv("BYTEWEFT_UNLUAU_PATH", "C:/Tools/Unluau.CLI.exe")

    settings = Settings.from_env()

    assert settings.backend_mode is BackendMode.UNLUAU
    assert settings.unluau_path == "C:/Tools/Unluau.CLI.exe"
