"""Live end-to-end probe against a running API.

    python tools/e2e_probe.py all
    python tools/e2e_probe.py contract --base http://127.0.0.1:8000/api/v1

Phase 7 has to exercise the real stack -- FastAPI against real PostgreSQL and
real Redis -- and check the things a unit test structurally cannot: that the
JSON a live endpoint returns matches the frontend's TypeScript types, that RBAC
refuses the right roles at the API rather than merely hiding a link, that the
cache actually caches, that rate limiting actually limits, and that hostile
input is handled safely.

See `e2e_harness` for how sessions are minted and, importantly, for what that
does and does not prove about the OAuth flow.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid
from typing import Any

import jwt as pyjwt
from tools.e2e_harness import (
    DEFAULT_BASE,
    Results,
    anon_client,
    client_for,
    parse_limit,
    seeded_users,
    token_client,
)

from app.config import get_settings
from app.security.jwt import issue_access_token

# =============================================================================
# Contract
# =============================================================================

#: Endpoints to check, with the fields the frontend declares as required and
#: those it declares nullable. Sourced by reading `client/types/*.ts`.
#:
#: The check runs in both directions, which is the point: a field the frontend
#: requires must be present, and a field it types as non-nullable must never
#: arrive null. The second half is what catches the mismatches that survive a
#: type-check -- TypeScript believes the annotation, and only a live response
#: can contradict it.
CONTRACT: list[dict[str, Any]] = [
    {
        "name": "auth.me",
        "path": "/auth/me",
        "envelope": "object",
        "required": [
            "id",
            "email",
            "name",
            "role",
            "role_label",
            "avatar_url",
            "is_active",
            "last_login_at",
            "permissions",
        ],
        "nullable": ["avatar_url", "last_login_at"],
    },
    {
        "name": "dashboard.summary",
        "path": "/dashboard/summary",
        "envelope": "object",
        "required": [
            "generated_at",
            "business_date",
            "kpis",
            "production",
            "quality",
            "inventory",
            "machines",
            "oee",
            "alerts",
            "recent_alerts",
            "cache_hit",
        ],
    },
    {
        "name": "dashboard.trends",
        "path": "/dashboard/trends",
        "envelope": "object",
        "required": [
            "start_date",
            "end_date",
            "production",
            "defects",
            "oee",
            "top_defects",
            "has_data",
        ],
    },
    {
        "name": "production.list",
        "path": "/production",
        "envelope": "paginated",
        "required": [
            "id",
            "record_date",
            "machine_id",
            "machine_code",
            "machine_name",
            "component_id",
            "component_code",
            "component_name",
            "line_id",
            "line_code",
            "line_name",
            "shift_id",
            "shift_code",
            "shift_name",
            "started_at",
            "ended_at",
            "planned_quantity",
            "produced_quantity",
            "accepted_quantity",
            "rejected_quantity",
            "planned_minutes",
            "operating_minutes",
            "downtime_minutes",
            "efficiency_percentage",
            "defect_rate_percentage",
        ],
    },
    {
        "name": "production.summary",
        "path": "/production/summary",
        "envelope": "object",
        "required": [
            "start_date",
            "end_date",
            "total_planned",
            "total_produced",
            "total_accepted",
            "total_rejected",
            "target_quantity",
            "achievement_percentage",
            "efficiency_percentage",
            "defect_rate_percentage",
            "total_planned_minutes",
            "total_operating_minutes",
            "total_downtime_minutes",
            "record_count",
            "has_data",
        ],
    },
    {
        "name": "production.trend",
        "path": "/production/trend",
        "envelope": "array",
        "required": [
            "bucket_date",
            "planned_quantity",
            "produced_quantity",
            "accepted_quantity",
            "rejected_quantity",
            "target_quantity",
            "achievement_percentage",
        ],
    },
    {
        "name": "quality.list",
        "path": "/quality",
        "envelope": "paginated",
        "required": [
            "id",
            "production_record_id",
            "inspected_at",
            "machine_id",
            "machine_code",
            "component_id",
            "component_code",
            "component_name",
            "defect_id",
            "defect_code",
            "defect_name",
            "severity",
            "inspected_quantity",
            "passed_quantity",
            "rejected_quantity",
            "first_pass_quantity",
            "rework_quantity",
            "is_rejection",
        ],
        "nullable": ["defect_id", "defect_code", "defect_name", "severity"],
    },
    {
        "name": "quality.summary",
        "path": "/quality/summary",
        "envelope": "object",
        "required": [
            "start_date",
            "end_date",
            "total_inspected",
            "total_passed",
            "total_rejected",
            "total_first_pass",
            "total_rework",
            "defect_rate_percentage",
            "first_pass_yield_percentage",
            "quality_rate_percentage",
            "distinct_defect_types",
            "record_count",
            "has_data",
        ],
    },
    {
        "name": "quality.defects",
        "path": "/quality/defects",
        "envelope": "array",
        "required": [
            "defect_id",
            "defect_code",
            "defect_name",
            "category",
            "default_severity",
            "rejected_quantity",
            "occurrence_count",
            "share_percentage",
            "cumulative_percentage",
        ],
    },
    {
        "name": "inventory.list",
        "path": "/inventory",
        "envelope": "paginated",
        "required": [
            "id",
            "sku",
            "name",
            "material_type",
            "unit",
            "component_id",
            "component_code",
            "component_name",
            "current_quantity",
            "minimum_stock",
            "reorder_point",
            "maximum_stock",
            "status",
            "status_label",
            "stock_utilization_percentage",
            "supplier_name",
            "supplier_lead_time_days",
            "unit_cost",
            "last_counted_at",
            "updated_at",
        ],
        "nullable": [
            "component_id",
            "component_code",
            "component_name",
            "supplier_lead_time_days",
            "unit_cost",
            "last_counted_at",
        ],
    },
    {
        "name": "inventory.summary",
        "path": "/inventory/summary",
        "envelope": "object",
        "required": [
            "total_items",
            "healthy_count",
            "low_count",
            "critical_count",
            "overstocked_count",
            "health_percentage",
            "items_requiring_attention",
            "total_stock_value",
            "status_breakdown",
        ],
        "nullable": ["total_stock_value"],
    },
    {
        "name": "inventory.alerts",
        "path": "/inventory/alerts",
        "envelope": "array",
        "required": [
            "id",
            "sku",
            "name",
            "unit",
            "status",
            "status_label",
            "current_quantity",
            "minimum_stock",
            "reorder_point",
            "shortfall",
            "supplier_name",
            "supplier_lead_time_days",
            "message",
        ],
        "nullable": ["supplier_lead_time_days"],
    },
    {
        "name": "machines.list",
        "path": "/machines",
        "envelope": "array",
        "required": [
            "id",
            "code",
            "name",
            "machine_type",
            "machine_type_label",
            "line_id",
            "line_code",
            "line_name",
            "status",
            "status_label",
            "current_component_id",
            "current_component_name",
            "utilization_percentage",
            "total_downtime_minutes",
            "commissioned_date",
            "last_maintenance_date",
            "next_maintenance_date",
            "days_until_maintenance",
            "maintenance_due",
        ],
        "nullable": [
            "current_component_id",
            "current_component_name",
            "last_maintenance_date",
            "next_maintenance_date",
            "days_until_maintenance",
        ],
    },
    {
        "name": "machines.summary",
        "path": "/machines/summary",
        "envelope": "object",
        "required": [
            "total_machines",
            "running_count",
            "idle_count",
            "maintenance_count",
            "offline_count",
            "availability_percentage",
            "average_utilization_percentage",
            "maintenance_due_count",
            "status_breakdown",
        ],
    },
    {
        "name": "analytics.oee",
        "path": "/analytics/oee",
        "envelope": "object",
        "required": [
            "start_date",
            "end_date",
            "availability_percentage",
            "performance_percentage",
            "quality_percentage",
            "oee_percentage",
            "performance_uncapped_percentage",
            "operating_minutes",
            "planned_minutes",
            "downtime_minutes",
            "produced_quantity",
            "accepted_quantity",
            "rejected_quantity",
            "ideal_output",
            "record_count",
            "has_data",
        ],
    },
    {
        "name": "analytics.oee.trend",
        "path": "/analytics/oee/trend",
        "envelope": "array",
        "required": [
            "bucket_date",
            "availability_percentage",
            "performance_percentage",
            "quality_percentage",
            "oee_percentage",
            "performance_uncapped_percentage",
        ],
    },
    {
        "name": "analytics.oee.by_machine",
        "path": "/analytics/oee/by-machine",
        "envelope": "array",
        "required": [
            "machine_id",
            "machine_code",
            "machine_name",
            "produced_quantity",
            "operating_minutes",
            "availability_percentage",
            "performance_percentage",
            "quality_percentage",
            "oee_percentage",
            "performance_uncapped_percentage",
        ],
    },
    {
        "name": "analytics.downtime",
        "path": "/analytics/downtime",
        "envelope": "array",
        "required": [
            "machine_id",
            "machine_code",
            "machine_name",
            "downtime_minutes",
            "planned_minutes",
            "downtime_percentage",
        ],
    },
    {
        "name": "analytics.efficiency.trend",
        "path": "/analytics/production-efficiency/trend",
        "envelope": "array",
        "required": [
            "bucket_date",
            "planned_quantity",
            "produced_quantity",
            "target_quantity",
            "efficiency_percentage",
            "achievement_percentage",
        ],
    },
    {
        "name": "analytics.efficiency",
        # The frontend calls `/analytics/production-efficiency`; an earlier
        # draft of this probe guessed `/analytics/efficiency` and got a 404.
        "path": "/analytics/production-efficiency",
        "envelope": "object",
        "required": [
            "start_date",
            "end_date",
            "total_planned",
            "total_produced",
            "total_target",
            "efficiency_percentage",
            "achievement_percentage",
            "total_planned_minutes",
            "total_operating_minutes",
            "total_downtime_minutes",
            "downtime_percentage",
            "record_count",
            "has_data",
        ],
    },
    {
        "name": "analytics.defects",
        "path": "/analytics/defects",
        "envelope": "object",
        "required": [
            "start_date",
            "end_date",
            "total_inspected",
            "total_rejected",
            "defect_rate_percentage",
            "by_defect",
            "by_machine",
            "by_component",
            "trend",
            "has_data",
        ],
    },
    {
        "name": "alerts.list",
        "path": "/alerts",
        "envelope": "paginated",
        "required": [
            "id",
            "alert_type",
            "alert_type_label",
            "severity",
            "severity_label",
            "status",
            "status_label",
            "title",
            "description",
            "machine_id",
            "machine_code",
            "machine_name",
            "component_id",
            "component_name",
            "inventory_item_id",
            "inventory_item_name",
            "line_id",
            "line_name",
            "triggered_at",
            "acknowledged_at",
            "resolved_at",
            "age_minutes",
        ],
        "nullable": [
            "machine_id",
            "machine_code",
            "machine_name",
            "component_id",
            "component_name",
            "inventory_item_id",
            "inventory_item_name",
            "line_id",
            "line_name",
            "acknowledged_at",
            "resolved_at",
        ],
    },
    {
        "name": "alerts.summary",
        "path": "/alerts/summary",
        "envelope": "object",
        "required": [
            "total_open",
            "critical_count",
            "warning_count",
            "info_count",
            "acknowledged_count",
            "severity_breakdown",
        ],
    },
    {
        "name": "maintenance.list",
        "path": "/maintenance",
        "envelope": "paginated",
        "required": [
            "id",
            "machine_id",
            "machine_code",
            "machine_name",
            "maintenance_type",
            "maintenance_type_label",
            "status",
            "status_label",
            "scheduled_date",
            "started_at",
            "completed_at",
            "downtime_minutes",
            "technician",
            "description",
            "cost",
            "is_overdue",
        ],
        "nullable": ["started_at", "completed_at", "cost"],
    },
]


def suite_contract(users, base, results: Results) -> None:
    """Live responses against the frontend's declared field sets."""
    with client_for("ADMIN", users, base) as client:
        for spec in CONTRACT:
            response = client.get(spec["path"])
            if response.status_code != 200:
                results.check(False, spec["name"], f"HTTP {response.status_code}")
                continue

            body = response.json()
            nullable = set(spec.get("nullable", []))
            required = spec["required"]

            if spec["envelope"] == "paginated":
                if not results.check(
                    "data" in body and "pagination" in body, f"{spec['name']}: paginated envelope"
                ):
                    continue
                meta = body["pagination"]
                results.check(
                    {"page", "page_size", "total"} <= set(meta)
                    and all(isinstance(meta[k], int) for k in ("page", "page_size", "total")),
                    f"{spec['name']}: pagination metadata",
                    f"page={meta.get('page')} size={meta.get('page_size')} "
                    f"total={meta.get('total')}",
                )
                items = body["data"]
            else:
                if not results.check("data" in body, f"{spec['name']}: data envelope"):
                    continue
                payload = body["data"]
                items = payload if isinstance(payload, list) else [payload]

            if not items:
                results.note(f"{spec['name']}: no rows returned; field check skipped")
                continue

            sample = items[0]
            missing = [f for f in required if f not in sample]
            results.check(
                not missing,
                f"{spec['name']}: declared fields present",
                f"missing={missing}" if missing else f"{len(required)} fields",
            )

            wrong_null = [
                f for f in required if f not in nullable and f in sample and sample[f] is None
            ]
            results.check(
                not wrong_null,
                f"{spec['name']}: non-nullable fields are not null",
                f"unexpectedly null={wrong_null}" if wrong_null else "",
            )

            extra = [f for f in sample if f not in required]
            if extra:
                results.note(f"{spec['name']}: response carries extra fields {extra}")


