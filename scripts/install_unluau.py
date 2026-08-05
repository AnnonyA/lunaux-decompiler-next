from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "third_party" / "unluau"
OUTPUT_DIR = ROOT / "tools" / "unluau"
UPSTREAM_URL = "https://github.com/atrexus/unluau.git"
PINNED_COMMIT = "f89e03a560f535eb19f11e89a6aadec636d2a8f5"


class InstallError(RuntimeError):
    pass


def _require(command: str) -> str:
    path = shutil.which(command)
    if path is None:
        raise InstallError(f"Required command was not found in PATH: {command}")
    return path


def _run(arguments: list[str], *, cwd: Path | None = None) -> None:
    print("> " + " ".join(arguments))
    process = subprocess.run(
        arguments,
        cwd=cwd or ROOT,
        check=False,
        text=True,
    )
    if process.returncode:
        raise InstallError(
            f"Command failed with exit code {process.returncode}: {arguments[0]}"
        )


def _capture(arguments: list[str], *, cwd: Path | None = None) -> str:
    process = subprocess.run(
        arguments,
        cwd=cwd or ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode:
        details = (process.stderr or process.stdout).strip()
        raise InstallError(
            f"Command failed with exit code {process.returncode}: "
            f"{arguments[0]}: {details}"
        )
    return process.stdout.strip()


def _default_runtime() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        architecture = "x64"
    elif machine in {"x86", "i386", "i686"}:
        architecture = "x86"
    elif machine in {"arm64", "aarch64"}:
        architecture = "arm64"
    else:
        raise InstallError(
            f"Could not choose a .NET runtime for architecture {machine!r}; "
            "pass --runtime explicitly."
        )

    if os.name == "nt":
        return f"win-{architecture}"
    if sys.platform.startswith("linux"):
        return f"linux-{architecture}"
    if sys.platform == "darwin":
        return f"osx-{architecture}"
    raise InstallError(
        f"Could not choose a .NET runtime for {sys.platform!r}; "
        "pass --runtime explicitly."
    )


def _prepare_source(git: str, *, refresh: bool) -> None:
    SOURCE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not (SOURCE_DIR / ".git").is_dir():
        if SOURCE_DIR.exists():
            shutil.rmtree(SOURCE_DIR)
        _run(
            [
                git,
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                UPSTREAM_URL,
                str(SOURCE_DIR),
            ]
        )

    if refresh:
        _run(
            [
                git,
                "-C",
                str(SOURCE_DIR),
                "fetch",
                "--force",
                "--depth",
                "1",
                "origin",
                PINNED_COMMIT,
            ]
        )
    else:
        has_commit = subprocess.run(
            [
                git,
                "-C",
                str(SOURCE_DIR),
                "cat-file",
                "-e",
                f"{PINNED_COMMIT}^{{commit}}",
            ],
            check=False,
            capture_output=True,
        ).returncode == 0
        if not has_commit:
            _run(
                [
                    git,
                    "-C",
                    str(SOURCE_DIR),
                    "fetch",
                    "--depth",
                    "1",
                    "origin",
                    PINNED_COMMIT,
                ]
            )

    _run(
        [
            git,
            "-C",
            str(SOURCE_DIR),
            "checkout",
            "--detach",
            "--force",
            PINNED_COMMIT,
        ]
    )
    current = _capture(
        [git, "-C", str(SOURCE_DIR), "rev-parse", "HEAD"]
    )
    if current != PINNED_COMMIT:
        raise InstallError(
            f"Unluau checkout mismatch: expected {PINNED_COMMIT}, got {current}"
        )


def _publish(dotnet: str, runtime: str) -> None:
    project = SOURCE_DIR / "src" / "Unluau.CLI" / "Unluau.CLI.csproj"
    if not project.is_file():
        raise InstallError(f"Unluau CLI project was not found: {project}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for child in OUTPUT_DIR.iterdir():
        if child.name == "README.md":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    _run(
        [
            dotnet,
            "publish",
            str(project),
            "--configuration",
            "Release",
            "--runtime",
            runtime,
            "--self-contained",
            "true",
            "-p:PublishSingleFile=true",
            "-p:IncludeNativeLibrariesForSelfExtract=true",
            "--output",
            str(OUTPUT_DIR),
        ]
    )

    license_path = SOURCE_DIR / "LICENSE"
    if license_path.is_file():
        shutil.copy2(license_path, OUTPUT_DIR / "LICENSE-Unluau.txt")

    manifest = {
        "upstream": UPSTREAM_URL,
        "commit": PINNED_COMMIT,
        "runtime": runtime,
        "built_with": _capture([dotnet, "--version"]),
    }
    (OUTPUT_DIR / "unluau-build.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    candidates = [
        item
        for item in OUTPUT_DIR.iterdir()
        if item.name.lower()
        in {
            "unluau",
            "unluau.exe",
            "unluau.cli",
            "unluau.cli.exe",
            "unluau.cli.dll",
        }
    ]
    if not candidates:
        names = ", ".join(sorted(item.name for item in OUTPUT_DIR.iterdir()))
        raise InstallError(
            "The build completed, but no recognized Unluau CLI binary was found. "
            f"Output files: {names}"
        )
    print("Unluau installed:")
    for candidate in candidates:
        print(f"  {candidate}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the pinned Apache-2.0 Unluau source and build its CLI "
            "for LunaUX Next."
        )
    )
    parser.add_argument(
        "--runtime",
        help="dotnet runtime identifier, for example win-x64 or linux-x64",
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="fetch and pin the source without building it",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="force-fetch the pinned upstream commit",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the existing source and build before continuing",
    )
    arguments = parser.parse_args()

    try:
        if arguments.clean:
            shutil.rmtree(SOURCE_DIR, ignore_errors=True)
            if OUTPUT_DIR.exists():
                for child in OUTPUT_DIR.iterdir():
                    if child.name != "README.md":
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()

        git = _require("git")
        _prepare_source(git, refresh=arguments.refresh)
        print(f"Unluau source pinned at {PINNED_COMMIT}")

        if arguments.source_only:
            return 0

        dotnet = _require("dotnet")
        runtime = arguments.runtime or _default_runtime()
        _publish(dotnet, runtime)
        return 0
    except (InstallError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
