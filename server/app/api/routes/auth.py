"""Authentication endpoints (spec sections 3, 13 and 14).

The flow, and where each security control sits:

    GET  /auth/google/login      Authlib generates state, nonce and PKCE
      -> Google
    GET  /auth/google/callback   Authlib validates state, nonce, the code
                                 exchange and the ID token signature
                                 -> account restriction
                                 -> user resolution and role assignment
                                 -> application JWT
                                 -> HttpOnly cookie
                                 -> redirect to an allow-listed destination
    POST /auth/logout            revoke the jti, clear the cookies
    GET  /auth/me                the current session's user

The callback never reads a user id or a role from a query parameter (spec
section 3). The only thing it takes from the URL is the authorization code and
state, both of which Authlib validates before this module sees an identity.
"""

from __future__ import annotations

from typing import Annotated

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.dependencies import AuditServiceDep, AuthServiceDep, RevocationStoreDep
from app.schemas.auth import AuthStatus, CsrfToken, CurrentUser, LogoutResult
from app.schemas.common import Envelope
from app.security.cookies import (
    clear_csrf_cookie,
    clear_session_cookie,
    generate_csrf_token,
    set_csrf_cookie,
    set_session_cookie,
)
from app.security.dependencies import CurrentUserDep, get_token_claims
from app.security.jwt import TokenClaims, issue_access_token
from app.security.oauth import (
    GOOGLE_CLIENT_NAME,
    OAuthIdentityError,
    describe_oauth_error,
    extract_identity,
    is_configured,
)
from app.security.redirects import is_safe_relative_path, resolve_post_login_redirect
from app.services.audit_service import AuditAction
from app.services.auth_service import AuthenticationError
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

#: Query parameter naming where to go after a successful sign-in. Always a
#: path, never a URL -- see `security/redirects.py`.
NEXT_PARAM = "next"


def _context(request: Request) -> dict[str, str | None]:
    """Audit context for an unauthenticated request."""
    client = request.client
    return {
        "request_id": getattr(request.state, "request_id", None),
        "ip_address": client.host if client else None,
        "user_agent": request.headers.get("user-agent", "")[:256] or None,
    }


def _failure_redirect(settings: Settings, reason: str) -> RedirectResponse:
    """Send the browser back to the login page with a reason code.

    The reason is a short opaque code, not a message. It tells the frontend
    which of a handful of copy strings to show, and tells an attacker nothing
    about which check refused them.
    """
    separator = "&" if "?" in settings.frontend_login_failure_url else "?"
    url = f"{settings.frontend_login_failure_url}{separator}reason={reason}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@router.get(
    "/status",
    response_model=Envelope[AuthStatus],
    summary="Authentication availability",
    description=(
        "Reports whether Google sign-in is configured on this deployment.\n\n"
        "Lets the login page render a useful message instead of a button that "
        "leads to an error when credentials are absent. Reports configuration "
        "only -- never a credential or any part of one."
    ),
)
async def auth_status(settings: SettingsDep) -> Envelope[AuthStatus]:
    return Envelope(
        data=AuthStatus(
            authentication_required=True,
            google_configured=is_configured(settings),
            login_url=f"{settings.api_v1_prefix}/auth/google/login",
        )
    )


@router.get(
    "/csrf",
    response_model=Envelope[CsrfToken],
    summary="Obtain a CSRF token",
    description=(
        "Issues a CSRF token, returned in the body and set as a readable "
        "cookie. Echo it in the `X-CSRF-Token` header on every state-changing "
        "request.\n\n"
        "The cookie is deliberately not HttpOnly: the double-submit pattern "
        "requires the frontend to read it. It is not a session secret -- a "
        "cross-site attacker can cause it to be sent but cannot read it."
    ),
)
async def csrf_token(response: Response, settings: SettingsDep) -> Envelope[CsrfToken]:
    token = generate_csrf_token()
    set_csrf_cookie(response, token, settings)
    return Envelope(data=CsrfToken(csrf_token=token))


@router.get(
    "/google/login",
    summary="Begin Google sign-in",
    description=(
        "Redirects to Google's authorization endpoint.\n\n"
        "Authlib generates and stores the OAuth `state`, the OIDC `nonce` and "
        "the PKCE verifier before redirecting; all three are checked on the way "
        "back.\n\n"
        "`next` optionally names where to land afterwards. It must be a path "
        "beginning with `/`; anything else -- an absolute URL, a "
        "scheme-relative `//host`, an encoded slash -- is discarded and the "
        "default destination is used (spec section 21)."
    ),
    responses={
        307: {"description": "Redirect to Google."},
        429: {"description": "Rate limit exceeded."},
        503: {"description": "Google sign-in is not configured on this deployment."},
    },
)
async def google_login(
    request: Request,
    settings: SettingsDep,
    audit: AuditServiceDep,
) -> Response:
    if not is_configured(settings):
        # A development deployment without credentials. Everything else in the
        # API keeps working; only this endpoint reports itself unavailable
        # (spec section 35).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this deployment.",
        )

    # Validated now rather than at the callback, so an unsafe value never
    # reaches the session and cannot be reflected back later. Only the path is
    # stored; the origin is always taken from configuration when it is resolved.
    requested_next = request.query_params.get(NEXT_PARAM)
    if requested_next and is_safe_relative_path(requested_next):
        request.session["post_login_path"] = requested_next

    await audit.login_initiated(**_context(request))

    oauth = request.app.state.oauth
    client = oauth.create_client(GOOGLE_CLIENT_NAME)
    return await client.authorize_redirect(request, settings.google_redirect_uri)