# =============================================================================
# RBAC
# =============================================================================

RBAC_MATRIX = [
    ("/dashboard/summary", "dashboard:read"),
    ("/production/summary", "production:read"),
    ("/quality/summary", "quality:read"),
    ("/inventory/summary", "inventory:read"),
    ("/machines/summary", "machines:read"),
    ("/analytics/oee", "analytics:read"),
    ("/alerts/summary", "alerts:read"),
    ("/maintenance", "maintenance:read"),
]


def suite_rbac(users, base, results: Results) -> None:
    """Every role against every domain, asserted in both directions."""
    from app.security.policy import Permission, permissions_for

    for path, permission_code in RBAC_MATRIX:
        permission = Permission(permission_code)
        for role in sorted(users):
            granted = permission in permissions_for(role)
            with client_for(role, users, base) as client:
                status = client.get(path).status_code
            if granted:
                results.check(status == 200, f"{role} may GET {path}", f"HTTP {status}")
            else:
                # The API refuses independently of what the UI shows.
                results.check(
                    status == 403, f"{role} is refused {path}", f"HTTP {status} (expected 403)"
                )

    with anon_client(base) as client:
        for path, _ in RBAC_MATRIX:
            status = client.get(path).status_code
            results.check(
                status == 401, f"anonymous is refused {path}", f"HTTP {status} (expected 401)"
            )


