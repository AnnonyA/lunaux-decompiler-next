from __future__ import annotations

import argparse
from pathlib import Path

from lunaux.backends.auto import build_backend
from lunaux.benchmarking import (
    BenchmarkBackend,
    InProcessBackend,
    default_options,
    load_external_backends,
    load_manifest,
    run_benchmark,
)
from lunaux.config import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the LunaUX 0.18 differential decompiler benchmark."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--external-backends", type=Path)
    parser.add_argument("--output", type=Path, default=Path("benchmark-report.json"))
    parser.add_argument("--artifacts", type=Path, default=Path("benchmark-artifacts"))
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    settings = Settings.from_env()
    backend = build_backend(
        settings.backend_module,
        settings.backend_mode,
        settings.native_path,
        settings.unluau_path,
        settings.external_timeout_seconds,
    )
    backends: list[BenchmarkBackend] = [
        InProcessBackend(backend, default_options())
    ]
    if args.external_backends is not None:
        backends.extend(load_external_backends(args.external_backends))

    report = run_benchmark(
        args.manifest,
        load_manifest(args.manifest),
        backends,
        args.artifacts,
        timeout_seconds=args.timeout,
    )
    report.write_json(args.output)
    for summary in report.summaries:
        print(
            f"{summary.backend} {summary.backend_version}: "
            f"{summary.successes}/{summary.total} success "
            f"({summary.success_rate:.1%}), median={summary.median_ms:.2f}ms, "
            f"p95={summary.p95_ms:.2f}ms"
        )
    print(f"report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
