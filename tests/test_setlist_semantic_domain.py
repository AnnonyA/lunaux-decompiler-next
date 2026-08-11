from __future__ import annotations

import base64

import pytest

from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.compat_quality_dispatch import decompile_module
from lunaux.backends.opcodes import DecodedInstruction, opcode_names, setlist_semantics
from lunaux.backends.reconstructed import ReconstructedBackend

# Serialized outputs from the pinned v3/v6 compiler profiles.  Unlike the small
# decoder-focused modules below, these exercise parsing, SSA, compatibility lifting,
# nested DUPTABLE ownership, mixed named fields, and fixed SETLIST recovery together.
_REAL_LEGACY_TABLES = {
    3: (
        "AwYGY2FzZS0wBE5hbWUFU2NvcmUHRW5hYmxlZAVTdGF0cwVwcmludAEFAAABJkEAAAA1AAIA"
        "AgAAAAUDAAAQAwC6AQAAADYDBAAEBAAAEAQDIgIAAAADBAEAEAQD8AMAAAAQAwAhBQAAAAQB"
        "AAAEAgAANwABAwEAAAAPAQAhBQAAAA8CASICAAAAEQMAACECAgMQAgEiAgAAAAwBBwAAAGBADwIA"
        "ugEAAAAPBAAhBQAAAA8DBCICAAAAEQQAARUBBAEWAAEACAMBAwIDAwMEBQICAwMFAwYEAABgQAAB"
        "AAAAAA=="
    ),
    6: (
        "BgMGBmNhc2UtMAROYW1lBVNjb3JlB0VuYWJsZWQFU3RhdHMFcHJpbnQAAQUAAAECACZBAAAA"
        "NQACAAIAAAAFAwAAEAMAugEAAAA2AwQABAQAABAEAyICAAAAAwQBABAEA/ADAAAAEAMAIQUAAAAE"
        "AQAABAIAADcAAQMBAAAADwEAIQUAAAAPAgEiAgAAABEDAAAhAgIDEAIBIgIAAAAMAQcAAABgQA8C"
        "ALoBAAAADwQAIQUAAAAPAwQiAgAAABEEAAEVAQQBFgABAAgDAQMCAwMDBAUCAgMDBQMGBAAAYEAA"
        "AQAAAAA="
    ),
}


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, *, a: int = 0, d: int = 0) -> int:
    return _opcode(name) | (a << 8) | ((d & 0xFFFF) << 16)


def _module(
    code: tuple[int, ...],
    constants: tuple[LuauConstant, ...] = (),
    *,
    version: int = 6,
) -> LuauBytecodeModule:
    proto = LuauProto(
        proto_id=0,
        max_stack_size=12,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=constants,
        child_proto_ids=(),
        line_defined=1,
        debug_name="main",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    return LuauBytecodeModule(
        version=version,
        types_version=3,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def _instruction(*, c: int, aux: int) -> DecodedInstruction:
    opcode = _opcode("SETLIST")
    return DecodedInstruction(
        pc=7,
        word=opcode,
        opcode=opcode,
        name="SETLIST",
        a=2,
        b=4,
        c=c,
        d=0,
        e=0,
        aux=aux,
    )


def test_setlist_keeps_semantic_index_and_legacy_offset_in_distinct_domains() -> None:
    fixed = setlist_semantics(_instruction(c=3, aux=1))
    assert fixed is not None
    assert fixed.semantic_first_array_index == 1
    assert fixed.legacy_emission_offset == 0
    assert fixed.fixed_value_count == 2
    assert tuple(fixed.semantic_indices()) == (1, 2)

    open_tail = setlist_semantics(_instruction(c=0, aux=5))
    assert open_tail is not None
    assert open_tail.is_open
    assert open_tail.semantic_first_array_index == 5
    assert open_tail.legacy_emission_offset == 4
    assert open_tail.source_register_count == 1


@pytest.mark.parametrize("version", [3, 6])
def test_real_legacy_mixed_table_recovers_fixed_setlist(version: int) -> None:
    output = ReconstructedBackend().decompile(
        base64.b64decode(_REAL_LEGACY_TABLES[version]),
        {},
        f"setlist-v{version}.luac",
    )

    assert output.startswith(
        'local value = {\n    Name = "case-0",\n'
        "    Stats = {Score = 0, Enabled = true},\n"
        "    0,\n    0,\n}\n"
    )
    assert "value[1] = 0" not in output
    assert "value[2] = 0" not in output


def test_two_contiguous_setlist_batches_extend_one_initializer() -> None:
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _ad("LOADN", a=1, d=10),
        _ad("LOADN", a=2, d=20),
        _abc("SETLIST", a=0, b=1, c=3),
        1,
        _ad("LOADN", a=1, d=30),
        _ad("LOADN", a=2, d=40),
        _abc("SETLIST", a=0, b=1, c=3),
        3,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code), {}, "contiguous-setlist.luau")

    assert "local value = {\n    10,\n    20,\n    30,\n    40,\n}" in output
    assert "value[" not in output


