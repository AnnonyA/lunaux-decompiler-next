from __future__ import annotations

import hashlib
import json
import re
import statistics
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from lunaux.backends.base import DecompilerBackend
from lunaux.models import DecompileOptions

_SCHEMA_VERSION = 1
_ARTIFACT_RE = re.compile(r"[^A-Za-z0-9._-]+")


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
            if not output.strip():
                return BackendExecution(BenchmarkStatus.EMPTY_OUTPUT)
            _write_artifact(output_path, output)
        except Exception as exc:  # benchmark boundary: record, then continue
            return _failure(exc)
        return BackendExecution(BenchmarkStatus.SUCCESS, output=output)


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
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.unlink(missing_ok=True)
        except OSError as exc:
            return _failure(exc, "could not prepare benchmark artifact")

        command = tuple(
            part.replace("{input}", str(case.bytecode_path)).replace(
                "{output}", str(output_path)
            )
            for part in self.command
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
                BenchmarkStatus.TIMEOUT,
                stderr=stderr,
                error=f"timed out after {timeout_seconds:g} seconds",
            )
        except OSError as exc:
            return _failure(exc)

        if completed.returncode != 0:
            return BackendExecution(
                BenchmarkStatus.ERROR,
                stderr=completed.stderr,
                return_code=completed.returncode,
                error=f"external command exited with code {completed.returncode}",
            )

        try:
            output = (
                output_path.read_text(encoding="utf-8")
                if self.output_mode == "file"
                else completed.stdout
            )
            if self.output_mode == "stdout" and output.strip():
                _write_artifact(output_path, output)
        except OSError as exc:
            return _failure(exc, "could not read or write external output")

        status = BenchmarkStatus.SUCCESS if output.strip() else BenchmarkStatus.EMPTY_OUTPUT
        return BackendExecution(
            status,
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


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    generated_at: str
    manifest: str
    results: tuple[BenchmarkResult, ...]
    summaries: tuple[BenchmarkSummary, ...]
    schema_version: int = _SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def _failure(exc: Exception, prefix: str | None = None) -> BackendExecution:
    detail = f"{type(exc).__name__}: {exc}"
    return BackendExecution(
        BenchmarkStatus.ERROR,
        error=f"{prefix}: {detail}" if prefix else detail,
    )


def _write_artifact(path: Path, output: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8", newline="\n")


def _safe_relative_path(root: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty string")
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the manifest directory") from exc
    return candidate


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def load_manifest(path: Path) -> tuple[BenchmarkCase, ...]:
    payload = _load_json_object(path, "benchmark manifest")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"benchmark manifest schema_version must be {_SCHEMA_VERSION}")
    entries = payload.get("cases")
    if not isinstance(entries, list) or not entries:
        raise ValueError("benchmark manifest must contain at least one case")

    root = path.parent.resolve()
    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = entry.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"cases[{index}].id must be a non-empty string")
        if case_id in seen:
            raise ValueError(f"duplicate benchmark case id: {case_id}")
        seen.add(case_id)

        bytecode = _safe_relative_path(root, entry.get("bytecode"), "bytecode")
        if not bytecode.is_file():
            raise ValueError(f"benchmark bytecode does not exist: {bytecode}")
        source_raw = entry.get("source")
        source = (
            _safe_relative_path(root, source_raw, "source")
            if source_raw is not None
            else None
        )
        if source is not None and not source.is_file():
            raise ValueError(f"benchmark source does not exist: {source}")
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError(f"cases[{index}].tags must be a list of strings")
        cases.append(
            BenchmarkCase(
                case_id,
                bytecode,
                source,
                tuple(tags),
                _optional_string(entry, "optimization"),
            )
        )
    return tuple(cases)


def load_external_backends(path: Path) -> tuple[ExternalCommandBackend, ...]:
    payload = _load_json_object(path, "external backend configuration")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(f"external backend schema_version must be {_SCHEMA_VERSION}")
    entries = payload.get("backends")
    if not isinstance(entries, list):
        raise ValueError("external backend configuration must contain a backends list")

    backends: list[ExternalCommandBackend] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"backends[{index}] must be an object")
        name = entry.get("name")
        version = entry.get("version", "unknown")
        command = entry.get("command")
        output = entry.get("output", "stdout")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"backends[{index}].name must be a non-empty string")
        if name in seen:
            raise ValueError(f"duplicate external backend name: {name}")
        seen.add(name)
        if not isinstance(version, str) or not isinstance(output, str):
            raise ValueError(f"backends[{index}] version and output must be strings")
        if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
            raise ValueError(f"backends[{index}].command must be a list of strings")
        backends.append(ExternalCommandBackend(name, version, tuple(command), output))
    return tuple(backends)


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _artifact_component(value: str) -> str:
    component = _ARTIFACT_RE.sub("_", value).strip("._")
    if not component:
        raise ValueError(f"value cannot be used as an artifact name: {value!r}")
    return component


def _percentile_95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * 0.95)
    return ordered[index]


def _summaries(results: Sequence[BenchmarkResult]) -> tuple[BenchmarkSummary, ...]:
    grouped: dict[tuple[str, str], list[BenchmarkResult]] = {}
    for result in results:
        grouped.setdefault((result.backend, result.backend_version), []).append(result)

    summaries: list[BenchmarkSummary] = []
    for (backend, version), items in sorted(grouped.items()):
        durations = [item.elapsed_ms for item in items]
        successes = sum(item.status is BenchmarkStatus.SUCCESS for item in items)
        summaries.append(
            BenchmarkSummary(
                backend,
                version,
                len(items),
                successes,
                sum(item.status is BenchmarkStatus.EMPTY_OUTPUT for item in items),
                sum(item.status is BenchmarkStatus.ERROR for item in items),
                sum(item.status is BenchmarkStatus.TIMEOUT for item in items),
                successes / len(items),
                statistics.median(durations),
                _percentile_95(durations),
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
    if not cases or not backends:
        raise ValueError("at least one benchmark case and backend are required")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    backend_paths = _unique_artifact_names(backend.name for backend in backends)
    case_paths = _unique_artifact_names(case.case_id for case in cases)
    if len({backend.name for backend in backends}) != len(backends):
        raise ValueError("benchmark backend names must be unique")

    results: list[BenchmarkResult] = []
    for backend in backends:
        for case in cases:
            relative = Path(backend_paths[backend.name]) / f"{case_paths[case.case_id]}.luau"
            output_path = artifact_directory / relative
            started = time.perf_counter()
            try:
                execution = backend.execute(case, output_path, timeout_seconds)
            except Exception as exc:  # custom adapter boundary
                execution = _failure(exc)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            output = execution.output
            results.append(
                BenchmarkResult(
                    case.case_id,
                    backend.name,
                    backend.version,
                    execution.status,
                    elapsed_ms,
                    len(output),
                    hashlib.sha256(output.encode()).hexdigest() if output else None,
                    relative.as_posix() if output.strip() else None,
                    execution.stderr or None,
                    execution.return_code,
                    execution.error,
                )
            )

    ordered = tuple(sorted(results, key=lambda item: (item.backend, item.case_id)))
    return BenchmarkReport(
        datetime.now(UTC).isoformat(),
        str(manifest_path),
        ordered,
        _summaries(ordered),
    )


def _unique_artifact_names(values: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    used: set[str] = set()
    for value in values:
        component = _artifact_component(value)
        if component in used:
            raise ValueError(f"benchmark artifact name collision: {component}")
        used.add(component)
        result[value] = component
    return result


def default_options() -> Mapping[str, bool]:
    return DecompileOptions().to_backend_dict()
