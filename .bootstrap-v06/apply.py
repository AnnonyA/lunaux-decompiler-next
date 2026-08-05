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

    # GitHub Actions tokens cannot create or modify workflow files. The
    # connector adds the permanent workflow after this source commit lands.
    generated_workflow = ROOT / ".github" / "workflows" / "luau-spec-check.yml"
    generated_workflow.unlink(missing_ok=True)
    shutil.rmtree(BOOTSTRAP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
