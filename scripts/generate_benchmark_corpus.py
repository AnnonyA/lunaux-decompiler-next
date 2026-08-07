from __future__ import annotations

import argparse
from pathlib import Path

from lunaux.benchmark_corpus import generate_corpus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the reproducible LunaUX 0.18 semantic corpus at O0/O1/O2 "
            "with stripped and full debug information."
        )
    )
    parser.add_argument("--luau-compile", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmark-corpus-v018"))
    parser.add_argument("--seeds", type=int, default=24)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    build = generate_corpus(
        args.output,
        (
            str(args.luau_compile),
            "--binary",
            "-O{optimization}",
            "-g{debug}",
            "{source}",
        ),
        seeds=args.seeds,
        timeout_seconds=args.timeout,
    )
    print(
        f"generated {build.bytecodes} bytecodes from {build.sources} sources: "
        f"{build.manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
