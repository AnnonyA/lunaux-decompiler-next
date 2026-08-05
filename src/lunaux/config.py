from __future__ import annotations

import os
from dataclasses import dataclass


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
    max_bytecode_bytes: int = 16 * 1024 * 1024
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            origin.strip()
            for origin in os.getenv("LUNAUX_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        return cls(
            backend_module=os.getenv("LUNAUX_BACKEND_MODULE", "luna").strip() or "luna",
            max_bytecode_bytes=_positive_int("LUNAUX_MAX_BYTECODE_BYTES", 16 * 1024 * 1024),
            cors_origins=origins,
        )
