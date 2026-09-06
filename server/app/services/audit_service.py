"""Audit logging for security-sensitive events (spec section 22).

Every authentication and authorization event goes through this service, which
exists to enforce one rule at a single point: **the audit trail must never
become the place a secret leaks.**

Spec section 22 lists what must not be logged -- JWTs, cookies, authorization
headers, the Google client secret, OAuth authorization codes, provider access
tokens. Redaction is applied here rather than trusted to each call site, so one
careless `metadata={"token": ...}` cannot put a credential in a table that is
append-only and therefore cannot be cleaned up afterwards.

Failures are swallowed. An audit write that raises would take down the login it
was recording, which trades a complete audit trail for an outage. The failure
itself is logged, loudly, to the application log.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.repositories.audit import AuditRepository
from app.utils.logging import get_logger

logger = get_logger(__name__)


class AuditAction:
    """Action names written to the trail.

    Constants rather than free strings so the vocabulary stays closed and a
    query for `AUTH.LOGIN_FAILURE` cannot silently miss entries someone spelled
    differently. The format matches the database CHECK constraint from Phase 2:
    uppercase, dot-separated.
    """

    LOGIN_INITIATED = "AUTH.LOGIN_INITIATED"
    LOGIN_SUCCESS = "AUTH.LOGIN_SUCCESS"
    LOGIN_FAILURE = "AUTH.LOGIN_FAILURE"
    LOGIN_DENIED = "AUTH.LOGIN_DENIED"
    OAUTH_CALLBACK_FAILURE = "AUTH.OAUTH_CALLBACK_FAILURE"
    LOGOUT = "AUTH.LOGOUT"
    TOKEN_REVOKED = "AUTH.TOKEN_REVOKED"
    TOKEN_REJECTED = "AUTH.TOKEN_REJECTED"
    UNAUTHORIZED_ACCESS = "AUTH.UNAUTHORIZED_ACCESS"
    FORBIDDEN_ACCESS = "AUTH.FORBIDDEN_ACCESS"
    USER_PROVISIONED = "USER.PROVISIONED"
    USER_IDENTITY_CLAIMED = "USER.IDENTITY_CLAIMED"
    USER_DEACTIVATED = "USER.DEACTIVATED"
    ROLE_CHANGED = "USER.ROLE_CHANGED"
    CSRF_REJECTED = "SECURITY.CSRF_REJECTED"
    REDIRECT_REJECTED = "SECURITY.REDIRECT_REJECTED"


#: Metadata keys that are dropped before writing, whatever their value.
#:
#: Matched case-insensitively against the whole key and as a substring, so
#: `id_token`, `googleAccessToken` and `x-csrf-token` are all caught. Being
#: over-broad is the right failure direction: losing a diagnostic field costs
#: nothing next to writing a credential into an append-only table.
_REDACTED_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "cookie",
    "authorization",
    "credential",
    "code",
    "key",
    "session",
    "jwt",
    "bearer",
    "assertion",
)

REDACTED = "[REDACTED]"

#: Longest string kept in metadata. A long value is either a payload or a
#: mistake, and the trail is not the place for either.
_MAX_VALUE_LENGTH = 512


def _redact(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Strip anything that looks like a credential from audit metadata."""
    if not metadata:
        return {}

    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if any(fragment in lowered for fragment in _REDACTED_KEY_FRAGMENTS):
            cleaned[key] = REDACTED
            continue

        if isinstance(value, str) and len(value) > _MAX_VALUE_LENGTH:
            cleaned[key] = value[:_MAX_VALUE_LENGTH] + "...[truncated]"
        elif isinstance(value, dict):
            cleaned[key] = _redact(value)
        else:
            cleaned[key] = value
    return cleaned


class AuditService:
    """Records security events, redacting as it goes."""

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        success: bool,
        actor_user_id: uuid.UUID | None = None,
        resource_id: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write one entry. Never raises.

        A failed audit write is reported to the application log and otherwise
        ignored: it must not be the reason a sign-in fails.
        """
        try:
            await self._repository.record(
                action=action,
                resource_type=resource_type,
                success=success,
                actor_user_id=actor_user_id,
                resource_id=resource_id,
                request_id=request_id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata=_redact(metadata),
            )
        except Exception as exc:
            logger.error(
                "audit.write_failed",
                extra={
                    "action": action,
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                },
            )

    async def login_initiated(self, **context: Any) -> None:
        await self.record(
            action=AuditAction.LOGIN_INITIATED,
            resource_type="session",
            success=True,
            **context,
        )

    async def login_success(self, *, user_id: uuid.UUID, **context: Any) -> None:
        await self.record(
            action=AuditAction.LOGIN_SUCCESS,
            resource_type="session",
            success=True,
            actor_user_id=user_id,
            resource_id=str(user_id),
            **context,
        )

    async def login_failure(self, *, reason: str, **context: Any) -> None:
        metadata = context.pop("metadata", {}) or {}
        await self.record(
            action=AuditAction.LOGIN_FAILURE,
            resource_type="session",
            success=False,
            metadata={**metadata, "reason": reason},
            **context,
        )

    async def login_denied(self, *, reason: str, **context: Any) -> None:
        """A verified identity that policy refused.

        Distinct from a failure: the sign-in worked, and the application chose
        not to admit them. Worth separating, because a run of these means the
        account restriction is misconfigured, not that anyone is under attack.
        """
        metadata = context.pop("metadata", {}) or {}
        await self.record(
            action=AuditAction.LOGIN_DENIED,
            resource_type="session",
            success=False,
            metadata={**metadata, "reason": reason},
            **context,
        )

    async def logout(self, *, user_id: uuid.UUID, revoked: bool, **context: Any) -> None:
        await self.record(
            action=AuditAction.LOGOUT,
            resource_type="session",
            success=True,
            actor_user_id=user_id,
            resource_id=str(user_id),
            metadata={"session_revoked": revoked},
            **context,
        )

    async def unauthorized(self, *, reason: str, path: str, **context: Any) -> None:
        await self.record(
            action=AuditAction.UNAUTHORIZED_ACCESS,
            resource_type="endpoint",
            success=False,
            resource_id=path,
            metadata={"reason": reason},
            **context,
        )

    async def forbidden(
        self,
        *,
        user_id: uuid.UUID,
        permission: str,
        path: str,
        role: str,
        **context: Any,
    ) -> None:
        """An authenticated user who lacked the permission.

        The most interesting event in the trail: it is the signature of either a
        misconfigured role or someone probing the API directly, having noticed
        that the button was missing from their screen.
        """
        await self.record(
            action=AuditAction.FORBIDDEN_ACCESS,
            resource_type="endpoint",
            success=False,
            actor_user_id=user_id,
            resource_id=path,
            metadata={"required_permission": permission, "role": role},
            **context,
        )
