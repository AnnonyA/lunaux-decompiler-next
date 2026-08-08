"""Compatibility facade for the LunaUX differential benchmark API."""

from lunaux.benchmark_engine import (
    BackendExecution,
    BenchmarkBackend,
    BenchmarkCase,
    BenchmarkReport,
    BenchmarkResult,
    BenchmarkStatus,
    BenchmarkSummary,
    ExternalCommandBackend,
    InProcessBackend,
    default_options,
    load_external_backends,
    load_manifest,
    run_benchmark,
)

__all__ = [
    "BackendExecution",
    "BenchmarkBackend",
    "BenchmarkCase",
    "BenchmarkReport",
    "BenchmarkResult",
    "BenchmarkStatus",
    "BenchmarkSummary",
    "ExternalCommandBackend",
    "InProcessBackend",
    "default_options",
    "load_external_backends",
    "load_manifest",
    "run_benchmark",
]
