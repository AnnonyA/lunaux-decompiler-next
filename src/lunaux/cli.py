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
from lunaux.backends.native import NativeModuleBackend
from lunaux.config import Settings
from lunaux.errors import LunaUXError
from lunaux.io import InputFormat, decode_input
from lunaux.models import DecompileOptions
from lunaux.service import DecompilerService

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
error_console = Console(stderr=True)


def _service() -> DecompilerService:
    settings = Settings.from_env()
    return DecompilerService(
        NativeModuleBackend(settings.backend_module),
        settings.max_bytecode_bytes,
    )


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


def _run(operation: str, input_path: Path, output: Path | None, input_format: InputFormat) -> None:
    try:
        bytecode = _read(input_path, input_format)
        service = _service()
        if operation == "decompile":
            result = service.decompile(bytecode, DecompileOptions(), input_path.name)
        else:
            result = service.disassemble(bytecode, input_path.name)
        _write_or_print(result, output)
    except LunaUXError as exc:
        error_console.print(f"[red]{exc.code}:[/red] {exc.message}")
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        error_console.print(f"[red]I/O error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def decompile(
    input_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    input_format: Annotated[InputFormat, typer.Option("--input-format")] = InputFormat.AUTO,
) -> None:
    """Decompile one raw or Base64-encoded Luau bytecode file."""
    _run("decompile", input_path, output, input_format)


@app.command()
def disassemble(
    input_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    input_format: Annotated[InputFormat, typer.Option("--input-format")] = InputFormat.AUTO,
) -> None:
    """Disassemble one raw or Base64-encoded Luau bytecode file."""
    _run("disassemble", input_path, output, input_format)


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
    log_level: Annotated[str, typer.Option()] = "info",
) -> None:
    """Run the versioned local HTTP API."""
    try:
        api = create_app()
    except LunaUXError as exc:
        error_console.print(f"[red]{exc.code}:[/red] {exc.message}")
        raise typer.Exit(code=1) from exc
    uvicorn.run(api, host=host, port=port, log_level=log_level, access_log=False)


@app.command()
def doctor() -> None:
    """Check Python, configuration, and backend availability."""
    settings = Settings.from_env()
    table = Table(title="LunaUX Next diagnostics")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("LunaUX Next", __version__)
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Backend module", settings.backend_module)
    table.add_row("Bytecode limit", f"{settings.max_bytecode_bytes} bytes")
    try:
        backend = NativeModuleBackend(settings.backend_module)
        table.add_row("Backend status", "available")
        table.add_row("Backend version", backend.version)
        console.print(table)
    except LunaUXError as exc:
        table.add_row("Backend status", "unavailable")
        console.print(table)
        error_console.print(f"[yellow]{exc.message}[/yellow]")
        raise typer.Exit(code=1) from exc


@app.command(name="version")
def version_command() -> None:
    """Print the LunaUX Next version."""
    typer.echo(__version__)
