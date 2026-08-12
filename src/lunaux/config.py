from __future__ import annotations

import os
from dataclasses import dataclass

from lunaux.backends.auto import BackendMode


def _environment_value(name: str, legacy_name: str, default: str) -> str:
    return os.getenv(name, os.getenv(legacy_name, default))


def _positive_int(name: str, legacy_name: str, default: int) -> int:
    raw = _environment_value(name, legacy_name, str(default))
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    backend_module: str = "luna"
    backend_mode: BackendMode = BackendMode.AUTO
    native_path: str | None = None
    unluau_path: str | None = None
    external_timeout_seconds: int = 45
    max_bytecode_bytes: int = 16 * 1024 * 1024
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> Settings:
        origins = tuple(
            origin.strip()
            for origin in _environment_value(
                "BYTEWEFT_CORS_ORIGINS", "LUNAUX_CORS_ORIGINS", ""
            ).split(",")
            if origin.strip()
        )
        raw_mode = _environment_value(
            "BYTEWEFT_BACKEND_MODE",
            "LUNAUX_BACKEND_MODE",
            BackendMode.AUTO,
        ).strip().lower()
        try:
            mode = BackendMode(raw_mode)
        except ValueError as exc:
            choices = ", ".join(item.value for item in BackendMode)
            raise ValueError(f"BYTEWEFT_BACKEND_MODE must be one of: {choices}") from exc
        native_path = _environment_value(
            "BYTEWEFT_NATIVE_PATH", "LUNAUX_NATIVE_PATH", ""
        ).strip() or None
        unluau_path = _environment_value(
            "BYTEWEFT_UNLUAU_PATH", "LUNAUX_UNLUAU_PATH", ""
        ).strip() or None
        return cls(
            backend_module=_environment_value(
                "BYTEWEFT_BACKEND_MODULE", "LUNAUX_BACKEND_MODULE", "luna"
            ).strip()
            or "luna",
            backend_mode=mode,
            native_path=native_path,
            unluau_path=unluau_path,
            external_timeout_seconds=_positive_int(
                "BYTEWEFT_EXTERNAL_TIMEOUT_SECONDS",
                "LUNAUX_EXTERNAL_TIMEOUT_SECONDS",
                45,
            ),
            max_bytecode_bytes=_positive_int(
                "BYTEWEFT_MAX_BYTECODE_BYTES",
                "LUNAUX_MAX_BYTECODE_BYTES",
                16 * 1024 * 1024,
            ),
            cors_origins=origins,
        )
