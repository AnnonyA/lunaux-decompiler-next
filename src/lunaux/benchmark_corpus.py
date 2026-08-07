from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lunaux.benchmark_corpus_templates import TEMPLATES


@dataclass(frozen=True, slots=True)
class CorpusBuild:
    manifest: Path
    sources: int
    bytecodes: int
    optimizations: tuple[int, ...]
    debug_levels: tuple[int, ...]


def _expand_command(
    template: Sequence[str],
    *,
    source: Path,
    optimization: int,
    debug: int,
) -> list[str]:
    values = {
        "{source}": str(source),
        "{optimization}": str(optimization),
        "{debug}": str(debug),
    }
    command: list[str] = []
    for part in template:
        expanded = part
        for placeholder, value in values.items():
            expanded = expanded.replace(placeholder, value)
        command.append(expanded)
    return command


def _compile(
    command_template: Sequence[str],
    source: Path,
    optimization: int,
    debug: int,
    timeout_seconds: float,
) -> bytes:
    command = _expand_command(
        command_template,
        source=source,
        optimization=optimization,
        debug=debug,
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Luau compiler timed out for {source.name} at O{optimization}/g{debug}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"could not execute Luau compiler: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Luau compiler failed for {source.name} at O{optimization}/g{debug}: "
            f"{detail or f'exit code {completed.returncode}'}"
        )
    if not completed.stdout:
        raise RuntimeError(
            f"Luau compiler produced empty bytecode for {source.name} "
            f"at O{optimization}/g{debug}"
        )
    return completed.stdout


def generate_corpus(
    output_directory: Path,
    compiler_command: Sequence[str],
    *,
    seeds: int = 24,
    optimizations: Sequence[int] = (0, 1, 2),
    debug_levels: Sequence[int] = (0, 2),
    timeout_seconds: float = 20.0,
) -> CorpusBuild:
    if seeds <= 0:
        raise ValueError("seeds must be greater than zero")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    if not compiler_command or not any("{source}" in part for part in compiler_command):
        raise ValueError("compiler_command must contain a {source} placeholder")

    optimization_values = tuple(optimizations)
    debug_values = tuple(debug_levels)
    if not optimization_values or any(value not in {0, 1, 2} for value in optimization_values):
        raise ValueError("optimizations must contain only 0, 1, and 2")
    if not debug_values or any(value not in {0, 1, 2} for value in debug_values):
        raise ValueError("debug_levels must contain only 0, 1, and 2")
    if len(set(optimization_values)) != len(optimization_values):
        raise ValueError("optimizations must be unique")
    if len(set(debug_values)) != len(debug_values):
        raise ValueError("debug_levels must be unique")

    root = output_directory.resolve()
    source_root = root / "sources"
    bytecode_root = root / "bytecode"
    source_root.mkdir(parents=True, exist_ok=True)
    bytecode_root.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, object]] = []
    source_count = 0
    for template_name, renderer in TEMPLATES:
        template_directory = source_root / template_name
        template_directory.mkdir(parents=True, exist_ok=True)
        for seed in range(seeds):
            source = template_directory / f"seed-{seed:03d}.luau"
            source.write_text(renderer(seed), encoding="utf-8", newline="\n")
            source_count += 1
            for optimization in optimization_values:
                for debug in debug_values:
                    relative_bytecode = Path("bytecode") / f"O{optimization}" / f"g{debug}" / template_name / f"seed-{seed:03d}.luac"
                    bytecode = root / relative_bytecode
                    bytecode.parent.mkdir(parents=True, exist_ok=True)
                    bytecode.write_bytes(
                        _compile(
                            compiler_command,
                            source,
                            optimization,
                            debug,
                            timeout_seconds,
                        )
                    )
                    cases.append(
                        {
                            "id": (
                                f"{template_name}-seed-{seed:03d}-"
                                f"O{optimization}-g{debug}"
                            ),
                            "bytecode": relative_bytecode.as_posix(),
                            "source": source.relative_to(root).as_posix(),
                            "optimization": f"O{optimization}",
                            "tags": [
                                template_name,
                                f"O{optimization}",
                                f"g{debug}",
                                "debug" if debug else "stripped-debug",
                                "semantic-oracle",
                            ],
                        }
                    )

    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generator": {
                    "templates": len(TEMPLATES),
                    "seeds": seeds,
                    "optimizations": list(optimization_values),
                    "debug_levels": list(debug_values),
                },
                "cases": cases,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return CorpusBuild(
        manifest,
        source_count,
        len(cases),
        optimization_values,
        debug_values,
    )
