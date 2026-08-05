from __future__ import annotations

from enum import StrEnum

from lunaux.backends.base import DecompilerBackend
from lunaux.backends.native import NativeModuleBackend
from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.errors import LunaUXError


class BackendMode(StrEnum):
    AUTO = "auto"
    NATIVE = "native"
    RECONSTRUCTED = "reconstructed"


class AutoBackend:
    """Select native behavior when available and degrade safely to Python."""

    def __init__(self, primary: DecompilerBackend, fallback_reason: str | None = None) -> None:
        self._primary = primary
        self.fallback_reason = fallback_reason

    @property
    def name(self) -> str:
        return self._primary.name

    @property
    def version(self) -> str:
        return self._primary.version

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        return self._primary.decompile(bytecode, options, filename)

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        return self._primary.disassemble(bytecode, filename)


def build_backend(
    module_name: str = "luna",
    mode: BackendMode | str = BackendMode.AUTO,
    module_path: str | None = None,
) -> AutoBackend:
    resolved_mode = BackendMode(mode)
    if resolved_mode is BackendMode.RECONSTRUCTED:
        return AutoBackend(ReconstructedBackend())
    try:
        return AutoBackend(NativeModuleBackend(module_name, module_path))
    except LunaUXError as exc:
        if resolved_mode is BackendMode.NATIVE:
            raise
        return AutoBackend(ReconstructedBackend(), fallback_reason=exc.message)
