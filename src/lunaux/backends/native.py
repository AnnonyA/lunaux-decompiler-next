from __future__ import annotations

from importlib import import_module, util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, cast

from lunaux.backends.base import DecompilerBackend
from lunaux.errors import ErrorCode, LunaUXError


class NativeModuleBackend(DecompilerBackend):
    """Compatibility adapter for the original ``luna`` native Python extension."""

    def __init__(self, module_name: str = "luna", module_path: str | None = None) -> None:
        self._module_name = module_name
        self._module_path = module_path
        self._module = self._load(module_name, module_path)
        self._validate_module(self._module)

    @staticmethod
    def _load(module_name: str, module_path: str | None) -> ModuleType:
        try:
            if module_path:
                return NativeModuleBackend._load_path(module_name, Path(module_path))
            return import_module(module_name)
        except Exception as exc:
            location = f" from '{module_path}'" if module_path else ""
            raise LunaUXError(
                ErrorCode.BACKEND_UNAVAILABLE,
                f"Could not import backend module '{module_name}'{location}: {exc}",
                status_code=503,
            ) from exc

    @staticmethod
    def _load_path(module_name: str, path: Path) -> ModuleType:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        spec = util.spec_from_file_location(module_name, resolved)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not create an extension loader for {resolved}")
        module = util.module_from_spec(spec)
        previous = sys.modules.get(module_name)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous
            raise
        return module

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

    @property
    def path(self) -> str | None:
        value = getattr(self._module, "__file__", None)
        return str(value) if value else self._module_path

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
