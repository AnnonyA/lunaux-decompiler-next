from __future__ import annotations

import os
from dataclasses import dataclass

from lunaux.backends.auto import BackendMode


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
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
            for origin in os.getenv("LUNAUX_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        raw_mode = os.getenv("LUNAUX_BACKEND_MODE", BackendMode.AUTO).strip().lower()
        try:
            mode = BackendMode(raw_mode)
        except ValueError as exc:
            choices = ", ".join(item.value for item in BackendMode)
            raise ValueError(f"LUNAUX_BACKEND_MODE must be one of: {choices}") from exc
        native_path = os.getenv("LUNAUX_NATIVE_PATH", "").strip() or None
        unluau_path = os.getenv("LUNAUX_UNLUAU_PATH", "").strip() or None
        return cls(
            backend_module=os.getenv("LUNAUX_BACKEND_MODULE", "luna").strip() or "luna",
            backend_mode=mode,
            native_path=native_path,
            unluau_path=unluau_path,
            external_timeout_seconds=_positive_int("LUNAUX_EXTERNAL_TIMEOUT_SECONDS", 45),
            max_bytecode_bytes=_positive_int("LUNAUX_MAX_BYTECODE_BYTES", 16 * 1024 * 1024),
            cors_origins=origins,
        )
