from __future__ import annotations

from lunaux.benchmark_engine import BenchmarkStatus
from lunaux.benchmark_quality_gate import apply_release_gate
from lunaux.benchmark_quality_models import (
    CheckStatus,
    QualityCheck,
    QualityReport,
    QualityResult,
    QualitySummary,
    ReadabilityMetrics,
)


def _result(
    case_id: str,
    backend: str,
    *,
    execution: BenchmarkStatus,
    semantic: CheckStatus,
    readability: float,
) -> QualityResult:
    executed = execution is BenchmarkStatus.SUCCESS
    check = QualityCheck(CheckStatus.PASS if executed else CheckStatus.SKIP)
    return QualityResult(
        case_id=case_id,
        backend=backend,
        backend_version="pinned",
        execution_status=execution,
        execution_ms=1.0,
        peak_memory_bytes=1024,
        syntax=check,
        recompilation=check,
        semantics=QualityCheck(semantic),
        readability=ReadabilityMetrics(readability, 0, 0.0, 1.0, 1.0),
    )


def _summary(
    backend: str,
    *,
    execution: float,
    recompilation: float,
    semantic_cases: int,
    semantic_rate: float,
    readability: float,
) -> QualitySummary:
    return QualitySummary(
        backend=backend,
        backend_version="pinned",
        total=3,
        execution_success_rate=execution,
        syntax_rate=recompilation,
        recompilation_rate=recompilation,
        semantic_cases=semantic_cases,
        semantic_equivalence_rate=semantic_rate,
        zero_fallback_rate=1.0,
        median_readability=readability,
        stability_rate=execution,
        median_ms=1.0,
        p95_ms=1.0,
        median_peak_memory_bytes=1024,
        max_peak_memory_bytes=1024,
    )


def test_unsupported_reference_cases_cannot_hide_same_bytecode_loss() -> None:
    report = QualityReport(
        generated_from="manifest.json",
        results=(
            _result(
                "compatible-a",
                "lunaux",
                execution=BenchmarkStatus.SUCCESS,
                semantic=CheckStatus.PASS,
                readability=80.0,
            ),
            _result(
                "compatible-b",
                "lunaux",
                execution=BenchmarkStatus.SUCCESS,
                semantic=CheckStatus.FAIL,
                readability=80.0,
            ),
            _result(
                "unsupported-c",
                "lunaux",
                execution=BenchmarkStatus.SUCCESS,
                semantic=CheckStatus.PASS,
                readability=80.0,
            ),
            _result(
                "compatible-a",
                "medal",
                execution=BenchmarkStatus.SUCCESS,
                semantic=CheckStatus.PASS,
                readability=40.0,
            ),
            _result(
                "compatible-b",
                "medal",
                execution=BenchmarkStatus.SUCCESS,
                semantic=CheckStatus.PASS,
                readability=40.0,
            ),
            _result(
                "unsupported-c",
                "medal",
                execution=BenchmarkStatus.ERROR,
                semantic=CheckStatus.SKIP,
                readability=0.0,
            ),
        ),
        summaries=(
            _summary(
                "lunaux",
                execution=1.0,
                recompilation=1.0,
                semantic_cases=3,
                semantic_rate=2 / 3,
                readability=80.0,
            ),
            _summary(
                "medal",
                execution=2 / 3,
                recompilation=2 / 3,
                semantic_cases=2,
                semantic_rate=1.0,
                readability=40.0,
            ),
        ),
    )

    gated = apply_release_gate(report, "lunaux", "medal")

    assert gated.release_gate is not None
    assert not gated.release_gate.passed
    compatible_semantics = next(
        metric
        for metric in gated.release_gate.metrics
        if metric.name == "compatible_semantic_pass_rate"
    )
    assert compatible_semantics.contender == 0.5
    assert compatible_semantics.reference == 1.0
    assert gated.release_gate.case_wins <= gated.release_gate.case_losses
