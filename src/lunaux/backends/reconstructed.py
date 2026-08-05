from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Final

from lunaux.backends.opcodes import disassemble_words
from lunaux.errors import ErrorCode, LunaUXError

_PRINTABLE: Final[re.Pattern[bytes]] = re.compile(rb"[\x20-\x7e]{4,}")


@dataclass(frozen=True, slots=True)
class BytecodeSummary:
    size: int
    version: int | None
    types_version: int | None
    raw_instruction_stream: bool
    strings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "size": self.size,
            "version": self.version,
            "types_version": self.types_version,
            "raw_instruction_stream": self.raw_instruction_stream,
            "strings": list(self.strings),
        }


def inspect_bytecode(bytecode: bytes, *, string_limit: int = 32) -> BytecodeSummary:
    strings: list[str] = []
    for match in _PRINTABLE.finditer(bytecode):
        value = match.group().decode("utf-8", errors="replace")
        if value not in strings:
            strings.append(value)
        if len(strings) >= string_limit:
            break
    return BytecodeSummary(
        size=len(bytecode),
        version=bytecode[0] if bytecode else None,
        types_version=bytecode[1] if len(bytecode) > 1 else None,
        raw_instruction_stream=bool(bytecode) and len(bytecode) % 4 == 0,
        strings=tuple(strings),
    )


class ReconstructedBackend:
    """Readable fallback for runtimes where the exact native backend cannot load.

    This backend deliberately distinguishes raw Luau instruction words from a complete
    serialized bytecode container. It never presents heuristic output as recovered source.
    """

    @property
    def name(self) -> str:
        return "python-reconstruction"

    @property
    def version(self) -> str:
        return "0.2.0"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        summary = inspect_bytecode(bytecode)
        label = filename or "<bytecode>"
        lines = [
            f"-- LunaUX Next reconstructed output for {label}",
            "-- Exact Luau source reconstruction requires a compatible native LunaUX backend.",
            "-- This fallback preserves instruction data instead of inventing source code.",
            f"-- metadata: {json.dumps(summary.as_dict(), ensure_ascii=False)}",
        ]
        if summary.raw_instruction_stream:
            lines.append("-- instructions:")
            lines.extend(f"-- {line}" for line in disassemble_words(bytecode).splitlines())
        else:
            lines.extend(
                [
                    "-- The input appears to be a serialized Luau container, "
                    "not a raw word stream.",
                    "-- Use a matching native backend for full container parsing "
                    "and decompilation.",
                ]
            )
        return "\n".join(lines) + "\n"

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        summary = inspect_bytecode(bytecode)
        if summary.raw_instruction_stream:
            return disassemble_words(bytecode)
        payload = {
            "backend": self.name,
            "filename": filename,
            "note": (
                "Serialized Luau container detected. Exact function/instruction parsing requires "
                "the native backend; metadata and printable strings are shown instead."
            ),
            **summary.as_dict(),
        }
        try:
            return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        except (TypeError, ValueError) as exc:
            raise LunaUXError(
                ErrorCode.BACKEND_FAILURE,
                f"Could not render reconstructed output: {exc}",
                status_code=502,
            ) from exc