# =============================================================================
# Session
# =============================================================================


def suite_session(users, base, results: Results) -> None:
    """Valid, anonymous, malformed, foreign-key, expired and alg=none tokens."""
    settings = get_settings()
    now = dt.datetime.now(dt.timezone.utc)

    with client_for("ADMIN", users, base) as client:
        response = client.get("/auth/me")
        if results.check(
            response.status_code == 200,
            "valid session resolves /auth/me",
            f"HTTP {response.status_code}",
        ):
            body = response.json()["data"]
            results.check(
                body["role"] == "ADMIN", "role reported correctly", body.get("role_label", "")
            )
            results.check(
                len(body.get("permissions", [])) > 0,
                "permissions returned",
                f"{len(body.get('permissions', []))}",
            )
            results.check(
                not any(k in body for k in ("token", "access_token", "jwt")),
                "no token echoed back to the client",
            )

    with anon_client(base) as client:
        results.check(client.get("/auth/me").status_code == 401, "anonymous /auth/me is 401")

    cases = [
        ("malformed token", "not-a-jwt"),
        (
            "token signed with a foreign key",
            pyjwt.encode(
                {
                    "sub": str(users["ADMIN"]),
                    "iss": settings.jwt_issuer,
                    "aud": settings.jwt_audience,
                    "exp": int((now + dt.timedelta(minutes=5)).timestamp()),
                    "iat": int(now.timestamp()),
                    "jti": str(uuid.uuid4()),
                    "typ": "access",
                    "role": "ADMIN",
                },
                "an-attacker-chosen-key-long-enough-to-encode-with",
                algorithm="HS256",
            ),
        ),
        (
            "alg=none token",
            pyjwt.encode({"sub": str(users["ADMIN"]), "role": "ADMIN"}, key="", algorithm="none"),
        ),
        (
            "expired token",
            issue_access_token(
                user_id=users["ADMIN"],
                role="ADMIN",
                settings=settings,
                issued_at=now - dt.timedelta(days=2),
            )[0],
        ),
    ]

    for label, token in cases:
        with token_client(token, base) as client:
            status = client.get("/auth/me").status_code
        results.check(status == 401, f"{label} is refused", f"HTTP {status}")

    # A role claim in the token must not override the database.
    forged_role, _ = issue_access_token(user_id=users["VIEWER"], role="ADMIN", settings=settings)
    with token_client(forged_role, base) as client:
        response = client.get("/auth/me")
        if response.status_code == 200:
            reported = response.json()["data"]["role"]
            results.check(
                reported == "VIEWER",
                "role comes from the database, not the token claim",
                f"token said ADMIN, API reports {reported}",
            )
        else:
            results.check(False, "role claim check", f"HTTP {response.status_code}")


