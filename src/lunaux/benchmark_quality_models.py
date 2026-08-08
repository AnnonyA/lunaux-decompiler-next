from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from lunaux.benchmark_engine import BenchmarkStatus

_SCHEMA_VERSION = 1


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class QualityCheck:
    status: CheckStatus
    elapsed_ms: float = 0.0
    detail: str | None = None
    stdout_sha256: str | None = None

    @property
    def passed(self) -> bool:
        return self.status is CheckStatus.PASS


@dataclass(frozen=True, slots=True)
class ReadabilityMetrics:
    score: float
    fallback_count: int
    generated_identifier_ratio: float
    structural_similarity: float
    style_score: float


@dataclass(frozen=True, slots=True)
class QualityResult:
    case_id: str
    backend: str
    backend_version: str
    execution_status: BenchmarkStatus
    execution_ms: float
    peak_memory_bytes: int | None
    syntax: QualityCheck
    recompilation: QualityCheck
    semantics: QualityCheck
    readability: ReadabilityMetrics


@dataclass(frozen=True, slots=True)
class QualitySummary:
    backend: str
    backend_version: str
    total: int
    execution_success_rate: float
    syntax_rate: float
    recompilation_rate: float
    semantic_cases: int
    semantic_equivalence_rate: float
    zero_fallback_rate: float
    median_readability: float
    stability_rate: float
    median_ms: float
    p95_ms: float
    median_peak_memory_bytes: int | None
    max_peak_memory_bytes: int | None


@dataclass(frozen=True, slots=True)
class GateMetric:
    name: str
    contender: float
    reference: float
    passed: bool
    strictly_better: bool


@dataclass(frozen=True, slots=True)
class ReleaseGate:
    contender: str
    reference: str
    passed: bool
    metrics: tuple[GateMetric, ...]
    case_wins: int
    case_losses: int
    case_ties: int
    reason: str


@dataclass(frozen=True, slots=True)
class QualityReport:
    generated_from: str
    results: tuple[QualityResult, ...]
    summaries: tuple[QualitySummary, ...]
    release_gate: ReleaseGate | None = None
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

    def write_markdown(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# LunaUX differential benchmark",
            "",
            "| Backend | Execute | Syntax | Recompile | Semantic | No fallback | "
            "Readability | Stability | Median ms | p95 ms | Median MiB |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for summary in self.summaries:
            memory = (
                "n/a"
                if summary.median_peak_memory_bytes is None
                else f"{summary.median_peak_memory_bytes / (1024 * 1024):.2f}"
            )
            lines.append(
                f"| {summary.backend} `{summary.backend_version}` "
                f"| {summary.execution_success_rate:.2%} "
                f"| {summary.syntax_rate:.2%} "
                f"| {summary.recompilation_rate:.2%} "
                f"| {summary.semantic_equivalence_rate:.2%} "
                f"| {summary.zero_fallback_rate:.2%} "
                f"| {summary.median_readability:.2f} "
                f"| {summary.stability_rate:.2%} "
                f"| {summary.median_ms:.2f} "
                f"| {summary.p95_ms:.2f} "
                f"| {memory} |"
            )
        if self.release_gate is not None:
            gate = self.release_gate
            lines.extend(
                [
                    "",
                    "## 0.18 release gate",
                    "",
                    f"**{'PASS' if gate.passed else 'FAIL'}** — {gate.reason}",
                    "",
                    f"Case wins/losses/ties: **{gate.case_wins} / "
                    f"{gate.case_losses} / {gate.case_ties}**.",
                    "",
                    "| Metric | LunaUX | Reference | Result |",
                    "|---|---:|---:|---:|",
                ]
            )
            for metric in gate.metrics:
                lines.append(
                    f"| {metric.name} | {metric.contender:.6f} "
                    f"| {metric.reference:.6f} "
                    f"| {'PASS' if metric.passed else 'FAIL'} |"
                )
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
