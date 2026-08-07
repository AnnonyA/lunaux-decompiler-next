from __future__ import annotations

import argparse
from pathlib import Path

from lunaux.benchmark_corpus import CompilerProfile, generate_corpus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the reproducible LunaUX 0.18 semantic corpus across "
            "Luau bytecode v3, v6, and v11 at O0/O1/O2 with g0/g2."
        )
    )
    parser.add_argument("--luau-v3-compile", type=Path, required=True)
    parser.add_argument("--luau-v6-compile", type=Path, required=True)
    parser.add_argument("--luau-v11-compile", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("benchmark-corpus-v018"))
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser


def _profile(name: str, version: int, executable: Path) -> CompilerProfile:
    return CompilerProfile(
        name,
        version,
        (
            str(executable),
            "--binary",
            "-O{optimization}",
            "-g{debug}",
            "{source}",
        ),
    )


def main() -> int:
    args = _parser().parse_args()
    build = generate_corpus(
        args.output,
        (
            _profile("luau-v3", 3, args.luau_v3_compile),
            _profile("luau-v6", 6, args.luau_v6_compile),
            _profile("luau-v11", 11, args.luau_v11_compile),
        ),
        seeds=args.seeds,
        timeout_seconds=args.timeout,
    )
    profiles = ", ".join(build.compiler_profiles)
    print(
        f"generated {build.bytecodes} bytecodes from {build.sources} sources "
        f"across {profiles}: {build.manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