# =============================================================================
# Cache
# =============================================================================


def suite_cache(users, base, results: Results) -> None:
    """Miss, hit, TTL, key separation, and the dashboard's own cache_hit flag."""
    import redis as redis_sync

    settings = get_settings()
    r = redis_sync.Redis.from_url(settings.redis_url, socket_connect_timeout=5)
    try:
        r.ping()
    except Exception as exc:
        results.check(False, "redis reachable from the probe", type(exc).__name__)
        return

    try:
        # Start from a known state. Otherwise the miss/hit assertions below are
        # really testing whether an earlier run left a key behind, and they
        # flip depending on the order suites happen to execute in.
        evicted = 0
        for key in r.scan_iter(match="acf:v1:*", count=1000):
            r.delete(key)
            evicted += 1
        results.note(f"evicted {evicted} cache keys so misses are observable")

        before = r.dbsize()
        with client_for("ADMIN", users, base) as client:
            params = {"start_date": "2026-02-03", "end_date": "2026-02-09"}

            first = client.get("/production/summary", params=params)
            results.check(first.status_code == 200, "cache: first request succeeds")
            after_first = r.dbsize()
            results.check(
                after_first > before,
                "cache: a key is written on a miss",
                f"dbsize {before} -> {after_first}",
            )

            second = client.get("/production/summary", params=params)
            results.check(
                second.json() == first.json(), "cache: the hit returns an identical payload"
            )
            results.check(
                r.dbsize() == after_first,
                "cache: a hit writes no new key",
                f"dbsize still {after_first}",
            )

            keys = [k.decode() for k in r.scan_iter(match="*production*", count=500)][:3]
            results.check(
                bool(keys), "cache: production keys exist in Redis", keys[0][:60] if keys else ""
            )
            for key in keys:
                ttl = r.ttl(key)
                results.check(ttl > 0, f"cache: TTL is set ({key[:40]})", f"{ttl}s")

            client.get(
                "/production/summary", params={"start_date": "2026-02-10", "end_date": "2026-02-16"}
            )
            results.check(
                r.dbsize() > after_first,
                "cache: a different filter is a separate entry",
                f"dbsize {after_first} -> {r.dbsize()}",
            )

            d1 = client.get("/dashboard/summary").json()["data"]
            d2 = client.get("/dashboard/summary").json()["data"]
            results.check(
                d1.get("cache_hit") is False and d2.get("cache_hit") is True,
                "cache: dashboard reports cache_hit truthfully",
                f"first={d1.get('cache_hit')} second={d2.get('cache_hit')}",
            )
            results.check(
                d1["production"]["total_produced"] == d2["production"]["total_produced"],
                "cache: the cached payload matches the fresh one",
            )
    finally:
        r.close()


