from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from lunaux import __version__
from lunaux.api.app import create_app
from lunaux.backends.auto import build_backend
from lunaux.config import Settings
from lunaux.errors import LunaUXError
from lunaux.hashing import installation_hash
from lunaux.io import InputFormat, decode_input
from lunaux.models import DecompileOptions
from lunaux.service import DecompilerService

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
error_console = Console(stderr=True)


def _version_option(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


def _hash_option(value: bool) -> None:
    if value:
        typer.echo(installation_hash())
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-v",
            callback=_version_option,
            is_eager=True,
            help="Show version information and exit.",
        ),
    ] = False,
    show_hash: Annotated[
        bool,
        typer.Option(
            "--hash",
            "-ih",
            callback=_hash_option,
            is_eager=True,
            help="Show the current installation SHA-256 and exit.",
        ),
    ] = False,
) -> None:
    """ByteWeft local Luau bytecode analysis tools."""
    del version, show_hash


def _service() -> DecompilerService:
    settings = Settings.from_env()
    backend = build_backend(
        settings.backend_module,
        settings.backend_mode,
        settings.native_path,
        settings.unluau_path,
        settings.external_timeout_seconds,
    )
    return DecompilerService(backend, settings.max_bytecode_bytes)


def _read(path: Path, input_format: InputFormat) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise typer.BadParameter(f"Could not read '{path}': {exc}") from exc
    return decode_input(data, input_format)


def _write_or_print(text: str, output: Path | None) -> None:
    if output is None:
        typer.echo(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    console.print(f"[green]Saved:[/green] {output}")


def _resolve_output(
    operation: str,
    input_path: Path,
    output_directory: Path | None,
    output: Path | None,
) -> Path | None:
    if output_directory is not None and output is not None:
        raise typer.BadParameter("Use either output_directory or --output, not both.")
    if output is not None:
        return output
    if output_directory is None:
        return None
    suffix = ".luau" if operation == "decompile" else ".disasm.txt"
    return output_directory / f"{input_path.stem}{suffix}"


def _run(
    operation: str,
    input_path: Path,
    output_directory: Path | None,
    output: Path | None,
    input_format: InputFormat,
    include_header: bool = True,
) -> None:
    try:
        bytecode = _read(input_path, input_format)
        service = _service()
        if operation == "decompile":
            result = service.decompile(
                bytecode,
                DecompileOptions(IncludeHeader=include_header),
                input_path.name,
            )
        else:
            result = service.disassemble(bytecode, input_path.name)
        _write_or_print(
            result,
            _resolve_output(operation, input_path, output_directory, output),
        )
    except LunaUXError as exc:
        error_console.print(f"[red]{exc.code}:[/red] {exc.message}")
        raise typer.Exit(code=1) from exc
    except (OSError, ValueError) as exc:
        error_console.print(f"[red]Configuration or I/O error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def _serve(host: str, port: int, log_level: str) -> None:
    try:
        api = create_app()
    except (LunaUXError, ValueError) as exc:
        message = exc.message if isinstance(exc, LunaUXError) else str(exc)
        error_console.print(f"[red]Startup error:[/red] {message}")
        raise typer.Exit(code=1) from exc
    uvicorn.run(api, host=host, port=port, log_level=log_level, access_log=False)


@app.command()
def decompile(
    input_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output_directory: Annotated[Path | None, typer.Argument(file_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    input_format: Annotated[InputFormat, typer.Option("--input-format")] = InputFormat.AUTO,
    include_header: Annotated[bool, typer.Option("--header/--no-header")] = True,
) -> None:
    """Decompile a raw or Base64-encoded Luau bytecode file."""
    _run("decompile", input_path, output_directory, output, input_format, include_header)


@app.command(name="decomp")
def decomp_alias(
    input_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output_directory: Annotated[Path | None, typer.Argument(file_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    input_format: Annotated[InputFormat, typer.Option("--input-format")] = InputFormat.AUTO,
    include_header: Annotated[bool, typer.Option("--header/--no-header")] = True,
) -> None:
    """Alias for ``decompile``."""
    _run("decompile", input_path, output_directory, output, input_format, include_header)


@app.command()
def disassemble(
    input_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output_directory: Annotated[Path | None, typer.Argument(file_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    input_format: Annotated[InputFormat, typer.Option("--input-format")] = InputFormat.AUTO,
) -> None:
    """Disassemble a raw or Base64-encoded Luau bytecode file."""
    _run("disassemble", input_path, output_directory, output, input_format)


@app.command(name="disasm")
def disasm_alias(
    input_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output_directory: Annotated[Path | None, typer.Argument(file_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    input_format: Annotated[InputFormat, typer.Option("--input-format")] = InputFormat.AUTO,
) -> None:
    """Alias for ``disassemble``."""
    _run("disassemble", input_path, output_directory, output, input_format)


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
    log_level: Annotated[str, typer.Option()] = "info",
) -> None:
    """Run the local HTTP API."""
    _serve(host, port, log_level)


@app.command()
def run(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
    log_level: Annotated[str, typer.Option()] = "info",
) -> None:
    """Classic alias for ``serve``."""
    _serve(host, port, log_level)


@app.command()
def doctor() -> None:
    """Check Python, configuration, native, Unluau, and fallback engines."""
    try:
        settings = Settings.from_env()
        backend = build_backend(
            settings.backend_module,
            settings.backend_mode,
            settings.native_path,
            settings.unluau_path,
            settings.external_timeout_seconds,
        )
    except (LunaUXError, ValueError) as exc:
        error_console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title="ByteWeft diagnostics")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("ByteWeft", __version__)
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Backend mode", settings.backend_mode.value)
    table.add_row("Backend module", settings.backend_module)
    table.add_row("Native path", settings.native_path or "auto-detect / not configured")
    table.add_row("Unluau path", settings.unluau_path or "auto-detect")
    table.add_row("External timeout", f"{settings.external_timeout_seconds} seconds")
    table.add_row("Active backend", backend.name)
    table.add_row("Engines", " -> ".join(item.name for item in backend.backends))
    table.add_row("Backend version", backend.version)
    table.add_row("Bytecode limit", f"{settings.max_bytecode_bytes} bytes")
    console.print(table)
    if backend.fallback_reason:
        error_console.print(f"[yellow]{backend.fallback_reason}[/yellow]")


@app.command(name="version")
def version_command() -> None:
    """Print the ByteWeft version."""
    typer.echo(__version__)
