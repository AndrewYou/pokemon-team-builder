"""Tests for the demo surface itself.

Swagger is how this project is reviewed, so the shape of the OpenAPI document
is a real requirement: every operation grouped, titled, and either open or
explicitly protected. None of these tests touch the database.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def schema(client: TestClient) -> dict[str, Any]:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return dict(response.json())


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, operation)
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
    ]


class TestDocsAreOpen:
    """A reviewer must be able to browse without credentials."""

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_reachable_without_auth(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 200

    def test_root_redirects_to_docs(self, client: TestClient) -> None:
        """The bare Railway URL should land somewhere useful."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (307, 308)
        assert response.headers["location"] == "/docs"


class TestOperationMetadata:
    def test_every_operation_has_a_summary(self, schema: dict[str, Any]) -> None:
        missing = [f"{m.upper()} {p}" for p, m, op in _operations(schema) if not op.get("summary")]
        assert not missing, f"operations without a summary: {missing}"

    def test_every_operation_is_tagged(self, schema: dict[str, Any]) -> None:
        missing = [f"{m.upper()} {p}" for p, m, op in _operations(schema) if not op.get("tags")]
        assert not missing, f"untagged operations: {missing}"

    def test_every_tag_used_is_documented(self, schema: dict[str, Any]) -> None:
        """An undescribed group renders as a bare heading in Swagger."""
        documented = {tag["name"] for tag in schema["tags"]}
        used = {tag for _, _, op in _operations(schema) for tag in op.get("tags", [])}
        assert used <= documented, f"undocumented tags: {used - documented}"

    def test_declared_tag_groups_are_present(self, schema: dict[str, Any]) -> None:
        documented = {tag["name"] for tag in schema["tags"]}
        assert {"catalog", "teams", "counter-team", "alerts", "admin"} <= documented

    def test_every_operation_declares_a_success_response(self, schema: dict[str, Any]) -> None:
        for path, method, operation in _operations(schema):
            codes = list(operation.get("responses", {}))
            assert any(c.startswith("2") for c in codes), f"{method.upper()} {path}"


class TestSecurityMarking:
    def test_admin_operations_require_auth(self, schema: dict[str, Any]) -> None:
        admin = [(p, m, op) for p, m, op in _operations(schema) if p.startswith("/admin")]
        assert admin, "no admin operations found"
        for path, method, operation in admin:
            assert operation.get("security"), f"{method.upper()} {path} is unprotected"

    def test_health_stays_open(self, schema: dict[str, Any]) -> None:
        health = schema["paths"]["/health"]["get"]
        assert not health.get("security")

    def test_basic_auth_scheme_is_declared(self, schema: dict[str, Any]) -> None:
        schemes = schema["components"]["securitySchemes"]
        assert any(s.get("scheme") == "basic" for s in schemes.values())


class TestExamples:
    @pytest.mark.parametrize(
        "model", ["HealthResponse", "JobAccepted", "JobRead", "StatsResponse", "DataQuality"]
    )
    def test_response_models_prefill_try_it_out(self, schema: dict[str, Any], model: str) -> None:
        """Without an example, Swagger renders an empty skeleton."""
        assert "example" in schema["components"]["schemas"][model]

    def test_seed_source_is_an_enum_dropdown(self, schema: dict[str, Any]) -> None:
        """A free-text field invites typos during a live demo."""
        params = schema["paths"]["/admin/seed"]["post"]["parameters"]
        source = next(p for p in params if p["name"] == "source")
        assert set(schema["components"]["schemas"]["SeedSource"]["enum"]) == {"fixture", "live"}
        assert source["required"] is False


class TestAdminGate:
    def test_admin_route_rejects_missing_credentials(self, client: TestClient) -> None:
        assert client.get("/admin/stats").status_code == 401

    def test_admin_route_rejects_wrong_credentials(self, client: TestClient) -> None:
        assert client.get("/admin/stats", auth=("admin", "nope")).status_code == 401
