from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from lunaux.backends.bytecode import function_parameter_types, parse_bytecode
from lunaux.backends.callframe import plan_call_frames
from lunaux.backends.module_analysis import build_module_analysis
from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.backends.table_recovery import plan_table_builds
from lunaux.benchmark_engine import default_options

_FIXTURE = Path(__file__).parent / "fixtures" / "source_fidelity" / "real_module_v9.bin"
_FIXTURE_SHA256 = "7d4bd8e422559a401adf6c7303dc73fb4543cf577d7ebe4e84bb8403256c8161"


def _decompile() -> str:
    return ReconstructedBackend().decompile(
        _FIXTURE.read_bytes(),
        dict(default_options()),
        _FIXTURE.name,
    )


def test_real_source_fidelity_fixture_is_exact_and_decodable() -> None:
    bytecode = _FIXTURE.read_bytes()

    assert len(bytecode) == 9722
    assert hashlib.sha256(bytecode).hexdigest() == _FIXTURE_SHA256

    module = parse_bytecode(bytecode)
    assert module.version == 9
    assert module.types_version == 3
    assert module.main_proto_id == 5
    assert len(module.protos) == 6
    assert function_parameter_types(module.protos[0]) == ()
    assert function_parameter_types(module.protos[1]) == ()
    assert function_parameter_types(module.protos[2]) == ("number",)
    assert function_parameter_types(module.protos[3]) == ("string?",)
    assert function_parameter_types(module.protos[4]) == ("string?",)
    assert function_parameter_types(module.protos[5]) == ()


def test_real_source_fidelity_output_is_deterministic() -> None:
    outputs = {_decompile() for _ in range(3)}

    assert len(outputs) == 1
    output = outputs.pop()
    assert hashlib.sha256(output.encode()).hexdigest() == (
        "e26ee5299517871ddfba45b7d510a9acbf4c269c61c11d7a518268a4789d827a"
    )


def test_real_fixture_call_shapes_have_exact_table_owners() -> None:
    module = parse_bytecode(_FIXTURE.read_bytes())
    analysis = build_module_analysis(module)
    call_shapes: Counter[str] = Counter()
    owned_shapes: Counter[str] = Counter()
    owned_calls = 0
    nested_owners = 0

    for proto in module.protos:
        facts = analysis.for_proto(proto)
        calls = plan_call_frames(facts.ssa)
        tables = plan_table_builds(facts.ssa, proto, calls)
        call_shapes.update(frame.result_shape.value for frame in calls.frames.values())
        owned_shapes.update(item.result_shape.value for item in tables.calls.values())
        owned_calls += len(tables.calls)
        nested_owners += len(tables.parent_by_table)
        for pc, ownership in tables.calls.items():
            assert calls.frames[pc].result_shape == ownership.result_shape

    assert call_shapes == {"fixed-many": 2, "fixed-one": 52, "open": 33}
    assert owned_shapes == {"fixed-one": 49, "open": 33}
    assert owned_calls == 82
    assert nested_owners == 95


def test_real_source_fidelity_output_uses_proven_structure() -> None:
    output = _decompile()

    assert output.startswith("local module = {\n")
    assert output.endswith("return module\n")
    assert "FlagColors = {\n" in output
    assert "SkinColors = {\n" in output
    assert "Tiers = {\n" in output
    assert "function module.GetLimitbreakerKind(arg1)" in output
    assert "function module.ComputeFinishCoins(arg1, arg2): number" in output
    assert "function module.GetTier(arg1: number)" in output
    assert "function module.GetFlag(arg1: string?)" in output
    assert "function module.GetSkinColor(arg1: string?)" in output
    assert "for _, value in ipairs(module.Limitbreaker.Kinds) do" in output
    assert "for _, value in ipairs(module.Tiers) do" in output
    assert (
        'return module.SkinColors[arg1 or "white"] or module.SkinColors.white'
        in output
    )
    assert "return math.floor(value13)" in output
    assert re.search(r"(?m)^\s*local\s+(?:data|color)\d*\b", output) is None
    assert re.search(r"(?m)^\s*module\.\w+\s*=\s*function\(", output) is None
    assert "multiple returns" not in output
    assert "--[[ open result ]]" not in output
