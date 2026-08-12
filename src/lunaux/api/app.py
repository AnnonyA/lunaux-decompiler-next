from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from lunaux import __version__
from lunaux.api.models import BytecodeRequest, DecompileRequest, HealthResult, TextResult
from lunaux.backends.auto import build_backend
from lunaux.config import Settings
from lunaux.errors import ErrorCode, LunaUXError
from lunaux.io import decode_base64
from lunaux.service import DecompilerService


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _decode_payload(value: str) -> bytes:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise LunaUXError(ErrorCode.INVALID_BASE64, "The input is not valid Base64.") from exc
    return decode_base64(encoded)


def _health_result(service: DecompilerService) -> HealthResult:
    backend = service.backend
    return HealthResult(
        status="ok",
        backend=backend.name,
        backend_version=backend.version,
    )


def _decompile_result(service: DecompilerService, payload: DecompileRequest) -> str:
    return service.decompile(
        _decode_payload(payload.bytecode),
        payload.options,
        payload.filename,
    )


def _disassemble_result(service: DecompilerService, payload: BytecodeRequest) -> str:
    return service.disassemble(
        _decode_payload(payload.bytecode),
        payload.filename,
    )


def create_app(
    service: DecompilerService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_service = service or DecompilerService(
        build_backend(
            resolved_settings.backend_module,
            resolved_settings.backend_mode,
            resolved_settings.native_path,
            resolved_settings.unluau_path,
            resolved_settings.external_timeout_seconds,
        ),
        resolved_settings.max_bytecode_bytes,
    )

    app = FastAPI(
        title="ByteWeft API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.service = resolved_service

    if resolved_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @app.exception_handler(LunaUXError)
    async def handle_lunaux_error(_request: Request, exc: LunaUXError) -> JSONResponse:
        return _error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(ErrorCode.INVALID_OPTIONS, str(exc), 422)

    @app.get("/v1/health", response_model=HealthResult)
    def health() -> HealthResult:
        return _health_result(resolved_service)

    @app.get("/health", response_model=HealthResult)
    def classic_health() -> HealthResult:
        """Compatibility health endpoint without the version prefix."""
        return _health_result(resolved_service)

    @app.post("/v1/decompile", response_model=TextResult)
    def decompile(payload: DecompileRequest) -> TextResult:
        result = _decompile_result(resolved_service, payload)
        backend = resolved_service.backend
        return TextResult(result=result, backend=backend.name, backend_version=backend.version)

    @app.post("/v1/disassemble", response_model=TextResult)
    def disassemble(payload: BytecodeRequest) -> TextResult:
        result = _disassemble_result(resolved_service, payload)
        backend = resolved_service.backend
        return TextResult(result=result, backend=backend.name, backend_version=backend.version)

    @app.post("/decompile", response_class=PlainTextResponse)
    def classic_decompile(payload: DecompileRequest) -> str:
        """Return only decompiled source for request-based Luau clients."""
        return _decompile_result(resolved_service, payload)

    @app.post("/disassemble", response_class=PlainTextResponse)
    def classic_disassemble(payload: BytecodeRequest) -> str:
        """Return only the disassembly for request-based Luau clients."""
        return _disassemble_result(resolved_service, payload)

    @app.post("/decomp", response_class=PlainTextResponse, include_in_schema=False)
    def short_decompile(payload: DecompileRequest) -> str:
        return _decompile_result(resolved_service, payload)

    @app.post("/disasm", response_class=PlainTextResponse, include_in_schema=False)
    def short_disassemble(payload: BytecodeRequest) -> str:
        return _disassemble_result(resolved_service, payload)

    return app
