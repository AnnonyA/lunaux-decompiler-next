from __future__ import annotations

from pathlib import Path

root = Path(__file__).resolve().parents[1]
recovery = root / "src/lunaux/backends/roblox_recovery.py"
text = recovery.read_text(encoding="utf-8")
old = "    chunks = _IDENTIFIER_CHUNK.findall(path)\n"
new = "    chunks = [str(chunk) for chunk in _IDENTIFIER_CHUNK.findall(path)]\n"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("module path typing marker not found")
recovery.write_text(text, encoding="utf-8")

for relative in (
    ".github/workflows/apply-v014-roblox-recovery.yml",
    ".github/workflows/fix-v014-generator.yml",
    ".github/workflows/finalize-v014.yml",
    "scripts/apply_v014_roblox_recovery.py",
    "scripts/fix_v014_generator.py",
    "scripts/finalize_v014.py",
):
    target = root / relative
    if target.exists():
        target.unlink()

print("finalized LunaUX 0.14 generated implementation")
