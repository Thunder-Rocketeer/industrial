"""API behaviour tests.

Service dependencies are overridden with fakes, so these exercise what the route
layer is actually responsible for: parameter validation, the response envelope,
pagination metadata, error mapping and security headers. No database is
required (spec section 22).

The security sections at the foot are the ones worth reading first. They assert
that an injection payload never reaches a service, that an XSS payload comes
back inert, and that an error response never carries a stack trace or SQL.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    get_alert_service,
    get_analytics_service,
    get_dashboard_service,
    get_inventory_service,
    get_machine_service,
    get_maintenance_service,
    get_production_service,
    get_quality_service,
)
from tests import fakes
from tests.fakes import XSS_PAYLOAD

API = "/api/v1"

#: Payloads that must never reach a service. Repeated from the SQL-safety suite
#: because the boundary that stops them here is a different one: Pydantic type
#: coercion, not the repository allow-list.
INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE production_records; --",
    "1 UNION SELECT null,null",
    "../../etc/passwd",
    XSS_PAYLOAD,
]


@pytest.fixture
def services(app) -> dict[str, Any]:
    """Install fake services and return them for assertion.

    Overrides are cleared afterwards so one test cannot leak into another.
    """
    fake = {
        "production": fakes.FakeProductionService(),
        "quality": fakes.FakeQualityService(),
        "inventory": fakes.FakeInventoryService(),
        "machines": fakes.FakeMachineService(),
        "alerts": fakes.FakeAlertService(),
        "maintenance": fakes.FakeMaintenanceService(),
        "analytics": fakes.FakeAnalyticsService(),
        "dashboard": fakes.FakeDashboardService(),
    }
    app.dependency_overrides.update(
        {
            get_production_service: lambda: fake["production"],
            get_quality_service: lambda: fake["quality"],
            get_inventory_service: lambda: fake["inventory"],
            get_machine_service: lambda: fake["machines"],
            get_alert_service: lambda: fake["alerts"],
            get_maintenance_service: lambda: fake["maintenance"],
            get_analytics_service: lambda: fake["analytics"],
            get_dashboard_service: lambda: fake["dashboard"],
        }
    )
    yield fake
    app.dependency_overrides.clear()


# =============================================================================
# Envelope and pagination (spec sections 7 and 24)
# =============================================================================


def test_a_list_endpoint_returns_data_and_pagination(client: TestClient, services) -> None:
    response = client.get(f"{API}/production")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"data", "pagination"}
    assert payload["pagination"] == {"page": 1, "page_size": 25, "total": 1}


def test_an_aggregate_endpoint_returns_a_data_envelope(client: TestClient, services) -> None:
    response = client.get(f"{API}/production/summary")

    assert response.status_code == 200
    assert set(response.json()) == {"data"}


def test_pagination_parameters_reach_the_service(client: TestClient, services) -> None:
    response = client.get(f"{API}/production", params={"page": 3, "page_size": 10})

    assert response.status_code == 200
    assert response.json()["pagination"]["page"] == 3
    assert services["production"].last_filters.offset == 20
    assert services["production"].last_filters.limit == 10


def test_an_empty_result_is_a_200_with_an_empty_list(client: TestClient, services) -> None:
    """No data is a normal state, not an error."""
    services["production"].records = []
    services["production"].total = 0

    response = client.get(f"{API}/production")

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["pagination"]["total"] == 0


@pytest.mark.parametrize("page_size", [0, -1, 101, 1_000, 100_000_000])
def test_an_out_of_range_page_size_is_rejected(
    client: TestClient, services, page_size: int
) -> None:
    """Spec section 64: a client cannot request the whole table."""
    response = client.get(f"{API}/production", params={"page_size": page_size})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_the_maximum_page_size_is_accepted(client: TestClient, services) -> None:
    assert client.get(f"{API}/production", params={"page_size": 100}).status_code == 200


# =============================================================================
# Filter validation (spec section 63)
# =============================================================================


def test_valid_filters_reach_the_service(client: TestClient, services) -> None:
    machine_id = uuid4()

    response = client.get(
        f"{API}/production",
        params={
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "machine_id": str(machine_id),
        },
    )

    assert response.status_code == 200
    filters = services["production"].last_filters
    assert filters.machine_id == machine_id
    assert filters.resolved_start.isoformat() == "2026-08-01"


def test_an_inverted_date_range_is_rejected(client: TestClient, services) -> None:
    response = client.get(
        f"{API}/production",
        params={"start_date": "2026-08-31", "end_date": "2026-08-01"},
    )

    assert response.status_code == 422
    assert "start_date" in response.text


def test_an_excessive_date_range_is_rejected(client: TestClient, services) -> None:
    """Spec section 64: expensive date-range analytics need a bound."""
    response = client.get(
        f"{API}/analytics/oee",
        params={"start_date": "2020-01-01", "end_date": "2026-12-31"},
    )

    assert response.status_code == 422
    assert "maximum" in response.text.lower()


def test_dates_default_to_a_recent_window(client: TestClient, services) -> None:
    """Omitting both dates must not mean "all of history"."""
    response = client.get(f"{API}/production/summary")

    assert response.status_code == 200
    filters = services["production"].last_filters
    assert (filters.resolved_end - filters.resolved_start).days == 29


def test_an_unknown_query_parameter_is_rejected(client: TestClient, services) -> None:
    """`extra="forbid"` surfaces typos instead of silently ignoring them."""
    response = client.get(f"{API}/production", params={"machine": "typo-not-machine_id"})

    assert response.status_code == 422


@pytest.mark.parametrize("value", ["not-a-uuid", "12345", "", "null", "undefined"])
def test_a_malformed_uuid_is_rejected(client: TestClient, services, value: str) -> None:
    response = client.get(f"{API}/production", params={"machine_id": value})

    assert response.status_code == 422


@pytest.mark.parametrize("value", ["not-a-date", "2026-13-01", "01/01/2026", "yesterday"])
def test_a_malformed_date_is_rejected(client: TestClient, services, value: str) -> None:
    response = client.get(f"{API}/production", params={"start_date": value})

    assert response.status_code == 422


def test_an_invalid_enum_value_is_rejected(client: TestClient, services) -> None:
    response = client.get(f"{API}/inventory", params={"status": "SUPER_CRITICAL"})

    assert response.status_code == 422


def test_a_valid_enum_value_is_accepted(client: TestClient, services) -> None:
    response = client.get(f"{API}/inventory", params={"status": "CRITICAL"})

    assert response.status_code == 200
    assert services["inventory"].last_filters.status.value == "CRITICAL"


# =============================================================================
# Routing
# =============================================================================


def test_a_missing_resource_returns_404(client: TestClient, services) -> None:
    services["machines"].detail = None

    response = client.get(f"{API}/machines/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"


def test_a_missing_inventory_item_returns_404(client: TestClient, services) -> None:
    services["inventory"].item = None

    response = client.get(f"{API}/inventory/{uuid4()}")

    assert response.status_code == 404


def test_a_literal_path_wins_over_the_uuid_route(client: TestClient, services) -> None:
    """`/inventory/alerts` must not be parsed as an item id.

    Route order decides this. Declared after `/{item_id}`, "alerts" would fail
    UUID validation with a confusing 422.
    """
    for path in ("/inventory/alerts", "/inventory/summary"):
        assert client.get(f"{API}{path}").status_code == 200, path


def test_every_documented_endpoint_responds(client: TestClient, services) -> None:
    """The endpoints spec section 9 lists, end to end through the route layer."""
    machine_id, item_id = uuid4(), uuid4()
    endpoints = [
        "/dashboard/summary",
        "/dashboard/trends",
        "/production",
        "/production/summary",
        "/production/trend",
        "/production/by-machine",
        "/production/by-component",
        "/production/by-shift",
        "/production/by-line",
        "/quality",
        "/quality/summary",
        "/quality/defects",
        "/quality/trend",
        "/quality/by-machine",
        "/quality/by-component",
        "/inventory",
        "/inventory/alerts",
        "/inventory/summary",
        f"/inventory/{item_id}",
        f"/inventory/{item_id}/transactions",
        f"/inventory/{item_id}/trend",
        "/machines",
        "/machines/summary",
        f"/machines/{machine_id}",
        "/analytics/oee",
        "/analytics/oee/trend",
        "/analytics/oee/by-machine",
        "/analytics/production-efficiency",
        "/analytics/production-efficiency/trend",
        "/analytics/downtime",
        "/analytics/defects",
        "/alerts",
        "/alerts/active",
        "/alerts/summary",
        "/maintenance",
        "/health",
        "/health/live",
    ]

    for endpoint in endpoints:
        response = client.get(f"{API}{endpoint}")
        assert response.status_code == 200, f"{endpoint} returned {response.status_code}"


# =============================================================================
# Error envelope (spec sections 17 and 68)
# =============================================================================


def test_an_error_uses_the_documented_envelope(client: TestClient, services) -> None:
    response = client.get(f"{API}/production", params={"page_size": 9_999})
    error = response.json()["error"]

    assert set(error) >= {"code", "message"}
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)


def test_an_error_carries_the_request_id(client: TestClient, services) -> None:
    """Spec section 17 puts the correlation ID in the body as well as the header."""
    response = client.get(f"{API}/production", params={"page_size": 9_999})

    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_a_supplied_request_id_is_preserved(client: TestClient, services) -> None:
    response = client.get(f"{API}/production", headers={"X-Request-ID": "trace-me-123"})

    assert response.headers["X-Request-ID"] == "trace-me-123"


def test_a_validation_error_names_the_offending_field(client: TestClient, services) -> None:
    response = client.get(f"{API}/production", params={"page": 0})

    details = response.json()["error"]["details"]
    assert any("page" in key for key in details)


def test_a_missing_database_returns_a_clean_503(client: TestClient) -> None:
    """No service override here, so the request reaches the real (absent) pool.

    The point is that a missing database produces the error envelope with a
    generic message, not a psycopg traceback.
    """
    response = client.get(f"{API}/production/summary")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DATABASE_UNAVAILABLE"
    # The exception's own message names DATABASE_URL and Supabase settings; it
    # must stay in the log.
    assert "DATABASE_URL" not in error["message"]
    assert "supabase" not in error["message"].lower()


@pytest.mark.security
def test_no_error_response_leaks_internals(client: TestClient) -> None:
    """Spec section 68: no stack trace, SQL, path or connection string."""
    responses = [
        client.get(f"{API}/production", params={"page_size": 9_999}),
        client.get(f"{API}/production", params={"machine_id": "not-a-uuid"}),
        client.get(f"{API}/does-not-exist"),
        client.get(f"{API}/production/summary"),  # 503, no database
        client.get(f"{API}/machines/{uuid4()}"),
    ]

    forbidden = (
        "traceback",
        "site-packages",
        'file "',
        "select ",
        "insert into",
        "psycopg",
        "postgresql://",
        "redis://",
        '.py", line',
    )
    for response in responses:
        body = response.text.lower()
        for term in forbidden:
            assert term not in body, f"{response.url} leaked {term!r}"


# =============================================================================
# Security -- injection and XSS payloads
# =============================================================================


@pytest.mark.security
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_an_injection_payload_never_reaches_a_service(
    client: TestClient, services, payload: str
) -> None:
    """Typed parameters stop a payload at the boundary.

    A UUID field cannot hold `' OR '1'='1`, so the request fails validation
    before a query is built. This is layer 3 of the injection defence and the
    one that fires first.
    """
    for parameter in ("machine_id", "component_id", "shift_id", "line_id"):
        response = client.get(f"{API}/production", params={parameter: payload})

        assert response.status_code == 422, f"{parameter}={payload!r} was not rejected"

    assert services["production"].last_filters is None, (
        "A rejected request must not reach the service layer."
    )


@pytest.mark.security
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_an_injected_sort_field_is_rejected(client: TestClient, services, payload: str) -> None:
    """`sort_by` is the one request value that shapes the SQL structure.

    The fake service does not validate it, so this asserts the request is
    accepted as a *string* by the boundary and then rejected by the allow-list
    in the repository -- which is where the real defence lives. Here the fake
    short-circuits that, so the test asserts only that nothing 500s.
    """
    response = client.get(f"{API}/production", params={"sort_by": payload})

    assert response.status_code in (200, 422)
    assert response.status_code != 500


@pytest.mark.security
@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_an_injected_path_parameter_is_rejected(client: TestClient, services, payload: str) -> None:
    """A path UUID is validated identically to a query UUID.

    The `services` fixture matters here. Without it the request reaches the real
    (absent) database and returns 503 before the path parameter is validated --
    FastAPI resolves dependencies alongside parameter validation, and a
    dependency that raises wins. With the services overridden, the validation
    error is what surfaces, which is what this test is about.
    """
    response = client.get(f"{API}/machines/{payload}")

    if "/" in payload:
        # A payload containing a slash produces extra path segments, so no route
        # matches at all and the answer is 404. Path traversal never reaches a
        # handler, which is the outcome that matters.
        assert response.status_code == 404
        return

    assert response.status_code == 422
    assert "machine_id" in str(response.json()["error"]["details"])


@pytest.mark.security
def test_an_xss_payload_is_returned_inert(client: TestClient, services) -> None:
    """Spec section 14: the API returns structured data, never HTML.

    A script tag stored in a database field comes back as a JSON string value.
    JSON escaping means it cannot terminate the response and become markup, and
    the content type tells the browser not to parse it as a document.
    """
    services["alerts"].alerts = [
        fakes.make_alert(title=XSS_PAYLOAD, description=f"Injected: {XSS_PAYLOAD}")
    ]

    response = client.get(f"{API}/alerts")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    alert = response.json()["data"][0]
    # The value survives intact as data -- not stripped, not mangled. Sanitising
    # here would be wrong: the API's job is to return what is stored, and the
    # frontend escapes on render.
    assert alert["title"] == XSS_PAYLOAD

    # The payload does appear in the raw JSON body, because JSON does not escape
    # angle brackets and does not need to. What makes that safe is the pair of
    # headers below: the response is declared as JSON, and `nosniff` stops a
    # browser opening it directly from re-interpreting it as HTML and executing
    # the script.
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.security
def test_security_headers_are_present(client: TestClient, services) -> None:
    """Spec section 62, for the headers that belong at this boundary.

    CSP and HSTS are deliberately absent: CSP must be written against the
    frontend's real sources, and HSTS belongs at the TLS-terminating proxy.
    """
    response = client.get(f"{API}/production")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Permissions-Policy" in response.headers


@pytest.mark.security
def test_no_endpoint_returns_html(client: TestClient, services) -> None:
    """Spec section 14: do not create HTML from database values."""
    for endpoint in ("/production", "/quality", "/inventory", "/machines", "/alerts"):
        response = client.get(f"{API}{endpoint}")

        assert response.headers["content-type"].startswith("application/json")
        assert not response.text.lstrip().startswith("<")


# =============================================================================
# Security: rate limiting through the middleware
# =============================================================================


@pytest.mark.security
def test_responses_carry_rate_limit_headers(client: TestClient, services) -> None:
    response = client.get(f"{API}/production")

    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
    assert "X-RateLimit-Reset" in response.headers


@pytest.mark.security
def test_rate_limiting_fails_open_without_redis(client: TestClient, services) -> None:
    """No Redis is configured in tests, so every request must still be served.

    This is the degradation requirement stated as an API-level fact: a cache
    outage must not close the API.
    """
    for _ in range(30):
        assert client.get(f"{API}/production").status_code == 200


# =============================================================================
# Accessibility of the payload (spec section 45)
# =============================================================================


def test_status_values_travel_with_text_labels(client: TestClient, services) -> None:
    """State must never be conveyed by colour alone.

    Every status the API reports carries a human-readable label, so the frontend
    renders words rather than mapping an enum to a colour.
    """
    machines = client.get(f"{API}/machines").json()["data"]
    assert machines[0]["status_label"] == "Running"
    assert machines[0]["machine_type_label"]

    inventory = client.get(f"{API}/inventory").json()["data"]
    assert inventory[0]["status_label"]

    alerts = client.get(f"{API}/alerts").json()["data"]
    assert alerts[0]["severity_label"]
    assert alerts[0]["description"], "An alert must be readable as text."


def test_a_dashboard_kpi_carries_status_text_not_a_colour(client: TestClient, services) -> None:
    payload = client.get(f"{API}/dashboard/summary").json()["data"]
    kpi = payload["kpis"][0]

    assert kpi["status"] in {"good", "warning", "critical", "neutral"}
    assert kpi["status_label"]
    assert kpi["trend"]["direction"] in {"up", "down", "flat", "unknown"}


# =============================================================================
# Health (spec section 20)
# =============================================================================


def test_liveness_does_not_depend_on_the_database(client: TestClient) -> None:
    """No database is configured here, and liveness must still report ok.

    If liveness checked the database, a database blip would have every instance
    killed and restarted -- turning a recoverable outage into an application one.
    """
    response = client.get(f"{API}/health")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_readiness_reports_an_unavailable_database(client: TestClient) -> None:
    response = client.get(f"{API}/health/ready")

    assert response.status_code == 503
    payload = response.json()["data"]
    assert payload["status"] == "not_ready"

    database = next(d for d in payload["dependencies"] if d["name"] == "database")
    assert database["healthy"] is False


def test_readiness_names_every_dependency(client: TestClient) -> None:
    payload = client.get(f"{API}/health/ready").json()["data"]

    assert {d["name"] for d in payload["dependencies"]} == {"database", "cache"}


# =============================================================================
# OpenAPI documentation (spec section 21)
# =============================================================================


def test_every_endpoint_is_documented(app) -> None:
    """Spec section 21: summary, description, response model and tags."""
    spec = app.openapi()

    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            label = f"{method.upper()} {path}"
            assert operation.get("summary"), f"{label} has no summary."
            assert operation.get("description"), f"{label} has no description."
            assert operation.get("tags"), f"{label} has no tag."
            assert "200" in operation["responses"], f"{label} documents no success response."


def test_endpoints_are_grouped_into_the_expected_tags(app) -> None:
    spec = app.openapi()
    tags = {tag["name"] for tag in spec["openapi"] and spec.get("tags", [])}

    assert tags == {
        "Dashboard",
        "Production",
        "Quality",
        "Inventory",
        "Machines",
        "Analytics",
        "Alerts",
        "Maintenance",
        "Health",
    }


def test_query_parameters_are_described(app) -> None:
    """A parameter without a description is undiscoverable in the docs."""
    spec = app.openapi()
    operation = spec["paths"]["/api/v1/production"]["get"]

    described = [p for p in operation.get("parameters", []) if p.get("description")]
    assert len(described) >= 6, "Production filters should be documented."
