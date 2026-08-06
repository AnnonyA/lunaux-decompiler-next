from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from lunaux.backends.base import DecompilerBackend
from lunaux.models import DecompileOptions

_SCHEMA_VERSION = 1


class BenchmarkStatus(StrEnum):
    SUCCESS = "success"
    EMPTY_OUTPUT = "empty_output"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    bytecode_path: Path
    source_path: Path | None = None
    tags: tuple[str, ...] = ()
    optimization: str | None = None


@dataclass(frozen=True, slots=True)
class BackendExecution:
    status: BenchmarkStatus
    output: str = ""
    stderr: str = ""
    return_code: int | None = None
    error: str | None = None


class BenchmarkBackend(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def execute(
        self,
        case: BenchmarkCase,
        output_path: Path,
        timeout_seconds: float,
    ) -> BackendExecution: ...


@dataclass(frozen=True, slots=True)
class InProcessBackend:
    backend: DecompilerBackend
    options: Mapping[str, bool]

    @property
    def name(self) -> str:
        return self.backend.name

    @property
    def version(self) -> str:
        return self.backend.version

    def execute(
        self,
        case: BenchmarkCase,
        output_path: Path,
        timeout_seconds: float,
    ) -> BackendExecution:
        del timeout_seconds
        try:
            output = self.backend.decompile(
                case.bytecode_path.read_bytes(),
                dict(self.options),
                case.bytecode_path.name,
            )
        except Exception as exc:  # benchmark boundary: record backend failures
            return BackendExecution(
                status=BenchmarkStatus.ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )
        if not output.strip():
            return BackendExecution(status=BenchmarkStatus.EMPTY_OUTPUT)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8", newline="\n")
        return BackendExecution(status=BenchmarkStatus.SUCCESS, output=output)


@dataclass(frozen=True, slots=True)
class ExternalCommandBackend:
    backend_name: str
    backend_version: str
    command: tuple[str, ...]
    output_mode: str = "stdout"

    def __post_init__(self) -> None:
        if not self.backend_name.strip():
            raise ValueError("backend_name must not be empty")
        if not self.command:
            raise ValueError("command must not be empty")
        if self.output_mode not in {"stdout", "file"}:
            raise ValueError("output_mode must be 'stdout' or 'file'")
        command_text = "\0".join(self.command)
        if "{input}" not in command_text:
            raise ValueError("external backend command must contain {input}")
        if self.output_mode == "file" and "{output}" not in command_text:
            raise ValueError("file output mode requires an {output} placeholder")

    @property
    def name(self) -> str:
        return self.backend_name

    @property
    def version(self) -> str:
        return self.backend_version

    def execute(
        self,
        case: BenchmarkCase,
        output_path: Path,
        timeout_seconds: float,
    ) -> BackendExecution:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = tuple(
            item.replace("{input}", str(case.bytecode_path)).replace(
                "{output}", str(output_path)
            )
            for item in self.command
        )
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return BackendExecution(
                status=BenchmarkStatus.TIMEOUT,
                stderr=stderr,
                error=f"timed out after {timeout_seconds:g} seconds",
            )
        except OSError as exc:
            return BackendExecution(
                status=BenchmarkStatus.ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )

        if completed.returncode != 0:
            return BackendExecution(
                status=BenchmarkStatus.ERROR,
                stderr=completed.stderr,
                return_code=completed.returncode,
                error=f"external command exited with code {completed.returncode}",
            )

        if self.output_mode == "file":
            try:
                output = output_path.read_text(encoding="utf-8")
            except OSError as exc:
                return BackendExecution(
                    status=BenchmarkStatus.ERROR,
                    stderr=completed.stderr,
                    return_code=completed.returncode,
                    error=f"could not read external output: {exc}",
                )
        else:
            output = completed.stdout
            if output.strip():
                output_path.write_text(output, encoding="utf-8", newline="\n")

        if not output.strip():
            return BackendExecution(
                status=BenchmarkStatus.EMPTY_OUTPUT,
                stderr=completed.stderr,
                return_code=completed.returncode,
            )
        return BackendExecution(
            status=BenchmarkStatus.SUCCESS,
            output=output,
            stderr=completed.stderr,
            return_code=completed.returncode,
        )


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    case_id: str
    backend: str
    backend_version: str
    status: BenchmarkStatus
    elapsed_ms: float
    output_characters: int
    output_sha256: str | None
    artifact: str | None
    stderr: str | None = None
    return_code: int | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "backend": self.backend,
            "backend_version": self.backend_version,
            "status": self.status.value,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "output_characters": self.output_characters,
            "output_sha256": self.output_sha256,
            "artifact": self.artifact,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    backend: str
    backend_version: str
    total: int
    successes: int
    empty_outputs: int
    errors: int
    timeouts: int
    success_rate: float
    median_ms: float
    p95_ms: float

    def as_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "backend_version": self.backend_version,
            "total": self.total,
            "successes": self.successes,
            "empty_outputs": self.empty_outputs,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "success_rate": round(self.success_rate, 6),
            "median_ms": round(self.median_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    generated_at: str
    manifest: str
    results: tuple[BenchmarkResult, ...]
    summaries: tuple[BenchmarkSummary, ...]
    schema_version: int = _SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "manifest": self.manifest,
            "summaries": [summary.as_dict() for summary in self.summaries],
            "results": [result.as_dict() for result in self.results],
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def _safe_relative_path(root: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty string")
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes the manifest directory") from exc
    return candidate


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def load_manifest(path: Path) -> tuple[BenchmarkCase, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load benchmark manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("benchmark manifest must be a JSON object")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"benchmark manifest schema_version must be {_SCHEMA_VERSION}")
    entries = payload.get("cases")
    if not isinstance(entries, list) or not entries:
        raise ValueError("benchmark manifest must contain at least one case")

    root = path.parent.resolve()
    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = raw_entry.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"cases[{index}].id must be a non-empty string")
        if case_id in seen:
            raise ValueError(f"duplicate benchmark case id: {case_id}")
        seen.add(case_id)

        bytecode_path = _safe_relative_path(root, raw_entry.get("bytecode"), "bytecode")
        if not bytecode_path.is_file():
            raise ValueError(f"benchmark bytecode does not exist: {bytecode_path}")

        source_value = raw_entry.get("source")
        source_path = (
            _safe_relative_path(root, source_value, "source")
            if source_value is not None
            else None
        )
        if source_path is not None and not source_path.is_file():
            raise ValueError(f"benchmark source does not exist: {source_path}")

        raw_tags = raw_entry.get("tags", [])
        if not isinstance(raw_tags, list) or not all(isinstance(tag, str) for tag in raw_tags):
            raise ValueError(f"cases[{index}].tags must be a list of strings")
        cases.append(
            BenchmarkCase(
                case_id=case_id,
                bytecode_path=bytecode_path,
                source_path=source_path,
                tags=tuple(raw_tags),
                optimization=_optional_string(raw_entry, "optimization"),
            )
        )
    return tuple(cases)


def load_external_backends(path: Path) -> tuple[ExternalCommandBackend, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load external backend configuration: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"external backend schema_version must be {_SCHEMA_VERSION}")
    entries = payload.get("backends")
    if not isinstance(entries, list):
        raise ValueError("external backend configuration must contain a backends list")

    backends: list[ExternalCommandBackend] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"backends[{index}] must be an object")
        name = raw_entry.get("name")
        version = raw_entry.get("version", "unknown")
        command = raw_entry.get("command")
        output_mode = raw_entry.get("output", "stdout")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"backends[{index}].name must be a non-empty string")
        if name in seen:
            raise ValueError(f"duplicate external backend name: {name}")
        seen.add(name)
        if not isinstance(version, str):
            raise ValueError(f"backends[{index}].version must be a string")
        if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
            raise ValueError(f"backends[{index}].command must be a list of strings")
        if not isinstance(output_mode, str):
            raise ValueError(f"backends[{index}].output must be a string")
        backends.append(
            ExternalCommandBackend(
                backend_name=name,
                backend_version=version,
                command=tuple(command),
                output_mode=output_mode,
            )
        )
    return tuple(backends)


