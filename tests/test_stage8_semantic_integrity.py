from __future__ import annotations

import base64
import hashlib
import re
from functools import lru_cache
from pathlib import Path

from lunaux.backends.bytecode import parse_bytecode
from lunaux.backends.contextual_functions import collect_module_function_contexts
from lunaux.backends.module_analysis import build_module_analysis
from lunaux.backends.proto_emission import build_proto_emission_plan
from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.models import DecompileOptions

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "semantic_integrity"
    / "mega_stress_v13.bin.b64"
)
_BYTECODE_SHA256 = "2446c05b227e607150b2dc030c56f23db253cb4e1aa79c1211041b29508fe1b7"
_OUTPUT_SHA256 = "9e6cbd1844fb002b7638832bdf4e8256ff525a799c20cf978cc569debf2ff736"
_REAL_MIXED_CALL_SETLIST = (
    "CwMHBG1hdGgDbWF4A29uZQZjYXNlLTUEbmFtZQVmbG9vcgVwcmludAACBAEAAAgA"
    "CEsSAAUAAAAABgIAAAUDAAAMAQMAAAgQgBUBAwAWAQAABAIAAAAAAADwPwMBAwIE"
    "AAgQgAABAwEYAAAAAAAAAAABAAAAAAAHAAABAgsAAAIPAAEcDwECGx1BAAAAQAAA"
    "ADUBAQADAAAABQUBABAFAVoCAAAABgIAAAQD7v8VAgICBAQEAEkMBAIMAwUAABAw"
    "gBUDAgIGBAAABAUFABUEAgA3AQIAAQAAAAwCBwAAAGBADwMBWgIAAAARBAEAEQUB"
    "AREGAQIVAgUBFgABAAgGAAMEAwUDAQMGBAAQMIADBwQAAGBAAQABAAEYAAABAAAA"
    "AAAAAAAAAAAAAAAAAAABAAAAAAAAAAEBAAAAAAAB"
)


@lru_cache(maxsize=1)
def _bytecode() -> bytes:
    return base64.b64decode(_FIXTURE.read_text(encoding="ascii"))


def _decompile() -> str:
    return ReconstructedBackend().decompile(
        _bytecode(),
        DecompileOptions().to_backend_dict(),
        "mega_stress_v13.bin",
    )


def test_real_v13_fixture_identity_and_metadata() -> None:
    bytecode = _bytecode()

    assert len(bytecode) == 22980
    assert hashlib.sha256(bytecode).hexdigest() == _BYTECODE_SHA256
    assert bytecode[:2] == bytes((13, 3))

    module = parse_bytecode(bytecode)
    assert module.version == 13
    assert module.types_version == 3
    assert len(module.protos) == 89
    assert module.main_proto_id == 88


def test_real_v13_direct_callback_protos_have_expression_owners() -> None:
    module = parse_bytecode(_bytecode())
    analysis = build_module_analysis(module)
    contexts = collect_module_function_contexts(
        module,
        recover_metatable_classes=True,
        enabled=True,
        module_analysis=analysis,
    )
    plan = build_proto_emission_plan(
        module,
        analysis,
        contexts,
        inline_callbacks=True,
    )

    for parent_id, child_id in ((46, 45), (79, 78), (81, 80), (86, 85)):
        instance = next(
            item
            for item in plan.for_parent(parent_id).instances
            if item.child_proto_id == child_id
        )
        assert instance.emission_kind == "inline-expression"
        assert child_id in plan.owned_proto_ids
        assert child_id not in plan.preemit_proto_ids


def test_real_v13_output_is_deterministic_and_exact() -> None:
    outputs = {_decompile() for _ in range(3)}

    assert len(outputs) == 1
    assert hashlib.sha256(outputs.pop().encode()).hexdigest() == _OUTPUT_SHA256


def test_real_v13_output_has_no_known_synthetic_ownership_artifacts() -> None:
    output = _decompile()

    assert re.search(r"(?m)^local function proto_\d+\b", output) is None
    assert re.search(r"\bgame\d+\b", output) is None
    assert re.search(r"\bnilValue\d*\b", output) is None
    assert "multiple returns" not in output
    assert "--[[ open result ]]" not in output
    assert "\nclass " not in output

    assert "for index3, value3 in item19 do" in output
    assert "for index4, value4 in item23, item24 do" in output
    assert "local recursiveFunction, recursiveFunction2" in output
    assert "xpcall(arg1, function(arg1)" in output


def test_real_v13_output_preserves_proven_semantic_structures() -> None:
    output = _decompile()

    assert (
        "values = {math.max(arg1, 1), math.floor(value13), "
        "math.clamp(arg1, 0, 100)}"
    ) in output
    assert 'local data = {"alpha", text5, tostring(arg2)}' in output
    assert 'table.concat(data, "|")' in output
    assert (
        'data15.sideEffectValue = 0 < arg1 and sideEffect("positive") '
        'or sideEffect("fallback")'
    ) in output
    assert "for index = 1, arg1 do" in output
    assert "for index2 = 1, 5 do" in output
    assert "local result = nil\nif OptionalModule then" in output
    assert output.index("local capturedValue3") > output.index(
        "local result = nil\nif OptionalModule then"
    )


def test_real_mixed_fixed_fastcall_and_open_setlist_is_transactional() -> None:
    bytecode = base64.b64decode(_REAL_MIXED_CALL_SETLIST)
    assert hashlib.sha256(bytecode).hexdigest() == (
        "02586f8a4f1ef07fb032abe152cdb1003219fb8dec31ffa9ce6b92cd4a19c1c1"
    )

    output = ReconstructedBackend().decompile(
        bytecode,
        DecompileOptions().to_backend_dict(),
        "mixed-call-setlist.bin",
    )

    assert 'name = "case-5"' in output
    assert "one(-18)" in output
    assert "math.floor(4)" in output
    assert "one(5)" in output
    assert "multiple returns" not in output
