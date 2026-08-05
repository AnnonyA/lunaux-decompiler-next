from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

from lunaux.backends.bytecode import (
    BytecodeFormatError,
    LuauBytecodeModule,
    LuauProto,
    parse_bytecode,
)
from lunaux.backends.lifter import decompile_module, disassemble_module
from lunaux.backends.opcodes import disassemble_words, unpack_words

_PRINTABLE: Final[re.Pattern[bytes]] = re.compile(rb"[\x20-\x7e]{4,}")


@dataclass(frozen=True, slots=True)
class BytecodeSummary:
    size: int
    version: int | None
    types_version: int | None
    raw_instruction_stream: bool
    serialized_container: bool
    prototype_count: int
    strings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "size": self.size,
            "version": self.version,
            "types_version": self.types_version,
            "raw_instruction_stream": self.raw_instruction_stream,
            "serialized_container": self.serialized_container,
            "prototype_count": self.prototype_count,
            "strings": list(self.strings),
        }


def _try_parse(bytecode: bytes) -> LuauBytecodeModule | None:
    if not bytecode or bytecode[0] not in range(3, 13):
        return None
    try:
        return parse_bytecode(bytecode)
    except BytecodeFormatError:
        return None


def inspect_bytecode(bytecode: bytes, *, string_limit: int = 32) -> BytecodeSummary:
    module = _try_parse(bytecode)
    strings: list[str] = []
    if module is not None:
        strings.extend(module.strings[:string_limit])
    else:
        for match in _PRINTABLE.finditer(bytecode):
            value = match.group().decode("utf-8", errors="replace")
            if value not in strings:
                strings.append(value)
            if len(strings) >= string_limit:
                break
    return BytecodeSummary(
        size=len(bytecode),
        version=module.version if module else (bytecode[0] if bytecode else None),
        types_version=(
            module.types_version
            if module
            else (bytecode[1] if len(bytecode) > 1 else None)
        ),
        raw_instruction_stream=(
            module is None and bool(bytecode) and len(bytecode) % 4 == 0
        ),
        serialized_container=module is not None,
        prototype_count=len(module.protos) if module else 0,
        strings=tuple(strings),
    )


def _raw_proto(bytecode: bytes) -> LuauBytecodeModule:
    words = unpack_words(bytecode)
    proto = LuauProto(
        proto_id=0,
        max_stack_size=255,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=words,
        constants=(),
        child_proto_ids=(),
        line_defined=0,
        debug_name="raw_chunk",
        line_info=(),
        locals=(),
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
    )
    return LuauBytecodeModule(
        version=0,
        types_version=0,
        strings=(),
        protos=(proto,),
        main_proto_id=0,
        bytes_consumed=len(bytecode),
        trailing_bytes=0,
    )


class ReconstructedBackend:
    """Portable Luau parser, disassembler, and heuristic source reconstructor."""

    @property
    def name(self) -> str:
        return "python-reconstruction"

    @property
    def version(self) -> str:
        return "0.5.0"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        module = _try_parse(bytecode)
        if module is not None:
            return decompile_module(module, options, filename)
        if len(bytecode) % 4 == 0:
            source = decompile_module(_raw_proto(bytecode), options, filename)
            listing = "\n".join(
                f"-- {line}" for line in disassemble_words(bytecode).splitlines()
            )
            return source + "\n-- Raw instruction stream\n" + listing + "\n"
        summary = inspect_bytecode(bytecode)
        label = filename or "<bytecode>"
        return "\n".join(
            [
                f"-- LunaUX Next could not parse {label} as serialized Luau bytecode.",
                "-- The input is also not a complete 32-bit instruction stream.",
                f"-- metadata: {json.dumps(summary.as_dict(), ensure_ascii=False)}",
                "",
            ]
        )

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        module = _try_parse(bytecode)
        if module is not None:
            return disassemble_module(module, filename)
        if len(bytecode) % 4 == 0:
            return disassemble_words(bytecode)
        summary = inspect_bytecode(bytecode)
        payload = {
            "backend": self.name,
            "filename": filename,
            "note": (
                "Input is neither a supported serialized Luau container "
                "nor a raw word stream."
            ),
            **summary.as_dict(),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
