from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

from lunaux.backends.bytecode import (
    BytecodeFormatError,
    LuauBytecodeModule,
    LuauProto,
    is_supported_bytecode_version,
    parse_bytecode,
)
from lunaux.backends.lifter import decompile_module, disassemble_module
from lunaux.backends.opcodes import disassemble_words, unpack_words

_PRINTABLE: Final[re.Pattern[bytes]] = re.compile(rb"[\x20-\x7e]{4,}")
_COMPATIBILITY_NOTICE: Final[str] = (
    "-- Higher-fidelity reconstruction requires a compatible native or external "
    "backend in some cases.\n"
)


@dataclass(frozen=True, slots=True)
class BytecodeSummary:
    size: int
    version: int | None
    types_version: int | None
    raw_instruction_stream: bool
    serialized_container: bool
    prototype_count: int
    strings: tuple[str, ...]
    opcode_encoding: str | None = None
    parse_error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "size": self.size,
            "version": self.version,
            "types_version": self.types_version,
            "raw_instruction_stream": self.raw_instruction_stream,
            "serialized_container": self.serialized_container,
            "prototype_count": self.prototype_count,
            "strings": list(self.strings),
            "opcode_encoding": self.opcode_encoding,
            "parse_error": self.parse_error,
        }


def _looks_like_container(bytecode: bytes) -> bool:
    if not bytecode or not is_supported_bytecode_version(bytecode[0]):
        return False
    if bytecode[0] >= 4:
        return len(bytecode) >= 2 and bytecode[1] in (1, 2, 3)
    return True


def _try_parse(
    bytecode: bytes,
) -> tuple[LuauBytecodeModule | None, BytecodeFormatError | None]:
    if not _looks_like_container(bytecode):
        return None, None
    try:
        return parse_bytecode(bytecode), None
    except BytecodeFormatError as exc:
        return None, exc


def inspect_bytecode(bytecode: bytes, *, string_limit: int = 32) -> BytecodeSummary:
    module, parse_error = _try_parse(bytecode)
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
            module.types_version if module else (bytecode[1] if len(bytecode) > 1 else None)
        ),
        raw_instruction_stream=(module is None and bool(bytecode) and len(bytecode) % 4 == 0),
        serialized_container=module is not None,
        prototype_count=len(module.protos) if module else 0,
        strings=tuple(strings),
        opcode_encoding=module.opcode_encoding if module else None,
        parse_error=str(parse_error) if parse_error else None,
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
    """Portable CFG/SSA reconstruction with contextual functions and class recovery."""

    @property
    def name(self) -> str:
        return "python-reconstruction"

    @property
    def version(self) -> str:
        return "0.16.0"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        module, parse_error = _try_parse(bytecode)
        if module is not None:
            return _COMPATIBILITY_NOTICE + decompile_module(module, options, filename)
        if parse_error is None and len(bytecode) % 4 == 0:
            source = decompile_module(_raw_proto(bytecode), options, filename)
            listing = "\n".join(f"-- {line}" for line in disassemble_words(bytecode).splitlines())
            return _COMPATIBILITY_NOTICE + source + "\n-- Raw instruction stream\n" + listing + "\n"
        summary = inspect_bytecode(bytecode)
        label = filename or "<bytecode>"
        lines = [
            _COMPATIBILITY_NOTICE.rstrip(),
            f"-- LunaUX Next could not parse {label} as serialized Luau bytecode.",
        ]
        if parse_error is not None:
            lines.append(f"-- Parse error: {parse_error}")
        else:
            lines.append("-- The input is also not a complete 32-bit instruction stream.")
        lines.extend(
            [
                f"-- metadata: {json.dumps(summary.as_dict(), ensure_ascii=False)}",
                "",
            ]
        )
        return "\n".join(lines)

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        module, parse_error = _try_parse(bytecode)
        if module is not None:
            return disassemble_module(module, filename)
        if parse_error is None and len(bytecode) % 4 == 0:
            return disassemble_words(bytecode)
        summary = inspect_bytecode(bytecode)
        payload = {
            "backend": self.name,
            "filename": filename,
            "note": (
                "Input is neither a supported serialized Luau container nor a raw word stream."
            ),
            **summary.as_dict(),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
