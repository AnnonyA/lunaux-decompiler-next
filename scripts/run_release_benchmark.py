from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lunaux import __version__
from lunaux.benchmark_engine import (
    BenchmarkBackend,
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


def main() -> int:
    args = _parser().parse_args()
    cases = load_manifest(args.manifest)
    if len(cases) < args.minimum_cases:
        print(
            f"ERROR: release corpus has {len(cases)} cases; "
            f"at least {args.minimum_cases} are required",
            file=sys.stderr,
        )
        return 2
    required_optimizations = {"O0", "O1", "O2"}
    observed_optimizations = {case.optimization for case in cases}
    if not required_optimizations.issubset(observed_optimizations):
        print(
            "ERROR: release corpus must include O0, O1, and O2",
            file=sys.stderr,
        )
        return 2
    if not all(case.source_path is not None for case in cases):
        print(
            "ERROR: every release case requires a semantic source oracle",
            file=sys.stderr,
        )
        return 2
    observed_debug = {
        tag for case in cases for tag in case.tags if tag in {"debug", "stripped-debug"}
    }
    if observed_debug != {"debug", "stripped-debug"}:
        print(
            "ERROR: release corpus requires debug and stripped-debug variants",
            file=sys.stderr,
        )
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
    backends: list[BenchmarkBackend] = [lunaux]
    backends.extend(load_external_backends(args.external_backends))

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
