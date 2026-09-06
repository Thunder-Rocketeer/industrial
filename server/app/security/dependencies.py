"""Authentication and authorization dependencies (spec sections 11 and 12).

The protected request flow from spec section 11, in one place:

    Request -> cookie -> JWT validation -> revocation -> user lookup
            -> active check -> authorization -> route

Spec section 11 requires that JWT parsing is not duplicated across routes. It
appears exactly once, in `get_current_user`. Everything else composes on top of
that, so there is one implementation to review and one place a mistake could be
made.

401 VERSUS 403, AND WHY IT MATTERS

Spec section 23 asks for the distinction explicitly:

  * **401** -- authentication is absent, malformed, expired or revoked. The
    client's move is to sign in. The frontend acts on this automatically.
  * **403** -- authentication succeeded and the user is not permitted. Signing
    in again changes nothing, so the frontend must *not* redirect to login:
    doing so produces an infinite loop between a valid session and a page it
    cannot see.

A deactivated user gets 401, not 403. Their session is no longer valid at all,
and the correct client behaviour is to clear it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.dependencies import AuditServiceDep, AuthServiceDep, RevocationStoreDep
from app.security.cookies import read_session_token
from app.security.jwt import (
    TokenClaims,
    TokenConfigurationError,
    TokenError,
    TokenExpiredError,
    decode_access_token,
)
from app.security.policy import Permission, UnknownRoleError, has_permission
from app.services.auth_service import AuthenticatedUser
from app.utils.logging import get_logger

logger = get_logger(__name__)

#: Sent on every 401 so a client can tell an authentication failure from an
#: authorization one without parsing the body.
_AUTH_CHALLENGE = {"WWW-Authenticate": 'Cookie realm="acf-dashboard"'}


def _unauthorized(code: str, message: str) -> HTTPException:
    """Build a 401 carrying a stable code.

    The code lets the frontend distinguish "expired, refresh quietly" from
    "never authenticated, show the login page" without string-matching.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={**_AUTH_CHALLENGE, "X-Auth-Error": code},
    )


def _request_context(request: Request) -> dict[str, str | None]:
    """Audit context available on any request.

    The client address is recorded because an audit trail without one cannot
    answer "where did this come from". Headers that could carry a credential are
    never touched.
    """
    client = request.client
    return {
        "request_id": getattr(request.state, "request_id", None),
        "ip_address": client.host if client else None,
        "user_agent": request.headers.get("user-agent", "")[:256] or None,
    }


async def get_token_claims(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenClaims:
    """Extract and validate the access token. The only place this happens.

    Raises:
        HTTPException: 401 for any token problem, 500 for a server
            misconfiguration -- telling a user to sign in again when the server
            has no signing key would loop them forever.
    """
    token = read_session_token(request.cookies, settings)
    if token is None:
        raise _unauthorized("missing_token", "Authentication is required.")

    try:
        claims = decode_access_token(token, settings)
    except TokenExpiredError as exc:
        raise _unauthorized(exc.code, exc.message) from exc
    except TokenError as exc:
        # Logged with the reason for an operator; the client is told only that
        # the session is invalid.
        logger.warning(
            "auth.token_rejected",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "path": request.url.path,
                "reason": type(exc).__name__,
            },
        )
        raise _unauthorized(exc.code, exc.message) from exc
    except TokenConfigurationError as exc:
        logger.error(
            "auth.configuration_error",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication is not correctly configured on the server.",
        ) from exc

    # Store for the rate limiter, which prefers a user bucket over an IP one so
    # colleagues behind one NAT are not throttled by each other.
    request.state.user_id = str(claims.subject)
    return claims


