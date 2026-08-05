from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from lunaux.api.app import create_app
from lunaux.config import Settings
from lunaux.service import DecompilerService
from tests.fakes import FakeBackend


def client() -> TestClient:
    service = DecompilerService(FakeBackend(), max_bytecode_bytes=100)
    app = create_app(service, Settings(max_bytecode_bytes=100))
    return TestClient(app)


def test_health_reports_backend() -> None:
    response = client().get("/v1/health")
    assert response.status_code == 200
    assert response.json()["backend"] == "fake"


def test_decompile_returns_structured_result() -> None:
    response = client().post(
        "/v1/decompile",
        json={"bytecode": base64.b64encode(b"abc").decode(), "filename": "A.luau"},
    )
    assert response.status_code == 200
    assert response.json()["result"].startswith("decompiled:A.luau:3")


def test_invalid_base64_returns_error_object() -> None:
    response = client().post("/v1/disassemble", json={"bytecode": "!!!"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_BASE64"
