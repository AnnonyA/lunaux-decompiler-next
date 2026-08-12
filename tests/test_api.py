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


def encoded(value: bytes) -> str:
    return base64.b64encode(value).decode()


def test_health_reports_backend() -> None:
    response = client().get("/v1/health")
    assert response.status_code == 200
    assert response.json()["backend"] == "fake"


def test_classic_health_alias_reports_backend() -> None:
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json()["backend"] == "fake"


def test_decompile_returns_structured_result() -> None:
    response = client().post(
        "/v1/decompile",
        json={"bytecode": encoded(b"abc"), "filename": "A.luau"},
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result.startswith("-- [[ ByteWeft v")
    assert "decompiled:A.luau:3" in result


def test_classic_decompile_returns_plain_source() -> None:
    response = client().post(
        "/decompile",
        json={"bytecode": encoded(b"abc"), "filename": "A.luau"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.startswith("-- [[ ByteWeft v")
    assert "decompiled:A.luau:3" in response.text


def test_classic_api_accepts_pascal_case_options() -> None:
    response = client().post(
        "/decompile",
        json={
            "bytecode": encoded(b"abc"),
            "filename": "A.luau",
            "options": {"UseIfExpression": False, "Semicolons": True},
        },
    )
    assert response.status_code == 200
    assert response.text.endswith(":False")


def test_api_can_disable_the_presentation_header() -> None:
    response = client().post(
        "/decompile",
        json={
            "bytecode": encoded(b"abc"),
            "filename": "A.luau",
            "options": {"IncludeHeader": False},
        },
    )

    assert response.status_code == 200
    assert response.text.startswith("decompiled:A.luau:3")


def test_classic_disassemble_returns_plain_text() -> None:
    response = client().post(
        "/disassemble",
        json={"bytecode": encoded(b"abc"), "filename": "A.luau"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "disassembled:A.luau:3"


def test_short_route_aliases_work() -> None:
    decompile_response = client().post(
        "/decomp",
        json={"bytecode": encoded(b"abc")},
    )
    disassemble_response = client().post(
        "/disasm",
        json={"bytecode": encoded(b"abc")},
    )
    assert decompile_response.status_code == 200
    assert disassemble_response.status_code == 200


def test_invalid_base64_returns_error_object() -> None:
    response = client().post("/v1/disassemble", json={"bytecode": "!!!"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_BASE64"