async def get_current_user(
    request: Request,
    claims: Annotated[TokenClaims, Depends(get_token_claims)],
    auth_service: AuthServiceDep,
    audit: AuditServiceDep,
    revocation: RevocationStoreDep,
) -> AuthenticatedUser:
    """Resolve the authenticated, active user behind a request.

    Runs the remaining three steps of the flow: revocation, user lookup, and the
    active check. Each is a separate rejection reason in the log and one 401 to
    the client.

    Raises:
        HTTPException: 401 if the session is revoked, the user no longer exists,
            or the account has been deactivated.
    """
    context = _request_context(request)

    if await revocation.is_revoked(claims.token_id):
        await audit.unauthorized(reason="token_revoked", path=request.url.path, **context)
        raise _unauthorized("token_revoked", "Your session has been ended.")

    user = await auth_service.load_active_user(claims.subject)

    if user is None:
        # Either the user was deleted or deactivated. Both are 401: the session
        # is no longer usable, and the client should clear it.
        await audit.unauthorized(
            reason="user_inactive_or_missing", path=request.url.path, **context
        )
        raise _unauthorized(
            "account_unavailable",
            "This account is no longer active. Please contact an administrator.",
        )

    # The role in the token is a cached copy. The database is authoritative, so
    # a role change takes effect on the next request rather than at token
    # expiry -- the opposite trade to the one the token claim implies, and the
    # safer one, since we already pay for the user lookup.
    request.state.user_role = user.role.value
    return user


CurrentUserDep = Annotated[AuthenticatedUser, Depends(get_current_user)]
"""Injects the authenticated, active user. Any route using it is protected."""


def require_permission(
    permission: Permission,
) -> Callable[..., Awaitable[AuthenticatedUser]]:
    """Build a dependency requiring one permission.

    Used as a router-level dependency so an entire domain is protected by one
    declaration, and a new endpoint added to that router inherits the
    protection rather than being unguarded until someone remembers.

    Routes name a *permission*, never a role. Which roles hold it is decided by
    the matrix in `security/policy.py` (spec section 12).
    """

    async def dependency(
        request: Request, user: CurrentUserDep, audit: AuditServiceDep
    ) -> AuthenticatedUser:
        try:
            permitted = has_permission(user.role, permission)
        except UnknownRoleError:
            # A role in the database with no matrix entry. Deny, and make it
            # loud: this is a deployment fault, not a user error.
            logger.error(
                "auth.unknown_role",
                extra={"role": user.role.value, "user_id": str(user.id)},
            )
            permitted = False

        if not permitted:
            await audit.forbidden(
                user_id=user.id,
                permission=permission.value,
                path=request.url.path,
                role=user.role.value,
                **_request_context(request),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )

        return user

    return dependency


def require_any_permission(
    *permissions: Permission,
) -> Callable[..., Awaitable[AuthenticatedUser]]:
    """Build a dependency requiring at least one of several permissions.

    For an endpoint several roles reach for different reasons -- a machine
    detail page is legitimately read by a production supervisor and a quality
    engineer, whose permissions do not otherwise overlap.
    """
    if not permissions:
        raise ValueError("At least one permission is required.")

    async def dependency(
        request: Request, user: CurrentUserDep, audit: AuditServiceDep
    ) -> AuthenticatedUser:
        try:
            permitted = any(has_permission(user.role, p) for p in permissions)
        except UnknownRoleError:
            logger.error("auth.unknown_role", extra={"role": user.role.value})
            permitted = False

        if not permitted:
            await audit.forbidden(
                user_id=user.id,
                permission="|".join(p.value for p in permissions),
                path=request.url.path,
                role=user.role.value,
                **_request_context(request),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )

        return user

    return dependency


def require_role(*roles: str) -> Callable[..., Awaitable[AuthenticatedUser]]:
    """Build a dependency requiring one of several role codes.

    Provided because spec section 11 asks for it, and deliberately unused by any
    endpoint. Naming roles at a route hard-codes today's answer to a question
    the permission matrix already answers, and goes stale the moment a role is
    added. Prefer `require_permission`.
    """
    allowed = {role.upper() for role in roles}
    if not allowed:
        raise ValueError("At least one role is required.")

    async def dependency(
        request: Request, user: CurrentUserDep, audit: AuditServiceDep
    ) -> AuthenticatedUser:
        if user.role.value not in allowed:
            await audit.forbidden(
                user_id=user.id,
                permission=f"role:{'|'.join(sorted(allowed))}",
                path=request.url.path,
                role=user.role.value,
                **_request_context(request),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )
        return user

    return dependency
