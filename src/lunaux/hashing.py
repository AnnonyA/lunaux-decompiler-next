from __future__ import annotations

from hashlib import sha256
from pathlib import Path

_EXCLUDED_PARTS = {"__pycache__"}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def installation_hash(package_root: Path | None = None) -> str:
    """Return a deterministic SHA-256 for the installed LunaUX package files."""
    root = package_root or Path(__file__).resolve().parent
    digest = sha256()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in _EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix in _EXCLUDED_SUFFIXES:
            continue

        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    return digest.hexdigest()
