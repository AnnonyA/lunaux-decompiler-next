from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeBackend:
    name: str = "fake"
    version: str = "test"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        return f"decompiled:{filename}:{len(bytecode)}:{options['UseIfExpression']}"

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        return f"disassembled:{filename}:{len(bytecode)}"
