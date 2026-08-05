from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lunaux.models import DecompileOptions


class BytecodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bytecode: str = Field(min_length=1, description="Base64-encoded Luau bytecode")
    filename: str | None = Field(default=None, max_length=255)


class DecompileRequest(BytecodeRequest):
    options: DecompileOptions = Field(default_factory=DecompileOptions)


class TextResult(BaseModel):
    result: str
    backend: str
    backend_version: str


class HealthResult(BaseModel):
    status: str
    backend: str
    backend_version: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResult(BaseModel):
    error: ErrorDetail
