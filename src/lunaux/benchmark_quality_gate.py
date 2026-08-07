from __future__ import annotations

from lunaux.benchmark_engine import BenchmarkStatus
from lunaux.benchmark_quality_models import (
    CheckStatus,
    GateMetric,
    QualityReport,
    QualityResult,
    ReleaseGate,
)


def _case_rank(item: QualityResult) -> tuple[int, int, int, int, int, float]:
    execution = {
        BenchmarkStatus.SUCCESS: 3,
        BenchmarkStatus.EMPTY_OUTPUT: 2,
        BenchmarkStatus.ERROR: 1,
        BenchmarkStatus.TIMEOUT: 0,
    }[item.execution_status]
    semantic = {
        CheckStatus.PASS: 2,
        CheckStatus.SKIP: 1,
    }.get(item.semantics.status, 0)
    return (
        execution,
        semantic,
        int(item.recompilation.passed),
        int(item.syntax.passed),
        -item.readability.fallback_count,
        item.readability.score,
    )


def apply_release_gate(
    report: QualityReport,
    contender: str,
    reference: str,
) -> QualityReport:
    summaries = {summary.backend: summary for summary in report.summaries}
    if contender not in summaries or reference not in summaries:
        missing = contender if contender not in summaries else reference
        gate = ReleaseGate(
            contender,
            reference,
            False,
            (),
            0,
            0,
            0,
            f"required backend is missing: {missing}",
        )
        return QualityReport(
            report.generated_from,
            report.results,
            report.summaries,
            gate,
        )

    left = summaries[contender]
    right = summaries[reference]
    values = (
        ("recompilation_rate", left.recompilation_rate, right.recompilation_rate),
        (
            "semantic_equivalence_rate",
            left.semantic_equivalence_rate,
            right.semantic_equivalence_rate,
        ),
        ("median_readability", left.median_readability, right.median_readability),
        ("stability_rate", left.stability_rate, right.stability_rate),
    )
    metrics = tuple(
        GateMetric(
            name,
            contender_value,
            reference_value,
            contender_value >= reference_value,
            contender_value > reference_value,
        )
        for name, contender_value, reference_value in values
    )

    left_results = {
        result.case_id: result
        for result in report.results
        if result.backend == contender
    }
    right_results = {
        result.case_id: result
        for result in report.results
        if result.backend == reference
    }
    wins = losses = ties = 0
    for case_id in sorted(left_results.keys() & right_results.keys()):
        left_rank = _case_rank(left_results[case_id])
        right_rank = _case_rank(right_results[case_id])
        if left_rank > right_rank:
            wins += 1
        elif left_rank < right_rank:
            losses += 1
        else:
            ties += 1

    no_regression = all(metric.passed for metric in metrics)
    strict_metric_win = any(metric.strictly_better for metric in metrics)
    zero_timeouts = all(
        result.execution_status is not BenchmarkStatus.TIMEOUT
        for result in report.results
        if result.backend == contender
    )
    passed = no_regression and strict_metric_win and wins > losses and zero_timeouts
    if passed:
        reason = "LunaUX is not worse on any required metric and wins the aggregate comparison."
    elif not no_regression:
        reason = (
            "LunaUX regresses at least one required correctness/readability/stability metric."
        )
    elif not strict_metric_win:
        reason = "LunaUX does not strictly improve any required metric."
    elif wins <= losses:
        reason = "LunaUX does not win more paired cases than it loses."
    else:
        reason = "LunaUX recorded a timeout."
    gate = ReleaseGate(
        contender,
        reference,
        passed,
        metrics,
        wins,
        losses,
        ties,
        reason,
    )
    return QualityReport(
        report.generated_from,
        report.results,
        report.summaries,
        gate,
    )
