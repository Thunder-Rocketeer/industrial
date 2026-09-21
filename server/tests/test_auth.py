"""Authentication and authorization tests (spec section 29).

Organised by the thing being defended, not by the module being tested. Each
section corresponds to an attack or a failure mode, so a reader can check that
the defence exists by reading the test names.

Spec section 29 asks that JWT verification is not tested only through mocks:
"Use realistic cryptographic test cases." Every token below is genuinely signed
and genuinely verified. The forged ones are forged with real cryptography -- a
real HMAC under the wrong key, a real `alg: none` token -- so what is being
asserted is that the verifier rejects them, not that a mock returned False.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.cache.client import CacheClient
from app.config import Settings
from app.dependencies import get_audit_service, get_auth_service, get_revocation_store
from app.models.enums import RoleCode
from app.security.cookies import (
    generate_csrf_token,
    read_session_token,
)
from app.security.csrf import CSRF_HEADER
from app.security.jwt import (
    FORBIDDEN_ALGORITHMS,
    SUPPORTED_ALGORITHMS,
    TokenConfigurationError,
    TokenError,
    TokenExpiredError,
    decode_access_token,
    issue_access_token,
)
from app.security.policy import (
    Permission,
    UnknownRoleError,
    has_permission,
    permissions_for,
    roles_with,
)
from app.security.redirects import is_safe_relative_path, resolve_post_login_redirect
from app.security.revocation import TokenRevocationStore
from app.services.auth_service import AuthenticationError, AuthService
from tests import fakes
from tests.test_cache import FakeRedis

API = "/api/v1"
UTC = timezone.utc

#: A signing key long enough to be realistic. Never a real one.
TEST_SECRET = "t" * 64


@pytest.fixture
def auth_settings() -> Settings:
    """Settings with a usable signing key.

    Deliberately not named `settings`: conftest defines a session-scoped
    `settings` that the session-scoped `app` fixture depends on, and shadowing
    it with a function-scoped one is a scope mismatch.
    """
    return Settings(secret_key=TEST_SECRET, _env_file=None)


def _frontend_origin(settings: Settings) -> str:
    """The scheme and host the post-login redirect must land on."""
    parts = urlsplit(settings.frontend_login_success_url)
    return f"{parts.scheme}://{parts.netloc}"


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


# =============================================================================
# JWT: issuing and the happy path
# =============================================================================


def test_a_token_round_trips(auth_settings: Settings, user_id: uuid.UUID) -> None:
    token, claims = issue_access_token(user_id=user_id, role="ADMIN", settings=auth_settings)
    decoded = decode_access_token(token, auth_settings)

    assert decoded.subject == user_id
    assert decoded.role == "ADMIN"
    assert decoded.token_id == claims.token_id


def test_claims_are_minimal(auth_settings: Settings, user_id: uuid.UUID) -> None:
    """Spec section 6: no sensitive information in JWT claims.

    A JWT is signed, not encrypted. Anyone holding it can read every claim, so
    the test asserts on what is *absent*: no email, no name, no provider token.
    """
    token, _ = issue_access_token(user_id=user_id, role="VIEWER", settings=auth_settings)
    payload = pyjwt.decode(
        token, TEST_SECRET, algorithms=["HS256"], audience=auth_settings.jwt_audience
    )

    assert set(payload) == {"sub", "iss", "aud", "iat", "exp", "jti", "typ", "role"}
    for forbidden in ("email", "name", "picture", "access_token", "id_token"):
        assert forbidden not in payload


def test_each_token_has_a_unique_id(auth_settings: Settings, user_id: uuid.UUID) -> None:
    """`jti` must be unique, or revoking one session would revoke another."""
    first, _ = issue_access_token(user_id=user_id, role="ADMIN", settings=auth_settings)
    second, _ = issue_access_token(user_id=user_id, role="ADMIN", settings=auth_settings)

    assert decode_access_token(first, auth_settings).token_id != (
        decode_access_token(second, auth_settings).token_id
    )


def test_token_lifetime_matches_configuration(user_id: uuid.UUID) -> None:
    short_lived = Settings(secret_key=TEST_SECRET, access_token_expire_minutes=10, _env_file=None)
    _, claims = issue_access_token(user_id=user_id, role="ADMIN", settings=short_lived)

    lifetime = (claims.expires_at - claims.issued_at).total_seconds()
    assert lifetime == pytest.approx(600, abs=1)


def test_the_configured_lifetime_is_bounded() -> None:
    """Spec section 55.3: access tokens must stay short-lived."""
    with pytest.raises(Exception, match="less than or equal to 60"):
        Settings(secret_key=TEST_SECRET, access_token_expire_minutes=1440, _env_file=None)


# =============================================================================
# JWT: forgery and algorithm attacks (spec section 32)
# =============================================================================


@pytest.mark.security
def test_an_alg_none_token_is_rejected(auth_settings: Settings, user_id: uuid.UUID) -> None:
    """The classic attack: ask the verifier to skip signature checking.

    A genuine unsigned token, constructed with a real JWT library. It must be
    rejected because the decoder is given an explicit algorithm list and never
    reads the token's own `alg` header.
    """
    forged = pyjwt.encode(
        {
            "sub": str(user_id),
            "iss": auth_settings.jwt_issuer,
            "aud": auth_settings.jwt_audience,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "jti": "forged",
            "typ": "access",
            "role": "ADMIN",
        },
        key="",
        algorithm="none",
    )

    with pytest.raises(TokenError):
        decode_access_token(forged, auth_settings)


@pytest.mark.security
def test_none_can_never_be_configured_as_the_algorithm(auth_settings: Settings) -> None:
    """Even a deliberate misconfiguration is refused."""
    for algorithm in FORBIDDEN_ALGORITHMS:
        bad = Settings(secret_key=TEST_SECRET, jwt_algorithm=algorithm, _env_file=None)
        with pytest.raises(TokenConfigurationError):
            issue_access_token(user_id=uuid.uuid4(), role="ADMIN", settings=bad)


@pytest.mark.security
def test_an_unsupported_algorithm_is_refused() -> None:
    bad = Settings(secret_key=TEST_SECRET, jwt_algorithm="HS1", _env_file=None)
    with pytest.raises(TokenConfigurationError, match="not supported"):
        issue_access_token(user_id=uuid.uuid4(), role="ADMIN", settings=bad)


@pytest.mark.security
def test_supported_algorithms_exclude_none() -> None:
    assert "none" not in SUPPORTED_ALGORITHMS
    assert frozenset() == FORBIDDEN_ALGORITHMS & SUPPORTED_ALGORITHMS


@pytest.mark.security
def test_a_token_signed_with_another_key_is_rejected(
    auth_settings: Settings, user_id: uuid.UUID
) -> None:
    """Real HMAC, wrong key. The signature genuinely does not verify."""
    attacker = Settings(secret_key="a" * 64, _env_file=None)
    forged, _ = issue_access_token(user_id=user_id, role="ADMIN", settings=attacker)

    with pytest.raises(TokenError):
        decode_access_token(forged, auth_settings)


@pytest.mark.security
def test_a_tampered_payload_is_rejected(auth_settings: Settings, user_id: uuid.UUID) -> None:
    """Editing a claim invalidates the signature.

    The role is swapped from VIEWER to ADMIN in the encoded payload, which is
    exactly the privilege escalation the signature exists to prevent.
    """
    import base64
    import json

    token, _ = issue_access_token(user_id=user_id, role="VIEWER", settings=auth_settings)
    header, payload, signature = token.split(".")

    decoded = json.loads(base64.urlsafe_b64decode(payload + "=="))
    decoded["role"] = "ADMIN"
    tampered_payload = base64.urlsafe_b64encode(json.dumps(decoded).encode()).rstrip(b"=").decode()

    with pytest.raises(TokenError):
        decode_access_token(f"{header}.{tampered_payload}.{signature}", auth_settings)


@pytest.mark.security
def test_a_token_from_another_issuer_is_rejected(user_id: uuid.UUID) -> None:
    ours = Settings(secret_key=TEST_SECRET, _env_file=None)
    theirs = Settings(secret_key=TEST_SECRET, jwt_issuer="other-app", _env_file=None)
    foreign, _ = issue_access_token(user_id=user_id, role="ADMIN", settings=theirs)

    with pytest.raises(TokenError):
        decode_access_token(foreign, ours)


@pytest.mark.security
def test_a_token_for_another_audience_is_rejected(user_id: uuid.UUID) -> None:
    """Stops a token minted for a sibling service being replayed at this one."""
    ours = Settings(secret_key=TEST_SECRET, _env_file=None)
    theirs = Settings(secret_key=TEST_SECRET, jwt_audience="other-api", _env_file=None)
    foreign, _ = issue_access_token(user_id=user_id, role="ADMIN", settings=theirs)

    with pytest.raises(TokenError):
        decode_access_token(foreign, ours)


@pytest.mark.security
def test_an_expired_token_is_rejected(auth_settings: Settings, user_id: uuid.UUID) -> None:
    issued = datetime.now(tz=UTC) - timedelta(hours=2)
    token, _ = issue_access_token(
        user_id=user_id, role="ADMIN", settings=auth_settings, issued_at=issued
    )

    with pytest.raises(TokenExpiredError):
        decode_access_token(token, auth_settings)


@pytest.mark.security
@pytest.mark.parametrize("claim", ["sub", "iss", "aud", "exp", "iat", "jti", "typ"])
def test_a_token_missing_a_required_claim_is_rejected(
    auth_settings: Settings, user_id: uuid.UUID, claim: str
) -> None:
    payload = {
        "sub": str(user_id),
        "iss": auth_settings.jwt_issuer,
        "aud": auth_settings.jwt_audience,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": "abc",
        "typ": "access",
        "role": "ADMIN",
    }
    payload.pop(claim)
    token = pyjwt.encode(payload, TEST_SECRET, algorithm="HS256")

    with pytest.raises(TokenError):
        decode_access_token(token, auth_settings)


@pytest.mark.security
def test_a_token_of_the_wrong_type_is_rejected(auth_settings: Settings, user_id: uuid.UUID) -> None:
    """A token minted for one purpose must not be usable for another."""
    token = pyjwt.encode(
        {
            "sub": str(user_id),
            "iss": auth_settings.jwt_issuer,
            "aud": auth_settings.jwt_audience,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "jti": "abc",
            "typ": "refresh",
            "role": "ADMIN",
        },
        TEST_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(TokenError):
        decode_access_token(token, auth_settings)


@pytest.mark.security
@pytest.mark.parametrize("token", ["", "   ", "not-a-token", "a.b", "a.b.c.d", "....", "null"])
def test_a_malformed_token_is_rejected(auth_settings: Settings, token: str) -> None:
    with pytest.raises(TokenError):
        decode_access_token(token, auth_settings)


@pytest.mark.security
def test_a_token_with_a_forged_subject_is_rejected(auth_settings: Settings) -> None:
    """A `sub` that is not a UUID cannot identify a user."""
    token = pyjwt.encode(
        {
            "sub": "'; DROP TABLE users; --",
            "iss": auth_settings.jwt_issuer,
            "aud": auth_settings.jwt_audience,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "jti": "abc",
            "typ": "access",
            "role": "ADMIN",
        },
        TEST_SECRET,
        algorithm="HS256",
    )

    with pytest.raises(TokenError):
        decode_access_token(token, auth_settings)


@pytest.mark.security
def test_signing_without_a_secret_is_refused() -> None:
    """An empty key would produce tokens anyone could forge."""
    with pytest.raises(TokenConfigurationError, match="SECRET_KEY"):
        issue_access_token(
            user_id=uuid.uuid4(), role="ADMIN", settings=Settings(secret_key="", _env_file=None)
        )


# =============================================================================
# Revocation (spec section 8)
# =============================================================================


async def test_a_revoked_token_is_reported_as_revoked() -> None:
    store = TokenRevocationStore(CacheClient(FakeRedis()))

    assert await store.is_revoked("abc") is False
    await store.revoke("abc", ttl_seconds=900)
    assert await store.is_revoked("abc") is True


async def test_revocation_entries_expire_with_the_token() -> None:
    """Spec section 8: no unbounded permanent blacklist."""
    redis = FakeRedis()
    store = TokenRevocationStore(CacheClient(redis))

    await store.revoke("abc", ttl_seconds=900)

    key = next(k for k in redis.store if "abc" in k)
    assert redis.expiries[key] == 900


async def test_revoking_an_already_expired_token_is_a_no_op() -> None:
    redis = FakeRedis()
    store = TokenRevocationStore(CacheClient(redis))

    assert await store.revoke("abc", ttl_seconds=0) is True
    assert redis.store == {}


@pytest.mark.security
async def test_revocation_fails_open_when_redis_is_down() -> None:
    """The documented trade-off, asserted so it cannot change silently.

    A revoked token stays usable for at most its remaining lifetime during a
    Redis outage. The alternative -- rejecting every request -- would turn a
    cache outage into a total outage. See the module docstring in
    `security/revocation.py`.
    """
    store = TokenRevocationStore(CacheClient(FakeRedis(fail=True)))

    assert await store.is_revoked("abc") is False
    assert await store.revoke("abc", ttl_seconds=900) is False


# =============================================================================
# RBAC (spec section 12)
# =============================================================================


def test_admin_holds_every_permission() -> None:
    assert permissions_for(RoleCode.ADMIN) == frozenset(Permission)


def test_viewer_is_read_only_and_narrow() -> None:
    """A Viewer sees the dashboard and analytics. Nothing operational."""
    granted = permissions_for(RoleCode.VIEWER)

    assert Permission.DASHBOARD_READ in granted
    assert Permission.ANALYTICS_READ in granted
    assert Permission.PRODUCTION_READ not in granted
    assert Permission.INVENTORY_READ not in granted
    assert not any(p.value.endswith(":write") for p in granted)


def test_every_role_is_in_the_matrix() -> None:
    """A role in the database with no matrix entry would deny everything."""
    for role in RoleCode:
        assert permissions_for(role) is not None


def test_specialist_roles_do_not_see_each_others_domains() -> None:
    """The point of having roles at all."""
    assert not has_permission(RoleCode.QUALITY_ENGINEER, Permission.INVENTORY_READ)
    assert not has_permission(RoleCode.INVENTORY_MANAGER, Permission.QUALITY_READ)
    assert not has_permission(RoleCode.PRODUCTION_SUPERVISOR, Permission.INVENTORY_READ)


def test_every_role_can_read_the_dashboard() -> None:
    """Spec section 56 defines each role as "Viewer + ...", and Viewer is this."""
    for role in RoleCode:
        assert has_permission(role, Permission.DASHBOARD_READ)


def test_only_admin_can_administer_users() -> None:
    assert roles_with(Permission.USERS_WRITE) == frozenset({RoleCode.ADMIN})
    assert roles_with(Permission.AUDIT_READ) == frozenset({RoleCode.ADMIN})


def test_an_unknown_role_raises_rather_than_denying_silently() -> None:
    """A deployment fault should be loud, not a confusing 403 for one group."""
    with pytest.raises(UnknownRoleError):
        permissions_for("SUPER_ADMIN")


def test_quality_engineers_can_read_machines() -> None:
    """A defect is attributed to the machine that produced the part."""
    assert has_permission(RoleCode.QUALITY_ENGINEER, Permission.MACHINES_READ)


# =============================================================================
# Route protection, end to end
# =============================================================================

PROTECTED_ENDPOINTS = [
    "/dashboard/summary",
    "/production",
    "/quality",
    "/inventory",
    "/machines",
    "/analytics/oee",
    "/alerts",
    "/maintenance",
    "/auth/me",
]

PUBLIC_ENDPOINTS = ["/health", "/health/live", "/health/ready", "/auth/status", "/auth/csrf"]


@pytest.mark.security
@pytest.mark.parametrize("endpoint", PROTECTED_ENDPOINTS)
def test_a_protected_endpoint_requires_a_session(client: TestClient, endpoint: str) -> None:
    response = client.get(f"{API}{endpoint}")

    assert response.status_code == 401, f"{endpoint} is not protected."
    assert response.json()["error"]["code"] == "missing_token"


@pytest.mark.parametrize("endpoint", PUBLIC_ENDPOINTS)
def test_a_public_endpoint_needs_no_session(client: TestClient, endpoint: str) -> None:
    """Spec section 13: health and the auth entry points stay public.

    Readiness returns 503 without a database, which is a report rather than a
    rejection -- what matters is that it is not a 401.
    """
    assert client.get(f"{API}{endpoint}").status_code in (200, 503)


@pytest.mark.security
def test_a_garbage_cookie_is_a_401_not_a_500(client: TestClient) -> None:
    client.cookies.set("acf_session", "not.a.jwt")
    response = client.get(f"{API}/dashboard/summary")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.security
def test_a_401_carries_an_authentication_challenge(client: TestClient) -> None:
    """Lets the frontend tell an auth failure from an authorization one."""
    response = client.get(f"{API}/dashboard/summary")

    assert "WWW-Authenticate" in response.headers


# =============================================================================
# Authorization, end to end: the forbidden path
# =============================================================================


@pytest.fixture
def as_role(app):
    """Sign in as a given role, without faking the service layer."""

    def _install(role: RoleCode):
        from app.security.dependencies import get_current_user

        app.dependency_overrides[get_current_user] = lambda: fakes.make_user(role)
        app.dependency_overrides[get_audit_service] = lambda: fakes.FakeAuditService()
        return app.dependency_overrides

    yield _install
    app.dependency_overrides.clear()


@pytest.mark.security
@pytest.mark.parametrize(
    ("role", "endpoint"),
    [
        (RoleCode.VIEWER, "/production"),
        (RoleCode.VIEWER, "/inventory"),
        (RoleCode.VIEWER, "/quality"),
        (RoleCode.VIEWER, "/machines"),
        (RoleCode.QUALITY_ENGINEER, "/inventory"),
        (RoleCode.INVENTORY_MANAGER, "/quality"),
        (RoleCode.INVENTORY_MANAGER, "/production"),
        (RoleCode.PRODUCTION_SUPERVISOR, "/inventory"),
    ],
)
def test_a_role_without_the_permission_gets_403(
    client: TestClient, as_role, role: RoleCode, endpoint: str
) -> None:
    """403, not 401: the session is valid, the permission is not held.

    The distinction matters to the frontend. A 401 means "sign in"; a 403 means
    "signing in again will not help". Confusing them produces an infinite
    redirect loop between a valid session and a page it cannot see.
    """
    as_role(role)
    response = client.get(f"{API}{endpoint}")

    assert response.status_code == 403, f"{role.value} should not reach {endpoint}"
    assert "permission" in response.json()["error"]["message"].lower()


@pytest.mark.security
@pytest.mark.parametrize(
    ("role", "endpoint"),
    [
        (RoleCode.VIEWER, "/dashboard/summary"),
        (RoleCode.VIEWER, "/analytics/oee"),
        (RoleCode.VIEWER, "/alerts"),
        (RoleCode.QUALITY_ENGINEER, "/quality"),
        (RoleCode.INVENTORY_MANAGER, "/inventory"),
        (RoleCode.PRODUCTION_SUPERVISOR, "/production"),
        (RoleCode.FACTORY_MANAGER, "/inventory"),
    ],
)
def test_a_role_with_the_permission_passes_authorization(
    client: TestClient, as_role, role: RoleCode, endpoint: str
) -> None:
    """Authorization allows the request through.

    It then reaches the database, which is absent in tests -- so a 503 means
    authorization passed. Anything but 401 or 403 proves the permission held.
    """
    as_role(role)
    response = client.get(f"{API}{endpoint}")

    assert response.status_code not in (401, 403), (
        f"{role.value} should reach {endpoint}, got {response.status_code}"
    )


# =============================================================================
# Account restriction (spec section 28)
# =============================================================================


def _auth_service(**overrides) -> AuthService:
    """An AuthService with no database, for testing policy in isolation.

    `is_email_permitted` reads only configuration, so the repository and audit
    collaborators are genuinely unused here.
    """
    configured = Settings(secret_key=TEST_SECRET, _env_file=None, **overrides)
    return AuthService(repository=None, audit=None, settings=configured)  # type: ignore[arg-type]


@pytest.mark.security
def test_any_account_is_permitted_when_no_restriction_is_configured() -> None:
    service = _auth_service()
    assert service.is_email_permitted("anyone@anywhere.example") is True


@pytest.mark.security
def test_a_domain_allow_list_is_enforced() -> None:
    service = _auth_service(auth_allowed_email_domains="factory.local")

    assert service.is_email_permitted("manager@factory.local") is True
    assert service.is_email_permitted("attacker@evil.example") is False


@pytest.mark.security
def test_an_email_allow_list_is_enforced() -> None:
    service = _auth_service(auth_allowed_emails="admin@factory.local")

    assert service.is_email_permitted("admin@factory.local") is True
    assert service.is_email_permitted("other@factory.local") is False


@pytest.mark.security
def test_the_allow_list_is_case_insensitive() -> None:
    """Google returns the address as typed; the mailbox is the same either way."""
    service = _auth_service(auth_allowed_email_domains="Factory.LOCAL")

    assert service.is_email_permitted("Manager@Factory.Local") is True


@pytest.mark.security
@pytest.mark.parametrize(
    "email",
    [
        "attacker@evil.example",
        "attacker@factory.local.evil.example",
        "attacker+factory.local@evil.example",
        "attacker@evil.example?factory.local",
        "factory.local@evil.example",
    ],
)
def test_a_domain_allow_list_cannot_be_spoofed(email: str) -> None:
    """The domain is what follows the *last* `@`, never a substring match.

    Every address here contains `factory.local` somewhere. A naive `in` check
    would admit all of them.
    """
    service = _auth_service(auth_allowed_email_domains="factory.local")

    assert service.is_email_permitted(email) is False


# =============================================================================
# Open redirect (spec section 21)
# =============================================================================


@pytest.mark.security
@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example",
        "http://evil.example",
        "//evil.example",
        "///evil.example",
        "/\\evil.example",
        "\\\\evil.example",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "/%2f%2fevil.example",
        "/%2F%2Fevil.example",
        "/path\r\nLocation: https://evil.example",
        "about:blank",
        "//evil.example/%2e%2e",
    ],
)
def test_an_open_redirect_attempt_is_refused(target: str, auth_settings: Settings) -> None:
    assert is_safe_relative_path(target) is False
    assert resolve_post_login_redirect(target, auth_settings) == (
        auth_settings.frontend_login_success_url
    )


@pytest.mark.security
@pytest.mark.parametrize(
    "target", ["/dashboard", "/production?line=A", "/quality#pareto", "/machines/abc"]
)
def test_a_legitimate_path_is_accepted(target: str, auth_settings: Settings) -> None:
    resolved = resolve_post_login_redirect(target, auth_settings)
    assert resolved.startswith(_frontend_origin(auth_settings))

    assert resolved.endswith(target)


@pytest.mark.security
def test_the_redirect_origin_always_comes_from_configuration(
    auth_settings: Settings,
) -> None:
    """A caller supplies a path; the origin is never theirs to choose."""
    assert resolve_post_login_redirect("/anything", auth_settings).startswith(
        _frontend_origin(auth_settings)
    )


@pytest.mark.security
def test_an_over_long_redirect_is_refused() -> None:
    assert is_safe_relative_path("/" + "a" * 1000) is False


# =============================================================================
# Cookies (spec sections 7 and 55.4)
# =============================================================================


def test_the_session_cookie_is_http_only(client: TestClient) -> None:
    """Spec section 55.4: unreadable from JavaScript, so XSS cannot steal it."""
    from fastapi import Response

    from app.security.cookies import set_session_cookie

    response = Response()
    set_session_cookie(response, "token-value", Settings(_env_file=None))
    header = response.headers["set-cookie"]

    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Path=/" in header


def test_the_session_cookie_is_secure_in_production() -> None:
    from fastapi import Response

    from app.security.cookies import set_session_cookie

    response = Response()
    set_session_cookie(response, "token-value", Settings(cookie_secure=True, _env_file=None))

    assert "Secure" in response.headers["set-cookie"]


def test_the_csrf_cookie_is_readable_by_javascript() -> None:
    """Deliberately not HttpOnly: double-submit requires the frontend to read it.

    It is not a session secret. A cross-site attacker can cause it to be sent
    but cannot read it, which is what makes the pattern work.
    """
    from fastapi import Response

    from app.security.cookies import set_csrf_cookie

    response = Response()
    set_csrf_cookie(response, "csrf-value", Settings(_env_file=None))

    assert "HttpOnly" not in response.headers["set-cookie"]


def test_csrf_tokens_are_unpredictable() -> None:
    tokens = {generate_csrf_token() for _ in range(100)}

    assert len(tokens) == 100
    assert all(len(token) >= 32 for token in tokens)


def test_the_token_is_read_only_from_the_cookie(auth_settings: Settings) -> None:
    """One accepted location, so there is one code path to secure."""
    assert read_session_token({"acf_session": "abc"}, auth_settings) == "abc"
    assert read_session_token({"acf_session": "   "}, auth_settings) is None
    assert read_session_token({}, auth_settings) is None


# =============================================================================
# CSRF (spec sections 10 and 59)
# =============================================================================


@pytest.mark.security
def test_logout_without_a_session_is_401(client: TestClient) -> None:
    assert client.post(f"{API}/auth/logout").status_code == 401


@pytest.mark.security
def test_a_state_changing_request_with_a_session_needs_csrf(
    client: TestClient,
    settings,
) -> None:
    """A cookie alone is not enough for an unsafe method.

    This is the cross-site form post: the browser attaches the session cookie
    automatically, so without a second factor the request would be indis-
    tinguishable from a deliberate one.
    """
    token, _ = issue_access_token(user_id=uuid.uuid4(), role="ADMIN", settings=settings)
    client.cookies.set("acf_session", token)

    response = client.post(f"{API}/auth/logout")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


@pytest.mark.security
def test_a_mismatched_csrf_token_is_refused(
    client: TestClient,
    settings,
) -> None:
    token, _ = issue_access_token(user_id=uuid.uuid4(), role="ADMIN", settings=settings)
    client.cookies.set("acf_session", token)
    client.cookies.set("acf_csrf", "the-real-token")

    response = client.post(
        f"{API}/auth/logout",
        headers={"Origin": "http://localhost:3000", CSRF_HEADER: "a-different-token"},
    )

    assert response.status_code == 403


@pytest.mark.security
def test_a_cross_site_origin_is_refused(
    client: TestClient,
    settings,
) -> None:
    token, _ = issue_access_token(user_id=uuid.uuid4(), role="ADMIN", settings=settings)
    client.cookies.set("acf_session", token)
    client.cookies.set("acf_csrf", "matching")

    response = client.post(
        f"{API}/auth/logout",
        headers={"Origin": "https://evil.example", CSRF_HEADER: "matching"},
    )

    assert response.status_code == 403


@pytest.mark.security
def test_safe_methods_need_no_csrf_token(client: TestClient) -> None:
    """GET changes nothing, so requiring a token would reject valid reads."""
    assert client.get(f"{API}/health").status_code == 200


@pytest.mark.security
def test_the_oauth_callback_is_csrf_exempt_by_design() -> None:
    """It is a navigation from Google, protected by the OAuth `state` instead.

    Asserted so the exemption is a documented decision rather than an oversight
    someone discovers later.
    """
    from app.security.csrf import CSRF_EXEMPT_PATH_SUFFIXES

    assert "/auth/google/callback" in CSRF_EXEMPT_PATH_SUFFIXES


# =============================================================================
# Endpoint behaviour
# =============================================================================


def test_auth_status_reports_configuration_without_credentials(
    client: TestClient,
) -> None:
    payload = client.get(f"{API}/auth/status").json()["data"]

    assert payload["authentication_required"] is True
    assert payload["google_configured"] is False
    assert payload["login_url"].endswith("/auth/google/login")


def test_the_csrf_endpoint_issues_a_token_and_a_cookie(client: TestClient) -> None:
    response = client.get(f"{API}/auth/csrf")

    assert response.status_code == 200
    assert response.json()["data"]["csrf_token"]
    assert "acf_csrf" in response.headers["set-cookie"]


def test_me_returns_only_safe_fields(client: TestClient, as_role) -> None:
    """Spec section 14: never a provider token, a key or internal metadata."""
    as_role(RoleCode.FACTORY_MANAGER)
    payload = client.get(f"{API}/auth/me").json()["data"]

    assert set(payload) == {
        "id",
        "email",
        "name",
        "role",
        "role_label",
        "avatar_url",
        "is_active",
        "last_login_at",
        "permissions",
    }
    assert payload["role"] == "FACTORY_MANAGER"
    assert payload["role_label"] == "Factory Manager"


@pytest.mark.security
def test_me_never_leaks_a_credential(client: TestClient, as_role) -> None:
    as_role(RoleCode.ADMIN)
    body = client.get(f"{API}/auth/me").text.lower()

    for forbidden in (
        "client_secret",
        "secret_key",
        "access_token",
        "refresh_token",
        "id_token",
        "provider_subject",
        "password",
    ):
        assert forbidden not in body


def test_me_reports_permissions_for_the_ui(client: TestClient, as_role) -> None:
    """A convenience for hiding buttons, never a grant."""
    as_role(RoleCode.VIEWER)
    payload = client.get(f"{API}/auth/me").json()["data"]

    assert "dashboard:read" in payload["permissions"]
    assert "production:read" not in payload["permissions"]


def test_login_is_unavailable_without_google_credentials(client: TestClient) -> None:
    """Spec section 35: fail gracefully rather than crashing other endpoints."""
    response = client.get(f"{API}/auth/google/login", follow_redirects=False)

    assert response.status_code == 503
    # Everything else still works.
    assert client.get(f"{API}/health").status_code == 200
    assert client.get(f"{API}/auth/status").status_code == 200


# =============================================================================
# Inactive users (spec section 23)
# =============================================================================


@pytest.mark.security
def test_a_deactivated_user_is_rejected_with_a_valid_token(
    client: TestClient,
    app,
    settings,
) -> None:
    """A token that still verifies must not admit a disabled account.

    `load_active_user` returns None for an inactive user, and the dependency
    turns that into a 401 -- the session is no longer usable, so the client
    should clear it rather than retry.
    """

    class InactiveAuthService:
        async def load_active_user(self, user_id):
            return None

    # Signed with the application's own key: a token signed with this module's
    # TEST_SECRET would be rejected for a bad signature, and the test would pass
    # for the wrong reason.
    token, _ = issue_access_token(user_id=uuid.uuid4(), role="ADMIN", settings=settings)
    app.dependency_overrides[get_auth_service] = lambda: InactiveAuthService()
    app.dependency_overrides[get_audit_service] = lambda: fakes.FakeAuditService()
    app.dependency_overrides[get_revocation_store] = lambda: fakes.FakeRevocationStore()
    client.cookies.set("acf_session", token)

    try:
        response = client.get(f"{API}/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "account_unavailable"


@pytest.mark.security
def test_a_revoked_token_is_rejected_end_to_end(
    client: TestClient,
    app,
    settings,
) -> None:
    """Logout must actually end the session, not merely clear the cookie."""
    token, claims = issue_access_token(user_id=uuid.uuid4(), role="ADMIN", settings=settings)

    revocation = fakes.FakeRevocationStore()
    revocation.revoked.add(claims.token_id)

    class ActiveAuthService:
        async def load_active_user(self, user_id):
            return fakes.make_user(RoleCode.ADMIN)

    app.dependency_overrides[get_auth_service] = lambda: ActiveAuthService()
    app.dependency_overrides[get_audit_service] = lambda: fakes.FakeAuditService()
    app.dependency_overrides[get_revocation_store] = lambda: revocation
    client.cookies.set("acf_session", token)

    try:
        response = client.get(f"{API}/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_revoked"


def test_an_authentication_error_carries_a_safe_message() -> None:
    """The client is never told which rule refused them."""
    error = AuthenticationError("email_not_permitted")

    assert error.reason == "email_not_permitted"
    assert "not successful" in error.message.lower()
