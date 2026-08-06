from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from lunaux.benchmarking import (
    BenchmarkStatus,
    ExternalCommandBackend,
    InProcessBackend,
    default_options,
    load_external_backends,
    load_manifest,
    run_benchmark,
)


@dataclass
class _Backend:
    name: str = "lunaux-test"
    version: str = "0.18.0.dev0"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        assert options["AdvancedLoops"]
        return f"-- {filename}\nreturn {len(bytecode)}\n"

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        del bytecode, filename
        return ""


def _manifest(tmp_path: Path) -> Path:
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "sample.luac").write_bytes(b"abc")
    (tmp_path / "fixtures" / "sample.luau").write_text("return 3\n", encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": [
                    {
                        "id": "sample-o2",
                        "bytecode": "fixtures/sample.luac",
                        "source": "fixtures/sample.luau",
                        "optimization": "O2",
                        "tags": ["smoke", "return"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_manifest_and_in_process_report(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    cases = load_manifest(manifest)
    report = run_benchmark(
        manifest,
        cases,
        [InProcessBackend(_Backend(), default_options())],
        tmp_path / "artifacts",
    )

    assert report.results[0].status is BenchmarkStatus.SUCCESS
    assert report.results[0].output_characters > 0
    assert report.results[0].output_sha256 is not None
    assert report.summaries[0].success_rate == 1.0
    assert (tmp_path / "artifacts" / "lunaux-test" / "sample-o2.luau").is_file()


def test_external_stdout_backend(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    backend = ExternalCommandBackend(
        backend_name="external-test",
        backend_version="1",
        command=(
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                "print('-- bytes', len(Path(sys.argv[1]).read_bytes()))"
            ),
            "{input}",
        ),
    )
    report = run_benchmark(
        manifest,
        load_manifest(manifest),
        [backend],
        tmp_path / "artifacts",
        timeout_seconds=5,
    )

    assert report.results[0].status is BenchmarkStatus.SUCCESS
    assert report.results[0].return_code == 0
    assert "bytes 3" in (
        tmp_path / "artifacts" / "external-test" / "sample-o2.luau"
    ).read_text(encoding="utf-8")


def test_external_config_and_path_escape_are_validated(tmp_path: Path) -> None:
    config = tmp_path / "backends.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backends": [
                    {
                        "name": "medal",
                        "version": "pinned",
                        "command": ["medal", "{input}", "--output", "{output}"],
                        "output": "file",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_external_backends(config)[0].name == "medal"

    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["cases"][0]["bytecode"] = "../outside.luac"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        load_manifest(manifest)