@router.get(
    "/google/callback",
    summary="Google sign-in callback",
    description=(
        "Completes sign-in and redirects to the frontend.\n\n"
        "Authlib validates the `state`, exchanges the authorization code "
        "server-side, and verifies the ID token's signature, issuer, audience, "
        "expiry and `nonce` against Google's published keys. Only then is the "
        "identity used.\n\n"
        "A user id or role is never read from the query string. The role is "
        "resolved from the database or from `AUTH_DEFAULT_ROLE`.\n\n"
        "Every failure redirects to the login page with a short reason code; "
        "the detail goes to the audit trail and the server log."
    ),
    responses={
        303: {"description": "Redirect to the frontend, successful or not."},
        429: {"description": "Rate limit exceeded."},
    },
)
async def google_callback(
    request: Request,
    settings: SettingsDep,
    auth_service: AuthServiceDep,
    audit: AuditServiceDep,
) -> Response:
    if not is_configured(settings):
        return _failure_redirect(settings, "not_configured")

    context = _context(request)
    oauth = request.app.state.oauth
    client = oauth.create_client(GOOGLE_CLIENT_NAME)

    # --- protocol: state, code exchange, ID token verification ---------------
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        reason = describe_oauth_error(exc)
        # An invalid state lands here. It is the CSRF failure case for the
        # callback, and worth its own audit action.
        await audit.record(
            action=AuditAction.OAUTH_CALLBACK_FAILURE,
            resource_type="session",
            success=False,
            metadata={"reason": reason},
            **context,
        )
        logger.warning("auth.oauth_callback_failed", extra={"reason": reason})
        return _failure_redirect(settings, "oauth_failed")
    except Exception as exc:
        await audit.record(
            action=AuditAction.OAUTH_CALLBACK_FAILURE,
            resource_type="session",
            success=False,
            metadata={"reason": type(exc).__name__},
            **context,
        )
        logger.error("auth.oauth_callback_error", exc_info=exc)
        return _failure_redirect(settings, "oauth_failed")

    # --- identity: verified claims only --------------------------------------
    try:
        identity = extract_identity(token)
    except OAuthIdentityError as exc:
        await audit.login_failure(reason=exc.reason, **context)
        return _failure_redirect(settings, "identity_invalid")

    # --- policy: restriction, provisioning, role -----------------------------
    try:
        user = await auth_service.resolve_user(identity, request_context=context)
    except AuthenticationError as exc:
        await audit.login_failure(reason=exc.reason, **context)
        return _failure_redirect(settings, "not_permitted")

    # --- session -------------------------------------------------------------
    access_token, claims = issue_access_token(
        user_id=user.id, role=user.role.value, settings=settings
    )

    # The stored value is a path, and it is validated again here. The session
    # cookie is signed, so tampering is already prevented -- re-validating costs
    # nothing and means a single mistake in session handling could not turn into
    # an open redirect. The origin always comes from configuration.
    stored_path = request.session.pop("post_login_path", None)
    destination = resolve_post_login_redirect(stored_path, settings)

    response = RedirectResponse(url=destination, status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, access_token, settings, max_age_seconds=claims.seconds_remaining)
    set_csrf_cookie(response, generate_csrf_token(), settings)

    # The OAuth transaction is finished; its state and nonce must not linger.
    request.session.clear()

    await audit.login_success(
        user_id=user.id,
        metadata={"role": user.role.value, "provider": "google"},
        **context,
    )
    logger.info(
        "auth.login_success",
        extra={"user_id": str(user.id), "role": user.role.value},
    )
    return response


@router.post(
    "/logout",
    response_model=Envelope[LogoutResult],
    summary="Sign out",
    description=(
        "Revokes the current session and clears its cookies.\n\n"
        "The token's `jti` is added to a Redis denylist with a TTL equal to its "
        "remaining lifetime, so a copy captured earlier stops working "
        "immediately rather than surviving until it expires. The entry expires "
        "with the token, so the denylist stays bounded (spec section 8).\n\n"
        "Idempotent, and always clears the cookies -- including when Redis is "
        "unavailable, in which case `session_revoked` is false and the token "
        "expires on its own shortly."
    ),
    responses={
        401: {"description": "No valid session."},
        403: {"description": "CSRF validation failed."},
    },
)
async def logout(
    request: Request,
    response: Response,
    settings: SettingsDep,
    claims: Annotated[TokenClaims, Depends(get_token_claims)],
    revocation: RevocationStoreDep,
    audit: AuditServiceDep,
) -> Envelope[LogoutResult]:
    revoked = await revocation.revoke(claims.token_id, claims.seconds_remaining)

    # Cleared regardless of whether revocation succeeded: for a cooperating
    # browser this is what actually ends the session.
    clear_session_cookie(response, settings)
    clear_csrf_cookie(response, settings)

    await audit.logout(user_id=claims.subject, revoked=revoked, **_context(request))
    logger.info("auth.logout", extra={"user_id": str(claims.subject), "revoked": revoked})
    return Envelope(data=LogoutResult(logged_out=True, session_revoked=revoked))


@router.get(
    "/me",
    response_model=Envelope[CurrentUser],
    summary="The current user",
    description=(
        "Returns the signed-in user's application identity.\n\n"
        "Safe fields only: id, email, name, role, avatar and active status. "
        "Never a provider token, a signing key or any internal security "
        "metadata (spec section 14).\n\n"
        "`permissions` is included so the frontend can decide what to *offer*. "
        "It is not a grant: every endpoint enforces its own check server-side, "
        "and hiding a button is not authorization."
    ),
    responses={401: {"description": "No valid session, or the account is inactive."}},
)
async def current_user(user: CurrentUserDep) -> Envelope[CurrentUser]:
    return Envelope(
        data=CurrentUser(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            role_label=user.role_label,
            avatar_url=user.avatar_url,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            permissions=user.permissions,
        )
    )
