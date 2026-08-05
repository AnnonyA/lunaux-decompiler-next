from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from lunaux.backends.base import DecompilerBackend
from lunaux.errors import ErrorCode, LunaUXError

_CANDIDATE_NAMES = (
    "unluau",
    "unluau.exe",
    "Unluau.CLI",
    "Unluau.CLI.exe",
)
_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


class UnluauBackend(DecompilerBackend):
    """Adapter for the Apache-2.0 Unluau command-line decompiler.

    Unluau is kept as a separate process on purpose. This avoids importing a
    second runtime into the API process, makes failures containable, and keeps
    the integration compatible with both framework-dependent DLLs and native
    Windows/Linux executables.
    """

    def __init__(
        self,
        executable_path: str | None = None,
        timeout_seconds: int = 45,
        *,
        command: Sequence[str] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._timeout_seconds = timeout_seconds
        self._command = (
            tuple(command)
            if command is not None
            else self._resolve_command(executable_path)
        )
        if not self._command:
            raise LunaUXError(
                ErrorCode.BACKEND_UNAVAILABLE,
                "The Unluau command is empty.",
                status_code=503,
            )
        self._version = self._read_version()

    @property
    def name(self) -> str:
        return "unluau"

    @property
    def version(self) -> str:
        return self._version

    @property
    def command(self) -> tuple[str, ...]:
        return self._command

    @staticmethod
    def _resolve_command(executable_path: str | None) -> tuple[str, ...]:
        resolved = UnluauBackend._find_executable(executable_path)
        if resolved.suffix.lower() == ".dll":
            dotnet = shutil.which("dotnet")
            if dotnet is None:
                raise LunaUXError(
                    ErrorCode.BACKEND_UNAVAILABLE,
                    "Unluau was configured as a .NET DLL, but 'dotnet' was not found.",
                    status_code=503,
                )
            return (dotnet, str(resolved))
        return (str(resolved),)

    @staticmethod
    def _find_executable(executable_path: str | None) -> Path:
        if executable_path:
            expanded = Path(os.path.expandvars(executable_path)).expanduser()
            if expanded.is_file():
                return expanded.resolve()
            discovered = shutil.which(executable_path)
            if discovered:
                return Path(discovered).resolve()
            raise LunaUXError(
                ErrorCode.BACKEND_UNAVAILABLE,
                f"Configured Unluau executable was not found: {executable_path}",
                status_code=503,
            )

        for candidate in UnluauBackend._local_candidates():
            if candidate.is_file():
                return candidate.resolve()
        for name in _CANDIDATE_NAMES:
            discovered = shutil.which(name)
            if discovered:
                return Path(discovered).resolve()
        raise LunaUXError(
            ErrorCode.BACKEND_UNAVAILABLE,
            "Unluau was not found. Set LUNAUX_UNLUAU_PATH or place it under tools/unluau.",
            status_code=503,
        )

    @staticmethod
    def _local_candidates() -> tuple[Path, ...]:
        roots = [Path.cwd()]
        package_root = Path(__file__).resolve().parents[3]
        if package_root not in roots:
            roots.append(package_root)
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            roots.append(Path(local_app_data) / "LunaUX")

        relative_names = (
            Path("tools/unluau/unluau.exe"),
            Path("tools/unluau/unluau"),
            Path("tools/unluau/Unluau.CLI.exe"),
            Path("tools/unluau/Unluau.CLI"),
            Path("tools/unluau/Unluau.CLI.dll"),
            Path("unluau/unluau.exe"),
            Path("unluau/Unluau.CLI.exe"),
            Path("unluau/Unluau.CLI.dll"),
        )
        return tuple(root / relative for root in roots for relative in relative_names)

    def _read_version(self) -> str:
        for flag in ("--version", "-v"):
            try:
                process = subprocess.run(
                    [*self._command, flag],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=min(self._timeout_seconds, 5),
                    check=False,
                    creationflags=_NO_WINDOW,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            output = "\n".join(part for part in (process.stdout, process.stderr) if part)
            first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
            if first_line:
                return first_line[:120]
        return "unknown"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="lunaux-unluau-") as temp_name:
            temp = Path(temp_name)
            input_path = temp / (filename or "chunk.luac")
            output_path = temp / "decompiled.luau"
            log_path = temp / "unluau.log"
            input_path.write_bytes(bytecode)

            arguments = [
                str(input_path),
                "--output",
                str(output_path),
                "--logs",
                str(log_path),
                "--inline-tables",
                "--smart-variable-names",
                "--rename-upvalues",
            ]
            if not options.get("StringInterpolation", True):
                arguments.extend(("--string-interpolation", "false"))

            process = self._execute(arguments, temp)
            if process.returncode != 0:
                raise self._process_error("decompilation", process, log_path)
            try:
                result = output_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise LunaUXError(
                    ErrorCode.BACKEND_FAILURE,
                    f"Unluau did not create its output file: {exc}",
                    status_code=422,
                ) from exc
            if not result.strip():
                raise self._process_error("decompilation produced empty output", process, log_path)
            return result

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        with tempfile.TemporaryDirectory(prefix="lunaux-unluau-") as temp_name:
            temp = Path(temp_name)
            input_path = temp / (filename or "chunk.luac")
            output_path = temp / "discarded-decompile.luau"
            log_path = temp / "unluau.log"
            input_path.write_bytes(bytecode)

            process = self._execute(
                [
                    str(input_path),
                    "--dissasemble",
                    "--output",
                    str(output_path),
                    "--logs",
                    str(log_path),
                ],
                temp,
            )
            if process.returncode != 0:
                raise self._process_error("disassembly", process, log_path)
            result = process.stdout.strip()
            if not result:
                raise self._process_error("disassembly produced empty output", process, log_path)
            return result

    def _execute(self, arguments: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [*self._command, *arguments],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                check=False,
                creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise LunaUXError(
                ErrorCode.BACKEND_FAILURE,
                f"Unluau exceeded the {self._timeout_seconds}-second timeout.",
                status_code=504,
            ) from exc
        except OSError as exc:
            raise LunaUXError(
                ErrorCode.BACKEND_UNAVAILABLE,
                f"Could not start Unluau: {exc}",
                status_code=503,
            ) from exc

    @staticmethod
    def _process_error(
        operation: str,
        process: subprocess.CompletedProcess[str],
        log_path: Path,
    ) -> LunaUXError:
        details: list[str] = []
        for value in (process.stderr, process.stdout):
            cleaned = value.strip()
            if cleaned:
                details.append(cleaned)
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            log_text = ""
        if log_text:
            details.append(log_text)
        excerpt = " | ".join(details).replace("\n", " ")[:800]
        suffix = f": {excerpt}" if excerpt else "."
        return LunaUXError(
            ErrorCode.BACKEND_FAILURE,
            f"Unluau {operation} failed{suffix}",
            status_code=422,
        )