# =============================================================================
# Rate limiting
# =============================================================================


def suite_ratelimit(users, base, results: Results) -> None:
    """Drive an endpoint past its threshold and confirm a real 429."""
    import redis as redis_sync

    settings = get_settings()
    if not settings.rate_limit_enabled:
        results.note("rate limiting is disabled in settings; suite skipped")
        return

    r = redis_sync.Redis.from_url(settings.redis_url, socket_connect_timeout=5)
    for key in r.scan_iter(match="*ratelimit*", count=1000):
        r.delete(key)

    limit, _ = parse_limit(settings.rate_limit_authenticated)
    results.note(f"authenticated limit is {settings.rate_limit_authenticated}")

    statuses: list[int] = []
    with client_for("ADMIN", users, base) as client:
        for _ in range(limit + 20):
            statuses.append(client.get("/machines/summary").status_code)
            if statuses[-1] == 429:
                break

        results.check(
            sum(1 for s in statuses if s == 200) > 0,
            "rate limit: normal traffic succeeds",
            f"{sum(1 for s in statuses if s == 200)} of {len(statuses)} were 200",
        )
        limited = results.check(
            429 in statuses, "rate limit: threshold enforced", f"429 after {len(statuses)} requests"
        )

        if limited:
            response = client.get("/machines/summary")
            if response.status_code == 429:
                headers = {k.lower() for k in response.headers}
                results.check(
                    "retry-after" in headers,
                    "rate limit: Retry-After header present",
                    response.headers.get("retry-after", "absent"),
                )
                results.check("error" in response.json(), "rate limit: error envelope returned")

            # A header a client controls must not move it to a fresh bucket.
            spoofed = client.get(
                "/machines/summary",
                headers={"X-Forwarded-For": f"10.0.0.{uuid.uuid4().int % 250}"},
            )
            results.check(
                spoofed.status_code == 429,
                "rate limit: X-Forwarded-For does not reset the bucket",
                f"HTTP {spoofed.status_code}",
            )

    keys = [k.decode() for k in r.scan_iter(match="*ratelimit*", count=1000)][:2]
    results.check(
        bool(keys), "rate limit: counters are held in Redis", keys[0][:60] if keys else ""
    )

    for key in r.scan_iter(match="*ratelimit*", count=1000):
        r.delete(key)
    r.close()


