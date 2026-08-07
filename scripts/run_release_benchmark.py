from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from lunaux import __version__
from lunaux.benchmark_engine import (
    BenchmarkBackend,
    BenchmarkCase,
    ExternalCommandBackend,
    load_external_backends,
    load_manifest,
    run_benchmark,
)
from lunaux.benchmark_quality import apply_release_gate, evaluate_quality, load_toolchain

ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the LunaUX 0.18 public correctness, equivalence, readability, "
            "stability, performance, and memory benchmark."
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--external-backends", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("benchmark-artifacts"))
    parser.add_argument("--raw-report", type=Path, default=Path("benchmark-report.json"))
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=Path("benchmark-quality-report.json"),
    )
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=Path("benchmark-quality-report.md"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--contender", default="lunaux")
    parser.add_argument("--reference", default="medal")
    parser.add_argument("--minimum-cases", type=int, default=2304)
    parser.add_argument("--require-gate", action="store_true")
    return parser


def _validate_release_corpus(
    cases: Sequence[BenchmarkCase],
    minimum_cases: int,
) -> str | None:
    if len(cases) < minimum_cases:
        return (
            f"release corpus has {len(cases)} cases; "
            f"at least {minimum_cases} are required"
        )
    required_optimizations = {"O0", "O1", "O2"}
    observed_optimizations = {case.optimization for case in cases}
    if not required_optimizations.issubset(observed_optimizations):
        return "release corpus must include O0, O1, and O2"
    if not all(case.source_path is not None for case in cases):
        return "every release case requires a semantic source oracle"

    all_tags = [tag for case in cases for tag in case.tags]
    observed_debug = {
        tag for tag in all_tags if tag in {"debug", "stripped-debug"}
    }
    if observed_debug != {"debug", "stripped-debug"}:
        return "release corpus requires debug and stripped-debug variants"
    version_counts = Counter(
        tag
        for tag in all_tags
        if tag in {"bytecode-v3", "bytecode-v6", "bytecode-v11"}
    )
    expected_per_version = minimum_cases // 3
    expected = {
        "bytecode-v3": expected_per_version,
        "bytecode-v6": expected_per_version,
        "bytecode-v11": expected_per_version,
    }
    if version_counts != expected:
        return (
            "release corpus requires balanced v3/v6/v11 coverage: "
            f"expected {expected}, got {dict(version_counts)}"
        )
    return None


def main() -> int:
    args = _parser().parse_args()
    cases = load_manifest(args.manifest)
    corpus_error = _validate_release_corpus(cases, args.minimum_cases)
    if corpus_error is not None:
        print(f"ERROR: {corpus_error}", file=sys.stderr)
        return 2

    lunaux = ExternalCommandBackend(
        backend_name="lunaux",
        backend_version=__version__,
        command=(
            sys.executable,
            str(ROOT / "scripts" / "benchmark_lunaux_backend.py"),
            "{input}",
            "{output}",
        ),
        output_mode="file",
    )
    external = load_external_backends(args.external_backends)
    external_names = {backend.name for backend in external}
    if not {"medal", "unluau"}.issubset(external_names):
        print(
            "ERROR: release benchmark requires pinned Medal and Unluau backends",
            file=sys.stderr,
        )
        return 2
    backends: list[BenchmarkBackend] = [lunaux, *external]

    raw = run_benchmark(
        args.manifest,
        cases,
        backends,
        args.artifacts,
        timeout_seconds=args.timeout,
    )
    raw.write_json(args.raw_report)
    quality = evaluate_quality(
        raw,
        cases,
        args.artifacts,
        load_toolchain(args.toolchain),
    )
    quality = apply_release_gate(quality, args.contender, args.reference)
    quality.write_json(args.quality_report)
    quality.write_markdown(args.markdown_report)

    for summary in quality.summaries:
        print(
            f"{summary.backend} {summary.backend_version}: "
            f"execute={summary.execution_success_rate:.2%}, "
            f"syntax={summary.syntax_rate:.2%}, "
            f"recompile={summary.recompilation_rate:.2%}, "
            f"semantic={summary.semantic_equivalence_rate:.2%}, "
            f"readability={summary.median_readability:.2f}, "
            f"stability={summary.stability_rate:.2%}"
        )
    gate = quality.release_gate
    if gate is None:
        print("ERROR: release gate was not produced", file=sys.stderr)
        return 2
    print(
        f"0.18 gate: {'PASS' if gate.passed else 'FAIL'}; "
        f"wins/losses/ties={gate.case_wins}/{gate.case_losses}/{gate.case_ties}; "
        f"{gate.reason}"
    )
    if args.require_gate and not gate.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