def test_real_toolchain_non_one_batch_shape_uses_semantic_start_index() -> None:
    # Pinned v6/v11 compilers split large literals into 16-value batches with
    # semantic AUX starts 1, 17, 33, ... .  Build the first two decoded batches
    # directly so this decoder test remains independent of an external executable.
    words = [_abc("NEWTABLE", a=0), 0]
    for start_index in (1, 17):
        words.extend(
            _ad("LOADN", a=register, d=start_index + register - 1)
            for register in range(1, 17)
        )
        words.extend((_abc("SETLIST", a=0, b=1, c=17), start_index))
    words.append(_abc("RETURN", a=0, b=2))

    output = decompile_module(_module(tuple(words)), {}, "non-one-setlist.luau")

    expected = "\n".join(f"    {value}," for value in range(1, 33))
    assert f"local value = {{\n{expected}\n}}" in output
    assert "value[17]" not in output


def test_noncontiguous_setlist_batch_uses_conservative_fallback() -> None:
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _ad("LOADN", a=1, d=10),
        _ad("LOADN", a=2, d=20),
        _abc("SETLIST", a=0, b=1, c=3),
        1,
        _ad("LOADN", a=1, d=40),
        _ad("LOADN", a=2, d=50),
        _abc("SETLIST", a=0, b=1, c=3),
        4,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code), {}, "noncontiguous-setlist.luau")

    assert "local value = {10, 20}" in output
    assert "value[4] = 40" in output
    assert "value[5] = 50" in output
    assert "value[3]" not in output


def test_call_escape_flushes_table_and_preserves_legacy_fallback_indices() -> None:
    constants = (LuauConstant("string", "observe", 3),)
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _abc("GETGLOBAL", a=3),
        0,
        _abc("MOVE", a=4, b=0),
        _abc("CALL", a=3, b=2, c=1),
        _ad("LOADN", a=1, d=10),
        _ad("LOADN", a=2, d=20),
        _abc("SETLIST", a=0, b=1, c=3),
        1,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code, constants), {}, "escaped-setlist.luau")

    assert "local value = {}" in output
    assert "value[1] = 10" in output
    assert "value[2] = 20" in output
    assert "value[0]" not in output


def test_reused_physical_register_does_not_merge_distinct_ssa_tables() -> None:
    code = (
        _abc("NEWTABLE", a=0),
        0,
        _ad("LOADN", a=1, d=10),
        _abc("SETLIST", a=0, b=1, c=2),
        1,
        _abc("NEWTABLE", a=0),
        0,
        _ad("LOADN", a=1, d=20),
        _abc("SETLIST", a=0, b=1, c=2),
        1,
        _abc("RETURN", a=0, b=2),
    )

    output = decompile_module(_module(code), {}, "register-reuse-setlist.luau")

    assert "local value = {10}" in output
    assert "value = {20}" in output
    assert "{10, 20}" not in output


def test_setlist_output_is_deterministic() -> None:
    payload = base64.b64decode(_REAL_LEGACY_TABLES[6])
    outputs = {
        ReconstructedBackend().decompile(payload, {}, "deterministic-setlist.luac")
        for _ in range(5)
    }

    assert len(outputs) == 1