# =============================================================================
# Injection, XSS, CSRF, open redirect
# =============================================================================

SQL_PAYLOADS = [
    "' OR 1=1 --",
    "'; DROP TABLE production_records; --",
    "1' UNION SELECT null,null,null --",
    "admin'--",
]

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",
]

HOSTILE_REDIRECTS = [
    "//evil.example",
    "/\\evil.example",
    "https://evil.example",
    "/%2f%2fevil.example",
    "javascript:alert(1)",
    "/dashboard\r\nSet-Cookie:%20x=1",
]


def suite_security(users, base, results: Results) -> None:
    """Hostile input, CSRF on a real state change, and redirect containment."""
    settings = get_settings()

    with client_for("ADMIN", users, base) as client:
        baseline = client.get("/production", params={"page_size": 1})
        total_before = baseline.json()["pagination"]["total"]

        for payload in SQL_PAYLOADS:
            for param in ("sort_by", "machine_id"):
                response = client.get("/production", params={param: payload, "page_size": 1})
                results.check(
                    response.status_code in (400, 422),
                    f"SQL payload refused ({param})",
                    f"HTTP {response.status_code} for {payload[:22]!r}",
                )
                lowered = response.text.lower()
                results.check(
                    "traceback" not in lowered
                    and "psycopg" not in lowered
                    and " select " not in lowered,
                    f"no internals leaked ({param}, {payload[:16]!r})",
                )

        after = client.get("/production", params={"page_size": 1}).json()["pagination"]["total"]
        results.check(
            after == total_before,
            "SQL payloads changed no data",
            f"total {total_before} -> {after}",
        )

        for payload in XSS_PAYLOADS:
            response = client.get("/alerts", params={"status": payload, "page_size": 1})
            results.check(
                response.status_code in (400, 422),
                f"XSS payload refused by enum validation: {payload[:24]!r}",
                f"HTTP {response.status_code}",
            )

        response = client.get("/production", params={"page_size": 1})
        results.check(
            response.headers.get("content-type", "").startswith("application/json"),
            "responses are JSON, never HTML",
            response.headers.get("content-type", ""),
        )

    # CSRF, against logout -- a genuine state change.
    with client_for("ADMIN", users, base) as client:
        results.check(
            client.post("/auth/logout").status_code == 403, "CSRF: POST with no token is refused"
        )
        results.check(
            client.post("/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403,
            "CSRF: POST with a wrong token is refused",
        )

        csrf_response = client.get("/auth/csrf")
        if results.check(csrf_response.status_code == 200, "CSRF: token endpoint responds"):
            csrf = csrf_response.json()["data"]["csrf_token"]
            allowed_origin = settings.cors_allowed_origins[0]

            foreign = client.post(
                "/auth/logout", headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}
            )
            results.check(
                foreign.status_code == 403,
                "CSRF: a foreign Origin is refused",
                f"HTTP {foreign.status_code}",
            )

            good = client.post(
                "/auth/logout", headers={"X-CSRF-Token": csrf, "Origin": allowed_origin}
            )
            results.check(
                good.status_code == 200,
                "CSRF: correct token and Origin succeeds",
                f"HTTP {good.status_code}",
            )

    # Open redirect containment on the login entry point.
    with anon_client(base) as client:
        for target in HOSTILE_REDIRECTS:
            response = client.get(
                "/auth/google/login", params={"next": target}, follow_redirects=False
            )
            location = response.headers.get("location", "")
            results.check(
                "evil.example" not in location and "javascript:" not in location,
                f"open redirect blocked: {target[:26]!r}",
                "" if "evil" not in location else f"leaked: {location[:70]}",
            )
            results.check(
                "\r" not in location and "\n" not in location,
                f"no CRLF in Location for {target[:18]!r}",
            )


