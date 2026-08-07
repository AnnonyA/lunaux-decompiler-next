from __future__ import annotations

import json
import sys
from pathlib import Path

from lunaux.benchmark_corpus import generate_corpus
from lunaux.benchmark_corpus_templates import TEMPLATES
from lunaux.benchmark_engine import (
    BenchmarkCase,
    BenchmarkReport,
    BenchmarkResult,
    BenchmarkStatus,
)
from lunaux.benchmark_quality import (
    CheckStatus,
    QualityCheck,
    QualityReport,
    QualityResult,
    QualitySummary,
    ReadabilityMetrics,
    apply_release_gate,
    evaluate_quality,
    readability_metrics,
)
from lunaux.benchmarking import BenchmarkStatus as PublicBenchmarkStatus


class _PassingToolchain:
    def syntax_check(self, source: Path) -> QualityCheck:
        assert source.is_file()
        return QualityCheck(CheckStatus.PASS)

    def compile_check(self, source: Path) -> QualityCheck:
        assert source.is_file()
        return QualityCheck(CheckStatus.PASS)

    def execute_source(self, source: Path) -> QualityCheck:
        return QualityCheck(CheckStatus.PASS, detail=source.read_text(encoding="utf-8"))


def _quality_result(
    backend: str,
    *,
    readability: float,
    semantic: CheckStatus = CheckStatus.PASS,
    fallback_count: int = 0,
) -> QualityResult:
    passed = QualityCheck(CheckStatus.PASS)
    return QualityResult(
        "case",
        backend,
        "pinned",
        BenchmarkStatus.SUCCESS,
        1.0,
        1024,
        passed,
        passed,
        QualityCheck(semantic),
        ReadabilityMetrics(readability, fallback_count, 0.0, 1.0, 1.0),
    )


def _summary(
    backend: str,
    *,
    recompilation: float,
    semantics: float,
    readability: float,
    stability: float,
) -> QualitySummary:
    return QualitySummary(
        backend,
        "pinned",
        1,
        1.0,
        1.0,
        recompilation,
        1,
        semantics,
        1.0,
        readability,
        stability,
        1.0,
        1.0,
        1024,
        1024,
    )


def test_public_benchmark_facade_uses_the_measured_engine() -> None:
    assert PublicBenchmarkStatus is BenchmarkStatus


def test_default_corpus_matrix_contains_exactly_2304_bytecodes(tmp_path: Path) -> None:
    fake_compiler = (
        sys.executable,
        "-c",
        (
            "from pathlib import Path; import sys; "
            "source=Path(sys.argv[1]).read_bytes(); "
            "sys.stdout.buffer.write(b'BC'+sys.argv[2].encode()+"
            "sys.argv[3].encode()+source)"
        ),
        "{source}",
        "{optimization}",
        "{debug}",
    )
    build = generate_corpus(tmp_path, fake_compiler)

    assert len(TEMPLATES) == 16
    assert build.sources == 16 * 24
    assert build.bytecodes == 2304
    payload = json.loads(build.manifest.read_text(encoding="utf-8"))
    assert len(payload["cases"]) == 2304
    assert {case["optimization"] for case in payload["cases"]} == {
        "O0",
        "O1",
        "O2",
    }
    tags = {tag for case in payload["cases"] for tag in case["tags"]}
    assert {"debug", "stripped-debug"}.issubset(tags)


def test_quality_evaluation_checks_syntax_recompile_semantics_and_readability(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.luau"
    source.write_text("print(7)\n", encoding="utf-8")
    bytecode = tmp_path / "case.luac"
    bytecode.write_bytes(b"bytecode")
    artifact_directory = tmp_path / "artifacts"
    artifact = artifact_directory / "lunaux" / "case.luau"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("print(7)\n", encoding="utf-8")
    case = BenchmarkCase("case", bytecode, source, ("semantic-oracle",), "O2")
    raw = BenchmarkReport(
        "now",
        str(tmp_path / "manifest.json"),
        (
            BenchmarkResult(
                "case",
                "lunaux",
                "pinned",
                BenchmarkStatus.SUCCESS,
                1.0,
                9,
                "digest",
                "lunaux/case.luau",
                peak_memory_bytes=2048,
            ),
        ),
        (),
    )

    report = evaluate_quality(raw, (case,), artifact_directory, _PassingToolchain())

    result = report.results[0]
    assert result.syntax.status is CheckStatus.PASS
    assert result.recompilation.status is CheckStatus.PASS
    assert result.semantics.status is CheckStatus.PASS
    assert result.readability.fallback_count == 0
    assert report.summaries[0].semantic_equivalence_rate == 1.0


def test_generic_lunaux_header_is_not_counted_as_a_fallback() -> None:
    metrics = readability_metrics(
        "-- Higher-fidelity reconstruction requires a compatible backend.\nreturn 1\n",
        "return 1\n",
    )
    assert metrics.fallback_count == 0


def test_release_gate_requires_no_regressions_and_more_case_wins() -> None:
    report = QualityReport(
        "manifest.json",
        (
            _quality_result("lunaux", readability=90.0),
            _quality_result("medal", readability=70.0),
        ),
        (
            _summary(
                "lunaux",
                recompilation=1.0,
                semantics=1.0,
                readability=90.0,
                stability=1.0,
            ),
            _summary(
                "medal",
                recompilation=0.5,
                semantics=0.5,
                readability=70.0,
                stability=1.0,
            ),
        ),
    )

    gated = apply_release_gate(report, "lunaux", "medal")

    assert gated.release_gate is not None
    assert gated.release_gate.passed
    assert gated.release_gate.case_wins == 1
    assert gated.release_gate.case_losses == 0


def test_release_gate_fails_when_lunaux_regresses_readability() -> None:
    report = QualityReport(
        "manifest.json",
        (
            _quality_result("lunaux", readability=60.0),
            _quality_result("medal", readability=80.0),
        ),
        (
            _summary(
                "lunaux",
                recompilation=1.0,
                semantics=1.0,
                readability=60.0,
                stability=1.0,
            ),
            _summary(
                "medal",
                recompilation=0.5,
                semantics=0.5,
                readability=80.0,
                stability=1.0,
            ),
        ),
    )

    gated = apply_release_gate(report, "lunaux", "medal")

    assert gated.release_gate is not None
    assert not gated.release_gate.passed
    assert "regresses" in gated.release_gate.reason
