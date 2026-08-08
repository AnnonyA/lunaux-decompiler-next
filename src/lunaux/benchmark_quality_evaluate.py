from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from pathlib import Path

from lunaux.benchmark_engine import BenchmarkCase, BenchmarkReport, BenchmarkStatus
from lunaux.benchmark_quality_models import (
    CheckStatus,
    QualityCheck,
    QualityReport,
    QualityResult,
    QualitySummary,
    ReadabilityMetrics,
)
from lunaux.benchmark_quality_readability import readability_metrics
from lunaux.benchmark_quality_toolchain import ExternalToolchain, semantic_check

_STABLE_STATUSES = frozenset(
    {CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.SKIP}
)


def evaluate_quality(
    report: BenchmarkReport,
    cases: Sequence[BenchmarkCase],
    artifact_directory: Path,
    toolchain: ExternalToolchain,
) -> QualityReport:
    by_case = {case.case_id: case for case in cases}
    source_oracles: dict[str, QualityCheck] = {}
    source_text: dict[str, str] = {}
    oracle_by_path: dict[Path, QualityCheck] = {}
    text_by_path: dict[Path, str] = {}
    for case in cases:
        if case.source_path is None:
            continue
        if case.source_path not in oracle_by_path:
            oracle_by_path[case.source_path] = toolchain.execute_source(case.source_path)
            text_by_path[case.source_path] = case.source_path.read_text(encoding="utf-8")
        source_oracles[case.case_id] = oracle_by_path[case.source_path]
        source_text[case.case_id] = text_by_path[case.source_path]

    quality_results: list[QualityResult] = []
    for result in report.results:
        case = by_case[result.case_id]
        if result.status is not BenchmarkStatus.SUCCESS or result.artifact is None:
            skipped = QualityCheck(
                CheckStatus.SKIP,
                detail=f"execution status: {result.status}",
            )
            quality_results.append(
                QualityResult(
                    result.case_id,
                    result.backend,
                    result.backend_version,
                    result.status,
                    result.elapsed_ms,
                    result.peak_memory_bytes,
                    skipped,
                    skipped,
                    skipped,
                    ReadabilityMetrics(0.0, 1, 1.0, 0.0, 0.0),
                )
            )
            continue

        artifact = artifact_directory / result.artifact
        output = artifact.read_text(encoding="utf-8")
        syntax = toolchain.syntax_check(artifact)
        recompile = toolchain.compile_check(artifact)
        if case.source_path is None:
            semantics = QualityCheck(
                CheckStatus.SKIP,
                detail="case has no semantic source oracle",
            )
        elif recompile.status is not CheckStatus.PASS:
            semantics = QualityCheck(
                CheckStatus.SKIP,
                detail="decompiled output did not recompile",
            )
        else:
            semantics = semantic_check(
                source_oracles[result.case_id],
                toolchain.execute_source(artifact),
            )
        quality_results.append(
            QualityResult(
                result.case_id,
                result.backend,
                result.backend_version,
                result.status,
                result.elapsed_ms,
                result.peak_memory_bytes,
                syntax,
                recompile,
                semantics,
                readability_metrics(output, source_text.get(result.case_id)),
            )
        )

    ordered = tuple(
        sorted(quality_results, key=lambda item: (item.backend, item.case_id))
    )
    return QualityReport(str(report.manifest), ordered, summaries(ordered))


def _rate(
    items: Sequence[QualityResult],
    predicate: Callable[[QualityResult], bool],
) -> float:
    return sum(predicate(item) for item in items) / len(items) if items else 0.0


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * 0.95)]


def _is_stable(item: QualityResult) -> bool:
    return (
        item.execution_status is BenchmarkStatus.SUCCESS
        and item.syntax.status in _STABLE_STATUSES
        and item.recompilation.status in _STABLE_STATUSES
        and item.semantics.status in _STABLE_STATUSES
    )


def summaries(results: Sequence[QualityResult]) -> tuple[QualitySummary, ...]:
    grouped: dict[tuple[str, str], list[QualityResult]] = {}
    for result in results:
        grouped.setdefault((result.backend, result.backend_version), []).append(result)

    output: list[QualitySummary] = []
    for (backend, version), items in sorted(grouped.items()):
        semantic = [
            item for item in items if item.semantics.status is not CheckStatus.SKIP
        ]
        memories = [
            item.peak_memory_bytes
            for item in items
            if item.peak_memory_bytes is not None
        ]
        durations = [item.execution_ms for item in items]
        output.append(
            QualitySummary(
                backend,
                version,
                len(items),
                _rate(
                    items,
                    lambda item: item.execution_status is BenchmarkStatus.SUCCESS,
                ),
                _rate(items, lambda item: item.syntax.passed),
                _rate(items, lambda item: item.recompilation.passed),
                len(semantic),
                _rate(semantic, lambda item: item.semantics.passed),
                _rate(items, lambda item: item.readability.fallback_count == 0),
                statistics.median(item.readability.score for item in items),
                _rate(items, _is_stable),
                statistics.median(durations),
                _p95(durations),
                int(statistics.median(memories)) if memories else None,
                max(memories) if memories else None,
            )
        )
    return tuple(output)
