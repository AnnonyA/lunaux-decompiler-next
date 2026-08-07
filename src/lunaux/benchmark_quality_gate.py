from __future__ import annotations

import statistics
from collections.abc import Sequence

from lunaux.benchmark_engine import BenchmarkStatus
from lunaux.benchmark_quality_models import (
    CheckStatus,
    GateMetric,
    QualityReport,
    QualityResult,
    ReleaseGate,
)

_STABLE_STATUSES = frozenset({CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.SKIP})


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


def _semantic_pass_rate(items: Sequence[QualityResult]) -> float:
    """Measure semantic correctness against the entire selected case set."""
    if not items:
        return 0.0
    return sum(item.semantics.status is CheckStatus.PASS for item in items) / len(items)


def _recompilation_rate(items: Sequence[QualityResult]) -> float:
    if not items:
        return 0.0
    return sum(item.recompilation.passed for item in items) / len(items)


def _median_readability(items: Sequence[QualityResult]) -> float:
    return statistics.median(item.readability.score for item in items) if items else 0.0


def _stable(item: QualityResult) -> bool:
    return (
        item.execution_status is BenchmarkStatus.SUCCESS
        and item.syntax.status in _STABLE_STATUSES
        and item.recompilation.status in _STABLE_STATUSES
        and item.semantics.status in _STABLE_STATUSES
    )


def _stability_rate(items: Sequence[QualityResult]) -> float:
    if not items:
        return 0.0
    return sum(_stable(item) for item in items) / len(items)


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

    # The aggregate corpus deliberately measures broader LunaUX version support, but
    # it cannot by itself prove a same-bytecode win. Build a second mandatory set from
    # the exact cases where the pinned reference actually produced an executable
    # result. For the 0.18 Medal pin this is the compatible v6/g0 surface. Unsupported
    # v3/v11 inputs may improve the aggregate capability score, never the head-to-head
    # release decision.
    compatible_case_ids = tuple(
        sorted(
            case_id
            for case_id, result in right_results.items()
            if result.execution_status is BenchmarkStatus.SUCCESS
            and case_id in left_results
        )
    )
    compatible_left = tuple(left_results[case_id] for case_id in compatible_case_ids)
    compatible_right = tuple(right_results[case_id] for case_id in compatible_case_ids)

    if not compatible_case_ids:
        gate = ReleaseGate(
            contender,
            reference,
            False,
            (),
            0,
            0,
            0,
            "reference produced no executable same-bytecode cases; comparison is invalid",
        )
        return QualityReport(
            report.generated_from,
            report.results,
            report.summaries,
            gate,
        )

    values = (
        ("recompilation_rate", left.recompilation_rate, right.recompilation_rate),
        (
            "semantic_pass_rate",
            _semantic_pass_rate(tuple(left_results.values())),
            _semantic_pass_rate(tuple(right_results.values())),
        ),
        ("median_readability", left.median_readability, right.median_readability),
        ("stability_rate", left.stability_rate, right.stability_rate),
        (
            "compatible_recompilation_rate",
            _recompilation_rate(compatible_left),
            _recompilation_rate(compatible_right),
        ),
        (
            "compatible_semantic_pass_rate",
            _semantic_pass_rate(compatible_left),
            _semantic_pass_rate(compatible_right),
        ),
        (
            "compatible_median_readability",
            _median_readability(compatible_left),
            _median_readability(compatible_right),
        ),
        (
            "compatible_stability_rate",
            _stability_rate(compatible_left),
            _stability_rate(compatible_right),
        ),
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

    wins = losses = ties = 0
    for case_id in compatible_case_ids:
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
        reason = (
            "LunaUX is not worse on any required aggregate or same-bytecode metric "
            f"and wins the compatible paired comparison ({len(compatible_case_ids)} cases)."
        )
    elif not no_regression:
        reason = (
            "LunaUX regresses at least one required aggregate or same-bytecode "
            "correctness/readability/stability metric."
        )
    elif not strict_metric_win:
        reason = "LunaUX does not strictly improve any required metric."
    elif wins <= losses:
        reason = (
            "LunaUX does not win more reference-compatible paired cases than it loses."
        )
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
