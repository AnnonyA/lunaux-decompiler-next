from __future__ import annotations

from pathlib import Path

path = Path(__file__).resolve().with_name("apply_v014_roblox_recovery.py")
text = path.read_text(encoding="utf-8")
old = '''replace_once(
    readme,
    """| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
| `MaxOutputCharacters` | `4000000` | Maximum generated output length. Accepted range: 1,000 to 20,000,000 characters. |
""",
    """| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
| `RecoverRobloxEvents` | `true` | Report recognized Roblox signal connections and event waits. |
| `InlineRobloxCallbacks` | `true` | Inline single-owner closures into supported callback, module-field, and returned-function positions. |
| `RecoverRobloxModules` | `true` | Recover `require` dependency paths and ModuleScript export shape. |
| `MaxOutputCharacters` | `4000000` | Maximum generated output length. Accepted range: 1,000 to 20,000,000 characters. |
""",
)
'''
new = '''replace_once(
    readme,
    """| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
""",
    """| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
| `RecoverRobloxEvents` | `true` | Report recognized Roblox signal connections and event waits. |
| `InlineRobloxCallbacks` | `true` | Inline single-owner closures into supported callback, module-field, and returned-function positions. |
| `RecoverRobloxModules` | `true` | Recover `require` dependency paths and ModuleScript export shape. |
""",
)
'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("README option marker block not found")
path.write_text(text, encoding="utf-8")
print("fixed v0.14 README option marker")
