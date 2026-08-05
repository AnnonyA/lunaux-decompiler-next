from __future__ import annotations

import base64
import io
import shutil
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / ".bootstrap-v06"


def main() -> int:
    encoded = "".join(
        path.read_text(encoding="ascii")
        for path in sorted(BOOTSTRAP.glob("*.part"))
    )
    payload = base64.b64decode(encoded, validate=True)

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError(f"unsafe payload path: {item.filename}")
        archive.extractall(ROOT)

    shutil.rmtree(BOOTSTRAP)
    workflow = ROOT / ".github" / "workflows" / "apply-v06.yml"
    workflow.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
