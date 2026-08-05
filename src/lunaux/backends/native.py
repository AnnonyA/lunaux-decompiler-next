from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any, cast

from lunaux.backends.base import DecompilerBackend
from lunaux.errors import ErrorCode, LunaUXError


class NativeModuleBackend(DecompilerBackend):
    """Compatibility adapter for the original `luna` native Python module."""

    def __init__(self, module_name: str = "luna") -> None:
        self._module_name = module_name
        self._module = self._load(module_name)
        self._validate_module(self._module)

    @staticmethod
    def _load(module_name: str) -> ModuleType:
        try:
            return import_module(module_name)
        except Exception as exc:
            raise LunaUXError(
                ErrorCode.BACKEND_UNAVAILABLE,
                f"Could not import backend module '{module_name}': {exc}",
                status_code=503,
            ) from exc

    @staticmethod
    def _validate_module(module: ModuleType) -> None:
        missing = [
            name
            for name in ("decompile_bytecode", "disassemble_bytecode")
            if not callable(getattr(module, name, None))
        ]
        if missing:
            raise LunaUXError(
                ErrorCode.BACKEND_UNAVAILABLE,
                "Backend module is missing required callables: " + ", ".join(missing),
                status_code=503,
            )

    @property
    def name(self) -> str:
        return self._module_name

    @property
    def version(self) -> str:
        raw = getattr(self._module, "__version__", None)
        if raw is not None:
            return str(raw)
        getter = getattr(self._module, "get_version", None)
        if callable(getter):
            try:
                return str(getter())
            except Exception:
                return "unknown"
        return "unknown"

    def decompile(
        self,
        bytecode: bytes,
        options: dict[str, bool],
        filename: str | None,
    ) -> str:
        function = cast(Any, self._module.decompile_bytecode)
        return self._call(function, bytecode, options, filename)

    def disassemble(self, bytecode: bytes, filename: str | None) -> str:
        function = cast(Any, self._module.disassemble_bytecode)
        return self._call(function, bytecode, filename)

    @staticmethod
    def _call(function: Any, *args: object) -> str:
        try:
            result = function(*args)
        except Exception as exc:
            raise LunaUXError(
                ErrorCode.BACKEND_FAILURE,
                f"The decompiler backend failed: {exc}",
                status_code=422,
            ) from exc
        if not isinstance(result, str):
            raise LunaUXError(
                ErrorCode.BACKEND_FAILURE,
                f"The backend returned {type(result).__name__}; expected str.",
                status_code=502,
            )
        return result
