from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DecompilerBackend(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str: ...

    def disassemble(self, bytecode: bytes, filename: str | None) -> str: ...
