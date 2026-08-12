from __future__ import annotations

from pathlib import PurePath

from lunaux.backends.base import DecompilerBackend
from lunaux.branding import decompilation_header
from lunaux.errors import ErrorCode, LunaUXError
from lunaux.models import DecompileOptions


class DecompilerService:
    def __init__(self, backend: DecompilerBackend, max_bytecode_bytes: int) -> None:
        if max_bytecode_bytes <= 0:
            raise ValueError("max_bytecode_bytes must be greater than zero")
        self.backend = backend
        self.max_bytecode_bytes = max_bytecode_bytes

    def _validate(self, bytecode: bytes, filename: str | None) -> str | None:
        if not bytecode:
            raise LunaUXError(ErrorCode.EMPTY_BYTECODE, "The bytecode is empty.")
        if len(bytecode) > self.max_bytecode_bytes:
            raise LunaUXError(
                ErrorCode.INPUT_TOO_LARGE,
                f"Bytecode exceeds the {self.max_bytecode_bytes} byte limit.",
                status_code=413,
            )
        if filename is None:
            return None
        safe_name = PurePath(filename.replace("\\", "/")).name.strip()
        if not safe_name or len(safe_name) > 255 or "\x00" in safe_name:
            raise LunaUXError(ErrorCode.INVALID_FILENAME, "The filename is invalid.")
        return safe_name

    def decompile(
        self,
        bytecode: bytes,
        options: DecompileOptions | None = None,
        filename: str | None = None,
    ) -> str:
        safe_name = self._validate(bytecode, filename)
        resolved = options or DecompileOptions()
        result = self.backend.decompile(bytecode, resolved.to_backend_dict(), safe_name)
        if resolved.include_header:
            result = decompilation_header(bytecode) + result
        if len(result) > resolved.max_output_characters:
            raise LunaUXError(
                ErrorCode.BACKEND_FAILURE,
                "Backend output exceeded the configured character limit.",
                status_code=502,
            )
        return result

    def disassemble(self, bytecode: bytes, filename: str | None = None) -> str:
        safe_name = self._validate(bytecode, filename)
        return self.backend.disassemble(bytecode, safe_name)
