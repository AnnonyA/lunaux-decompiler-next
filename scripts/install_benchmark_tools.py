from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PINS = ROOT / "benchmarks" / "pins.json"
MEDAL_LOCK_ARCHIVE = ROOT / "benchmarks" / "medal-Cargo.lock.gz.b64"
MEDAL_LOCK_SHA256 = "4588b89b068c33e4ec07a26afa54634c1be336b46ff956bb2171b60db2fc2d00"


class InstallError(RuntimeError):
    pass


def _run(arguments: list[str], *, cwd: Path | None = None) -> None:
    print("> " + " ".join(arguments), flush=True)
    completed = subprocess.run(arguments, cwd=cwd or ROOT, check=False)
    if completed.returncode != 0:
        raise InstallError(
            f"command failed with exit code {completed.returncode}: {arguments[0]}"
        )


def _capture(arguments: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        arguments,
        cwd=cwd or ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise InstallError(
            f"command failed with exit code {completed.returncode}: "
            f"{arguments[0]}: {detail}"
        )
    return completed.stdout.strip()


def _require(command: str) -> str:
    path = shutil.which(command)
    if path is None:
        raise InstallError(f"required command was not found in PATH: {command}")
    return path


def _load_pins(path: Path) -> dict[str, dict[str, str]]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"could not load benchmark pins: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise InstallError("benchmark pins schema_version must be 1")
    tools = payload.get("tools")
    if not isinstance(tools, dict):
        raise InstallError("benchmark pins must contain a tools object")
    result: dict[str, dict[str, str]] = {}
    for name, raw in tools.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            raise InstallError("benchmark pin entries must be objects")
        repository = raw.get("repository")
        commit = raw.get("commit")
        if not isinstance(repository, str) or not isinstance(commit, str):
            raise InstallError(f"benchmark pin {name} requires repository and commit")
        result[name] = {"repository": repository, "commit": commit}
    return result


def _checkout(
    git: str,
    *,
    repository: str,
    commit: str,
    directory: Path,
    clean: bool,
) -> None:
    if clean:
        shutil.rmtree(directory, ignore_errors=True)
    directory.parent.mkdir(parents=True, exist_ok=True)
    if not (directory / ".git").is_dir():
        if directory.exists():
            shutil.rmtree(directory)
        _run(
            [
                git,
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                repository,
                str(directory),
            ]
        )
    _run(
        [
            git,
            "-C",
            str(directory),
            "fetch",
            "--force",
            "--depth",
            "1",
            "origin",
            commit,
        ]
    )
    _run(
        [
            git,
            "-C",
            str(directory),
            "checkout",
            "--detach",
            "--force",
            commit,
        ]
    )
    actual = _capture([git, "-C", str(directory), "rev-parse", "HEAD"])
    if actual != commit:
        raise InstallError(
            f"checkout mismatch for {repository}: expected {commit}, got {actual}"
        )


def _install_medal_lock(source: Path) -> None:
    try:
        encoded = MEDAL_LOCK_ARCHIVE.read_text(encoding="ascii")
        compressed = base64.b64decode(encoded, validate=True)
        content = gzip.decompress(compressed)
    except (OSError, ValueError, gzip.BadGzipFile) as exc:
        raise InstallError(f"could not restore Medal Cargo.lock: {exc}") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != MEDAL_LOCK_SHA256:
        raise InstallError(
            "Medal Cargo.lock checksum mismatch: "
            f"expected {MEDAL_LOCK_SHA256}, got {digest}"
        )
    (source / "Cargo.lock").write_bytes(content)
    print(f"Medal Cargo.lock verified: {digest}")


def _find_executable(root: Path, names: tuple[str, ...]) -> Path:
    candidates = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.name.lower() in {name.lower() for name in names}
    ]
    if not candidates:
        raise InstallError(
            f"could not find any of {', '.join(names)} below benchmark build {root}"
        )
    candidates.sort(key=lambda path: (len(path.parts), str(path)))
    return candidates[0]


