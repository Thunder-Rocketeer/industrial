"""Tests for the health endpoint and the Phase 1 application wiring."""

from __future__ import annotations

from app import __version__


def test_health_returns_ok(client, settings) -> None:
    """The liveness endpoint reports status without needing a database."""
    response = client.get(f"{settings.api_v1_prefix}/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["version"] == __version__
    assert payload["data"]["environment"] == settings.app_env.value


def test_health_response_carries_correlation_id(client, settings) -> None:
    """Every response echoes a request ID so logs can be tied to a request."""
    response = client.get(f"{settings.api_v1_prefix}/health")

    assert response.headers.get("X-Request-ID")


def test_supplied_correlation_id_is_preserved(client, settings) -> None:
    """A client-supplied request ID flows through to the response."""
    supplied = "test-correlation-id-123"
    response = client.get(
        f"{settings.api_v1_prefix}/health",
        headers={"X-Request-ID": supplied},
    )

    assert response.headers["X-Request-ID"] == supplied


def test_unknown_route_returns_error_envelope(client) -> None:
    """404s use the documented error envelope rather than FastAPI's default."""
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "HTTP_404"
    assert "message" in payload["error"]


def test_error_response_hides_internal_details(client) -> None:
    """Spec section 68: no stack trace, SQL or path leaks into an error body."""
    response = client.get("/api/v1/does-not-exist")

    body = response.text.lower()
    for forbidden in ("traceback", 'file "', "site-packages", "select "):
        assert forbidden not in body