# =============================================================================
# Pagination
# =============================================================================


def suite_pagination(users, base, results: Results) -> None:
    """First, middle, last and past-the-end pages against real row counts."""
    with client_for("ADMIN", users, base) as client:
        first = client.get("/production", params={"page": 1, "page_size": 25}).json()
        total = first["pagination"]["total"]
        results.check(
            total > 100,
            "pagination: dataset is large enough to matter",
            f"{total} production records",
        )
        results.check(
            len(first["data"]) == 25, "pagination: page 1 is full", f"{len(first['data'])} rows"
        )

        pages = (total + 24) // 25
        middle_no = max(2, pages // 2)
        middle = client.get("/production", params={"page": middle_no, "page_size": 25}).json()
        results.check(
            len(middle["data"]) == 25, "pagination: a middle page is full", f"page {middle_no}"
        )
        results.check(
            middle["pagination"]["total"] == total, "pagination: the total is stable across pages"
        )
        results.check(
            not ({row["id"] for row in first["data"]} & {row["id"] for row in middle["data"]}),
            "pagination: pages do not overlap",
        )

        last = client.get("/production", params={"page": pages, "page_size": 25}).json()
        expected = total - (pages - 1) * 25
        results.check(
            len(last["data"]) == expected,
            "pagination: the last page holds the remainder",
            f"{len(last['data'])} rows, expected {expected}",
        )

        past = client.get("/production", params={"page": pages + 50, "page_size": 25}).json()
        results.check(past["data"] == [], "pagination: past the end is empty")
        results.check(
            past["pagination"]["total"] == total,
            "pagination: the total is still correct past the end",
        )

        machines = client.get("/machines").json()["data"]
        machine = machines[0]
        filtered = client.get(
            "/production", params={"machine_id": machine["id"], "page_size": 25}
        ).json()
        results.check(
            filtered["pagination"]["total"] < total,
            "pagination: a filter narrows the total",
            f"{filtered['pagination']['total']} of {total}",
        )
        results.check(
            all(row["machine_id"] == machine["id"] for row in filtered["data"]),
            "pagination: every filtered row matches the filter",
        )

        over = client.get("/production", params={"page_size": 5000})
        results.check(
            over.status_code == 422,
            "pagination: an oversized page_size is refused",
            f"HTTP {over.status_code}",
        )

        # Sorting must change the order, and only through allow-listed keys.
        asc = client.get(
            "/production", params={"sort_by": "produced", "sort_dir": "asc", "page_size": 5}
        ).json()["data"]
        desc = client.get(
            "/production", params={"sort_by": "produced", "sort_dir": "desc", "page_size": 5}
        ).json()["data"]
        results.check(
            [r["produced_quantity"] for r in asc] == sorted(r["produced_quantity"] for r in asc),
            "sorting: ascending really is ascending",
        )
        results.check(asc[0]["id"] != desc[0]["id"], "sorting: direction changes the result")
        bad_sort = client.get("/production", params={"sort_by": "created_at"})
        results.check(
            bad_sort.status_code in (400, 422),
            "sorting: a non-allow-listed key is refused",
            f"HTTP {bad_sort.status_code}",
        )


SUITES: dict[str, Any] = {
    "contract": suite_contract,
    "rbac": suite_rbac,
    "session": suite_session,
    "cache": suite_cache,
    "ratelimit": suite_ratelimit,
    "security": suite_security,
    "pagination": suite_pagination,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=[*sorted(SUITES), "all"])
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args()

    users = seeded_users()
    results = Results()

    names = sorted(SUITES) if args.suite == "all" else [args.suite]
    for name in names:
        print(f"\n{'=' * 70}\n{name.upper()}\n{'=' * 70}")
        SUITES[name](users, args.base, results)

    return results.summary()


if __name__ == "__main__":
    sys.exit(main())
