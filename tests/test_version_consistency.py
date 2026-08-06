from __future__ import annotations

import tomllib
from pathlib import Path

from lunaux import __version__
from lunaux.backends.reconstructed import ReconstructedBackend


def test_version_metadata_is_consistent() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    project = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["version"] == __version__
    assert ReconstructedBackend().version == __version__
