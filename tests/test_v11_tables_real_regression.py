from __future__ import annotations

import base64

import pytest

from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.benchmark_engine import default_options

# Exact O1/g0 bytecode produced by pinned Luau 0.724 (commit 8f33df91).  These are
# serialized compiler outputs, not hand-built opcode sketches, and therefore exercise
# table literal recovery, SSA naming, GETTABLEKS emission, and final alias cleanup.
_TABLES = (
    "CwMGBmNhc2UtMAROYW1lBVNjb3JlB0VuYWJsZWQFU3RhdHMFcHJpbnQAAQUAAAECACBBAAAANQACAAIA"
    "AAAFAwAAEAMAugEAAAA2AwYAEAMAIQcAAAAEAQAABAIAADcAAQMBAAAADwEAIQcAAAAPAgEiAgAAABED"
    "AAAhAgIDEAIBIgIAAAAMAQkAAACAQA8CALoBAAAADwMAIQcAAAAPAwMiAgAAABEEAAEVAQQBFgABAAoD"
    "AQMCAwMCAAAAAAAAAAADBAEBCAICAwAAAAQFAAAAAwUDBgQAAIBAAAEAAAAAAA=="
)
_ARITHMETIC = (
    "CwMDBG1hdGgFZmxvb3IFcHJpbnQAAgcBAAAIAAwpAgABJwECACoDAQJJDAMCDAIFAAAQMIAVAgICKwQC"
    "BiwGAQIrBQYHIQMEBRYDAgAIAgAAAAAAABxAAgAAAAAAAAhAAgAAAAAAAABAAwEDAgQAEDCAAgAAAAAA"
    "ADNAAgAAAAAAADdAAAIAAAAABAAAAQIACUEAAABAAAAADAECAAAAEEAGAgAABAMAABUCAgAVAQABFgAB"
    "AAMGAAMDBAAAEEABAAEAAAAAAQ=="
)
_MULTIPLE_ASSIGNMENT = (
    "CwMBBXByaW50AAEHAAABAgAQQQAAAAQAAAAEAQAABAIAACEDAQIiBAACIQIAAQYAAwAGAQQADAMBAAAA"
    "AEAGBAAABgUBAAYGAgAVAwQBFgABAAIDAQQAAABAAAEAAAAAAA=="
)


def _decompile(payload: str) -> str:
    return ReconstructedBackend().decompile(
        base64.b64decode(payload),
        dict(default_options()),
        "fixture.luac",
    )


def test_real_v11_tables_alias_chain_keeps_transitive_provenance() -> None:
    assert _decompile(_TABLES) == (
        'local data = {Name = "case-0", Stats = {Score = 0, Enabled = true}, 0, 0}\n'
        "data.Stats.Score += data[1]\n"
        "print(data.Name, data.Stats.Score, data[2])\n"
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            _ARITHMETIC,
            """local function proto_0(arg1): number
    local value2 = arg1 * 3 + 7
    local value3 = value2 / 2
    local value = math.floor(value3)
    return value % 19 + value2 ^ 2 % 23
end

local callback = proto_0
print(callback(0))
""",
        ),
        (
            _MULTIPLE_ASSIGNMENT,
            """local value = 0
local value2 = 0
local value3 = 0
local value4 = value2 + value3
local value5 = value - value3
local value6 = value + value2
local value7 = value4
local value8 = value5
print(value7, value8, value6)
""",
        ),
    ],
)
def test_broad_physical_register_replay_regressions_remain_absent(
    payload: str,
    expected: str,
) -> None:
    assert _decompile(payload) == expected