def _copy_executable(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(destination.stat().st_mode | 0o111)
    return destination


def _build_luau(cmake: str, source: Path, bin_directory: Path) -> tuple[Path, Path]:
    build = source / "build-lunaux-benchmark"
    _run(
        [
            cmake,
            "-S",
            str(source),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DLUAU_BUILD_TESTS=OFF",
        ]
    )
    _run(
        [
            cmake,
            "--build",
            str(build),
            "--config",
            "Release",
            "--target",
            "Luau.Repl.CLI",
            "Luau.Compile.CLI",
            "-j2",
        ]
    )
    suffix = ".exe" if os.name == "nt" else ""
    luau = _find_executable(build, (f"luau{suffix}",))
    compiler = _find_executable(build, (f"luau-compile{suffix}",))
    return (
        _copy_executable(luau, bin_directory / f"luau{suffix}"),
        _copy_executable(compiler, bin_directory / f"luau-compile{suffix}"),
    )


def _build_medal(cargo: str, source: Path, bin_directory: Path) -> Path:
    _run(
        [
            cargo,
            "build",
            "--locked",
            "--manifest-path",
            str(source / "Cargo.toml"),
            "--release",
            "-p",
            "luau-lifter",
        ]
    )
    suffix = ".exe" if os.name == "nt" else ""
    executable = source / "target" / "release" / f"luau-lifter{suffix}"
    if not executable.is_file():
        executable = _find_executable(
            source / "target" / "release",
            (f"luau-lifter{suffix}",),
        )
    return _copy_executable(executable, bin_directory / f"medal{suffix}")


def _build_unluau(bin_directory: Path) -> Path:
    runtime = "win-x64" if os.name == "nt" else "linux-x64"
    if sys.platform == "darwin":
        runtime = "osx-x64"
    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_unluau.py"),
            "--runtime",
            runtime,
            "--refresh",
            "--clean",
        ]
    )
    suffix = ".exe" if os.name == "nt" else ""
    candidates = (
        f"unluau{suffix}",
        f"unluau.cli{suffix}",
        "Unluau.CLI.dll",
        "unluau.cli.dll",
    )
    source = _find_executable(ROOT / "tools" / "unluau", candidates)
    destination = bin_directory / source.name
    return _copy_executable(source, destination)


def _path_for_config(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _write_configs(
    output: Path,
    *,
    luau: Path,
    compiler: Path,
    medal: Path,
    medal_commit: str,
    unluau: Path | None,
    unluau_commit: str | None,
) -> None:
    toolchain = {
        "schema_version": 1,
        "syntax_command": [_path_for_config(compiler), "--only-parse", "{source}"],
        "compile_command": [
            _path_for_config(compiler),
            "--binary",
            "-O1",
            "-g0",
            "{source}",
        ],
        "run_command": [_path_for_config(luau), "{source}"],
        "timeout_seconds": 10.0,
    }
    backends: list[dict[str, object]] = [
        {
            "name": "medal",
            "version": medal_commit,
            "command": [_path_for_config(medal), "{input}"],
            "output": "stdout",
        }
    ]
    if unluau is not None and unluau_commit is not None:
        if unluau.suffix.lower() == ".dll":
            command = [
                "dotnet",
                _path_for_config(unluau),
                "--output",
                "{output}",
                "--inline-tables",
                "--smart-variable-names",
                "{input}",
            ]
        else:
            command = [
                _path_for_config(unluau),
                "--output",
                "{output}",
                "--inline-tables",
                "--smart-variable-names",
                "{input}",
            ]
        backends.append(
            {
                "name": "unluau",
                "version": unluau_commit,
                "command": command,
                "output": "file",
            }
        )
    output.mkdir(parents=True, exist_ok=True)
    (output / "toolchain.json").write_text(
        json.dumps(toolchain, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output / "backends.json").write_text(
        json.dumps(
            {"schema_version": 1, "backends": backends},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the exact compiler and competitors pinned for LunaUX 0.18."
    )
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument("--output", type=Path, default=ROOT / ".benchmark-tools")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--include-unluau", action="store_true")
    args = parser.parse_args()

    try:
        pins = _load_pins(args.pins)
        git = _require("git")
        cmake = _require("cmake")
        cargo = _require("cargo")
        source_root = args.output / "source"
        bin_directory = args.output / "bin"
        if args.clean:
            shutil.rmtree(args.output, ignore_errors=True)

        luau_pin = pins["luau"]
        medal_pin = pins["medal"]
        luau_source = source_root / "luau"
        medal_source = source_root / "medal"
        _checkout(
            git,
            repository=luau_pin["repository"],
            commit=luau_pin["commit"],
            directory=luau_source,
            clean=False,
        )
        _checkout(
            git,
            repository=medal_pin["repository"],
            commit=medal_pin["commit"],
            directory=medal_source,
            clean=False,
        )
        _install_medal_lock(medal_source)
        luau, compiler = _build_luau(cmake, luau_source, bin_directory)
        medal = _build_medal(cargo, medal_source, bin_directory)

        unluau: Path | None = None
        unluau_commit: str | None = None
        if args.include_unluau:
            unluau = _build_unluau(bin_directory)
            unluau_commit = pins["unluau"]["commit"]
        _write_configs(
            args.output,
            luau=luau,
            compiler=compiler,
            medal=medal,
            medal_commit=medal_pin["commit"],
            unluau=unluau,
            unluau_commit=unluau_commit,
        )
        print(f"benchmark tools installed in {args.output}")
        return 0
    except (InstallError, KeyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