def _percentile_95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95 + 0.5)))
    return ordered[index]


def _summaries(results: Sequence[BenchmarkResult]) -> tuple[BenchmarkSummary, ...]:
    grouped: dict[tuple[str, str], list[BenchmarkResult]] = {}
    for result in results:
        grouped.setdefault((result.backend, result.backend_version), []).append(result)

    summaries: list[BenchmarkSummary] = []
    for (backend, version), items in sorted(grouped.items()):
        durations = [item.elapsed_ms for item in items]
        success_count = sum(item.status is BenchmarkStatus.SUCCESS for item in items)
        total = len(items)
        summaries.append(
            BenchmarkSummary(
                backend=backend,
                backend_version=version,
                total=total,
                successes=success_count,
                empty_outputs=sum(
                    item.status is BenchmarkStatus.EMPTY_OUTPUT for item in items
                ),
                errors=sum(item.status is BenchmarkStatus.ERROR for item in items),
                timeouts=sum(item.status is BenchmarkStatus.TIMEOUT for item in items),
                success_rate=success_count / total if total else 0.0,
                median_ms=statistics.median(durations) if durations else 0.0,
                p95_ms=_percentile_95(durations),
            )
        )
    return tuple(summaries)


def run_benchmark(
    manifest_path: Path,
    cases: Sequence[BenchmarkCase],
    backends: Sequence[BenchmarkBackend],
    artifact_directory: Path,
    *,
    timeout_seconds: float = 30.0,
) -> BenchmarkReport:
    if not cases:
        raise ValueError("at least one benchmark case is required")
    if not backends:
        raise ValueError("at least one benchmark backend is required")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    names: set[str] = set()
    for backend in backends:
        if backend.name in names:
            raise ValueError(f"duplicate benchmark backend name: {backend.name}")
        names.add(backend.name)

    results: list[BenchmarkResult] = []
    for backend in backends:
        for case in cases:
            relative_artifact = Path(backend.name) / f"{case.case_id}.luau"
            output_path = artifact_directory / relative_artifact
            started = time.perf_counter()
            execution = backend.execute(case, output_path, timeout_seconds)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            output = execution.output
            artifact = str(relative_artifact.as_posix()) if output.strip() else None
            results.append(
                BenchmarkResult(
                    case_id=case.case_id,
                    backend=backend.name,
                    backend_version=backend.version,
                    status=execution.status,
                    elapsed_ms=elapsed_ms,
                    output_characters=len(output),
                    output_sha256=(
                        hashlib.sha256(output.encode("utf-8")).hexdigest()
                        if output
                        else None
                    ),
                    artifact=artifact,
                    stderr=execution.stderr or None,
                    return_code=execution.return_code,
                    error=execution.error,
                )
            )

    ordered_results = tuple(sorted(results, key=lambda item: (item.backend, item.case_id)))
    return BenchmarkReport(
        generated_at=datetime.now(UTC).isoformat(),
        manifest=str(manifest_path),
        results=ordered_results,
        summaries=_summaries(ordered_results),
    )


def default_options() -> Mapping[str, bool]:
    return DecompileOptions().to_backend_dict()
