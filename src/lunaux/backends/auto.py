from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from lunaux.backends.base import DecompilerBackend
from lunaux.backends.native import NativeModuleBackend
from lunaux.backends.reconstructed import ReconstructedBackend
from lunaux.backends.unluau import UnluauBackend
from lunaux.errors import ErrorCode, LunaUXError


class BackendMode(StrEnum):
    AUTO = "auto"
    NATIVE = "native"
    UNLUAU = "unluau"
    RECONSTRUCTED = "reconstructed"


class AutoBackend:
    """Run the strongest available backend and fall through safely per request."""

    def __init__(
        self,
        primary: DecompilerBackend,
        fallbacks: tuple[DecompilerBackend, ...] = (),
        fallback_reason: str | None = None,
    ) -> None:
        self._backends = (primary, *fallbacks)
        self.fallback_reason = fallback_reason

    @property
    def backends(self) -> tuple[DecompilerBackend, ...]:
        return self._backends

    @property
    def name(self) -> str:
        if len(self._backends) == 1:
            return self._backends[0].name
        return "auto[" + " -> ".join(backend.name for backend in self._backends) + "]"

    @property
    def version(self) -> str:
        if len(self._backends) == 1:
            return self._backends[0].version
        return ", ".join(
            f"{backend.name}={backend.version}" for backend in self._backends
        )

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        return self._invoke(
            "decompilation",
            lambda backend: backend.decompile(bytecode, options, filename),
        )

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        return self._invoke(
            "disassembly",
            lambda backend: backend.disassemble(bytecode, filename),
        )

    def _invoke(
        self,
        operation: str,
        call: Callable[[DecompilerBackend], str],
    ) -> str:
        failures: list[str] = []
        last_status = 422
        for backend in self._backends:
            try:
                return call(backend)
            except LunaUXError as exc:
                if exc.code not in (ErrorCode.BACKEND_FAILURE, ErrorCode.BACKEND_UNAVAILABLE):
                    raise
                failures.append(f"{backend.name}: {exc.message}")
                last_status = exc.status_code
        detail = " | ".join(failures)
        raise LunaUXError(
            ErrorCode.BACKEND_FAILURE,
            f"Every backend failed during {operation}: {detail}",
            status_code=last_status,
        )


def build_backend(
    module_name: str = "luna",
    mode: BackendMode | str = BackendMode.AUTO,
    module_path: str | None = None,
    unluau_path: str | None = None,
    external_timeout_seconds: int = 45,
) -> AutoBackend:
    resolved_mode = BackendMode(mode)
    if resolved_mode is BackendMode.RECONSTRUCTED:
        return AutoBackend(ReconstructedBackend())
    if resolved_mode is BackendMode.NATIVE:
        return AutoBackend(NativeModuleBackend(module_name, module_path))
    if resolved_mode is BackendMode.UNLUAU:
        return AutoBackend(UnluauBackend(unluau_path, external_timeout_seconds))

    available: list[DecompilerBackend] = []
    unavailable: list[str] = []
    try:
        available.append(NativeModuleBackend(module_name, module_path))
    except LunaUXError as exc:
        unavailable.append(f"native: {exc.message}")
    try:
        available.append(UnluauBackend(unluau_path, external_timeout_seconds))
    except LunaUXError as exc:
        unavailable.append(f"unluau: {exc.message}")
    available.append(ReconstructedBackend())

    return AutoBackend(
        available[0],
        tuple(available[1:]),
        fallback_reason=" | ".join(unavailable) or None,
    )
