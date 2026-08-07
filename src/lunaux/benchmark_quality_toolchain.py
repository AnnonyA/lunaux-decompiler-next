from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lunaux.benchmark_quality_models import CheckStatus, QualityCheck


@dataclass(frozen=True, slots=True)
class ExternalToolchain:
    syntax_command: tuple[str, ...]
    compile_command: tuple[str, ...]
    run_command: tuple[str, ...]
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        for label, command in (
            ("syntax_command", self.syntax_command),
            ("compile_command", self.compile_command),
            ("run_command", self.run_command),
        ):
            if not command or not any("{source}" in part for part in command):
                raise ValueError(f"{label} must contain a {{source}} placeholder")
        if self.timeout_seconds <= 0:
            raise ValueError("toolchain timeout_seconds must be greater than zero")

    def syntax_check(self, source: Path) -> QualityCheck:
        return self._execute(self.syntax_command, source)

    def compile_check(self, source: Path) -> QualityCheck:
        return self._execute(self.compile_command, source, binary_stdout=True)

    def execute_source(self, source: Path) -> QualityCheck:
        return self._execute(self.run_command, source)

    def _execute(
        self,
        template: Sequence[str],
        source: Path,
        *,
        binary_stdout: bool = False,
    ) -> QualityCheck:
        command = [part.replace("{source}", str(source)) for part in template]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=not binary_stdout,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return QualityCheck(
                CheckStatus.TIMEOUT,
                (time.perf_counter() - started) * 1000.0,
                f"timed out after {self.timeout_seconds:g} seconds",
            )
        except OSError as exc:
            return QualityCheck(
                CheckStatus.ERROR,
                (time.perf_counter() - started) * 1000.0,
                f"{type(exc).__name__}: {exc}",
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        stdout = completed.stdout
        if isinstance(stdout, bytes):
            stdout_bytes = stdout
            stdout_text = ""
        else:
            stdout_text = stdout
            stdout_bytes = stdout.encode("utf-8")
        stderr = completed.stderr
        stderr_text = (
            stderr.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes)
            else stderr
        )
        digest = hashlib.sha256(stdout_bytes).hexdigest()
        if completed.returncode == 0:
            return QualityCheck(CheckStatus.PASS, elapsed_ms, stdout_text, digest)
        detail = (stderr_text or stdout_text).strip()
        if len(detail) > 1000:
            detail = detail[:1000] + "…"
        return QualityCheck(
            CheckStatus.FAIL,
            elapsed_ms,
            detail or f"exit code {completed.returncode}",
            digest,
        )


def load_toolchain(path: Path) -> ExternalToolchain:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load benchmark toolchain: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("benchmark toolchain schema_version must be 1")

    def command(key: str) -> tuple[str, ...]:
        value = payload.get(key)
        if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
            raise ValueError(f"{key} must be a list of strings")
        return tuple(value)

    timeout = payload.get("timeout_seconds", 10.0)
    if not isinstance(timeout, (int, float)):
        raise ValueError("timeout_seconds must be numeric")
    return ExternalToolchain(
        command("syntax_command"),
        command("compile_command"),
        command("run_command"),
        float(timeout),
    )


def normalized_stdout(value: str | None) -> str:
    if value is None:
        return ""
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def semantic_check(expected: QualityCheck, actual: QualityCheck) -> QualityCheck:
    if expected.status is not CheckStatus.PASS:
        return QualityCheck(
            CheckStatus.SKIP,
            detail="the original source did not execute successfully",
        )
    if actual.status is not CheckStatus.PASS:
        return actual
    expected_output = normalized_stdout(expected.detail)
    actual_output = normalized_stdout(actual.detail)
    detail = (
        f"expected={expected_output!r}; actual={actual_output!r}"
        if expected_output != actual_output
        else None
    )
    return QualityCheck(
        CheckStatus.PASS if expected_output == actual_output else CheckStatus.FAIL,
        expected.elapsed_ms + actual.elapsed_ms,
        detail,
        actual.stdout_sha256,
    )
