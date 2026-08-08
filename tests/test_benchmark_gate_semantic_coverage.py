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
    passed = QualityCheck(CheckStatus.PASS)
    skipped = QualityCheck(CheckStatus.SKIP)
    executed = execution is BenchmarkStatus.SUCCESS
    return QualityResult(
        case_id=case_id,
        backend=backend,
        backend_version="pinned",
        execution_status=execution,
        execution_ms=1.0,
        peak_memory_bytes=1024,
        syntax=passed if executed else skipped,
        recompilation=passed if executed else skipped,
        semantics=QualityCheck(semantic),
        readability=ReadabilityMetrics(readability, 0, 0.0, 1.0, 1.0),
    )


def _summary(
    backend: str,
    *,
    recompilation: float,
    conditional_semantics: float,
    readability: float,
    stability: float,
) -> QualitySummary:
    return QualitySummary(
        backend=backend,
        backend_version="pinned",
        total=2,
        execution_success_rate=1.0 if backend == "lunaux" else 0.5,
        syntax_rate=recompilation,
        recompilation_rate=recompilation,
        semantic_cases=2 if backend == "lunaux" else 1,
        semantic_equivalence_rate=conditional_semantics,
        zero_fallback_rate=1.0,
        median_readability=readability,
        stability_rate=stability,
        median_ms=1.0,
        p95_ms=1.0,
        median_peak_memory_bytes=1024,
        max_peak_memory_bytes=1024,
    )


def test_release_gate_does_not_reward_skipped_semantic_cases() -> None:
    report = QualityReport(
        generated_from="manifest.json",
        results=(
            _result(
                "a",
                "lunaux",
                execution=BenchmarkStatus.SUCCESS,
                semantic=CheckStatus.PASS,
                readability=80.0,
            ),
            _result(
                "b",
                "lunaux",
                execution=BenchmarkStatus.SUCCESS,
                semantic=CheckStatus.FAIL,
                readability=80.0,
            ),
            _result(
                "a",
                "medal",
                execution=BenchmarkStatus.SUCCESS,
                semantic=CheckStatus.PASS,
                readability=40.0,
            ),
            _result(
                "b",
                "medal",
                execution=BenchmarkStatus.ERROR,
                semantic=CheckStatus.SKIP,
                readability=0.0,
            ),
        ),
        summaries=(
            _summary(
                "lunaux",
                recompilation=1.0,
                conditional_semantics=0.5,
                readability=80.0,
                stability=1.0,
            ),
            _summary(
                "medal",
                recompilation=0.5,
                conditional_semantics=1.0,
                readability=40.0,
                stability=0.5,
            ),
        ),
    )

    gated = apply_release_gate(report, "lunaux", "medal")

    assert gated.release_gate is not None
    semantic_metric = next(
        metric
        for metric in gated.release_gate.metrics
        if metric.name == "semantic_pass_rate"
    )
    assert semantic_metric.contender == 0.5
    assert semantic_metric.reference == 0.5
    assert semantic_metric.passed
    assert gated.release_gate.passed
    assert gated.release_gate.case_wins > gated.release_gate.case_losses
