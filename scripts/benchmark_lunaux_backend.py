from __future__ import annotations

import argparse
from pathlib import Path

from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.benchmark_engine import default_options


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute the portable LunaUX backend for one benchmark case."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    backend = ReconstructedBackend()
    source = backend.decompile(
        args.input.read_bytes(),
        dict(default_options()),
        args.input.name,
    )
    if not source.strip():
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
