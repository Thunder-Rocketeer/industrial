"""Authentication business logic (spec sections 5 and 28).

Everything that decides *who may sign in and what they get* lives here. The
route handles HTTP, `security/oauth.py` handles the protocol, the repository
handles rows -- and the policy is in one readable place.

THE THREE RULES THAT MATTER

**A role is never taken from a request.** Not from a query parameter, not from a
form field, not from a Google claim. It comes from the database for an existing
user, or from `AUTH_DEFAULT_ROLE` for a new one. Spec section 5 states this four
different ways because it is the single most tempting shortcut in an OAuth
integration: Google is authenticating the person, so it feels natural to let the
sign-in request say what they are.

**Identity is the provider subject, never the email.** An address can be
reassigned inside a Workspace domain. If email were the key, the new holder of
`manager@factory.local` would inherit the Factory Manager role.

**Account restriction is enforced after verification, never before.** The
allow-list is checked against the email in the *verified ID token*, not against
anything the browser sent (spec section 28).

THE ONE EXCEPTION, AND ITS GUARD

Seeded demo accounts exist with real roles and no provider identity. A first
sign-in matching one by email claims it, so `admin@factory.local` gets the Admin
role rather than the default. That is a deliberate convenience for a course
deployment, and it would be a serious hole without its guard: an account can be
claimed only while `provider_subject IS NULL`. Once claimed, a different Google
account presenting the same address cannot take it over. The guard lives in the
repository's `WHERE` clause, so it is enforced by the database rather than by a
check that could be reordered away.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.models.enums import RoleCode
from app.repositories.users import UserRepository
from app.security.oauth import GoogleIdentity
from app.security.policy import permissions_for
from app.services.audit_service import AuditService
from app.utils.logging import get_logger

logger = get_logger(__name__)


class AuthenticationError(Exception):
    """Sign-in failed or was refused.

    One exception type for every reason, carrying a machine-readable `reason`
    for the audit trail and a client-safe `message`. The client is never told
    which rule refused them: "your account is not permitted" and "your domain is
    not on the allow-list" differ only in how much they help someone enumerate
    the policy.
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        self.message = message or "Sign-in was not successful."
        super().__init__(reason)


@dataclass(frozen=True)
class AuthenticatedUser:
    """A signed-in user, resolved from the database.

    Built on every authenticated request, so it carries exactly what
    authorization and `/auth/me` need and nothing else.
    """

    id: uuid.UUID
    email: str
    name: str
    role: RoleCode
    role_label: str
    avatar_url: str | None
    is_active: bool
    last_login_at: Any = None

    @property
    def permissions(self) -> list[str]:
        """Permission strings for this user's role, for the frontend to read."""
        return sorted(permission.value for permission in permissions_for(self.role))

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AuthenticatedUser:
        """Map a `users` row to the domain object."""
        return cls(
            id=row["id"],
            email=row["email"],
            name=row["full_name"],
            role=RoleCode(row["role_code"]),
            role_label=row["role_name"],
            avatar_url=row.get("avatar_url"),
            is_active=row["is_active"],
            last_login_at=row.get("last_login_at"),
        )


class AuthService:
    """Resolves verified Google identities into application users."""

    def __init__(
        self,
        repository: UserRepository,
        audit: AuditService,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._audit = audit
        self._settings = settings

    # -- account restriction (spec section 28) --------------------------------

    def is_email_permitted(self, email: str) -> bool:
        """Whether an address is allowed to sign in.

        Two independent allow-lists, either of which admits an address. Both
        empty means any Google account may sign in, which is the right default
        for a course demo and must be changed for anything real -- the
        documentation says so, and `AUTH_ALLOWED_EMAIL_DOMAINS` is the switch.
        """
        allowed_emails = self._settings.auth_allowed_emails
        allowed_domains = self._settings.auth_allowed_email_domains

        if not allowed_emails and not allowed_domains:
            return True

        normalized = email.strip().lower()
        if normalized in allowed_emails:
            return True

        # rsplit, not split: an address may contain more than one `@` in its
        # local part, and the domain is always what follows the last one.
        domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
        return domain in allowed_domains

    # -- sign-in --------------------------------------------------------------

    async def resolve_user(
        self,
        identity: GoogleIdentity,
        *,
        request_context: dict[str, Any] | None = None,
    ) -> AuthenticatedUser:
        """Turn a verified Google identity into an application user.

        Tried in order: an existing provider identity, then an unclaimed account
        with the same email, then provisioning a new one. Each step is narrower
        than the last, and the first match wins.

        Raises:
            AuthenticationError: If policy refuses the sign-in.
        """
        context = request_context or {}
        provider = "google"

        if not self.is_email_permitted(identity.email):
            await self._audit.login_denied(
                reason="email_not_permitted",
                metadata={"email_domain": identity.email.rsplit("@", 1)[-1]},
                **context,
            )
            raise AuthenticationError(
                "email_not_permitted",
                "This account is not permitted to sign in to this application.",
            )

        # --- 1. a returning user, matched on the stable identity -------------
        row = await self._repository.get_by_provider_identity(
            provider=provider, subject=identity.subject
        )
        if row is not None:
            user = AuthenticatedUser.from_row(row)
            self._require_active(user)
            refreshed = await self._repository.record_login(
                user_id=user.id,
                full_name=identity.name,
                avatar_url=identity.picture,
            )
            return AuthenticatedUser.from_row(refreshed or row)

        # --- 2. an unclaimed seeded account with this email -------------------
        existing = await self._repository.get_by_email(identity.email)
        if existing is not None:
            if existing["provider_subject"] is not None:
                # The address belongs to a different Google account. This is the
                # reassigned-mailbox case, and it must not be a takeover.
                await self._audit.login_denied(
                    reason="email_claimed_by_other_identity",
                    metadata={"user_id": str(existing["id"])},
                    **context,
                )
                raise AuthenticationError(
                    "email_claimed_by_other_identity",
                    "This email address is already linked to a different account.",
                )

            claimed = await self._repository.claim_identity(
                user_id=existing["id"],
                provider=provider,
                provider_subject=identity.subject,
                full_name=identity.name,
                avatar_url=identity.picture,
            )
            if claimed is None:
                # Another request claimed it between the read and the update.
                # Re-read rather than guessing which won.
                current = await self._repository.get_by_provider_identity(
                    provider=provider, subject=identity.subject
                )
                if current is None:
                    raise AuthenticationError("identity_claim_conflict")
                claimed = current

            user = AuthenticatedUser.from_row(claimed)
            self._require_active(user)
            await self._audit.record(
                action="USER.IDENTITY_CLAIMED",
                resource_type="user",
                resource_id=str(user.id),
                success=True,
                actor_user_id=user.id,
                metadata={"provider": provider, "role": user.role.value},
                **context,
            )
            logger.info(
                "auth.identity_claimed",
                extra={"user_id": str(user.id), "role": user.role.value},
            )
            return user

        # --- 3. provision a new user ------------------------------------------
        if not self._settings.auth_auto_provision:
            await self._audit.login_denied(reason="auto_provision_disabled", **context)
            raise AuthenticationError(
                "auto_provision_disabled",
                "This account does not exist. Ask an administrator to create it.",
            )

        return await self._provision(identity, provider=provider, context=context)

    async def _provision(
        self,
        identity: GoogleIdentity,
        *,
        provider: str,
        context: dict[str, Any],
    ) -> AuthenticatedUser:
        """Create a user with the configured default role.

        The role comes from `AUTH_DEFAULT_ROLE`, which defaults to `VIEWER` --
        the least privileged role there is. A new arrival gets read access to
        the dashboard and nothing else until someone deliberately promotes them.
        """
        role_code = self._settings.auth_default_role
        role = await self._repository.get_role_by_code(role_code)
        if role is None:
            # Configuration validation checks the code is a known enum value,
            # but not that the row exists -- an unseeded database reaches here.
            logger.error("auth.default_role_missing", extra={"role_code": role_code})
            raise AuthenticationError(
                "default_role_missing",
                "Sign-in is not available. Please contact an administrator.",
            )

        created = await self._repository.create_user(
            email=identity.email,
            full_name=identity.name,
            role_id=role["id"],
            provider=provider,
            provider_subject=identity.subject,
            avatar_url=identity.picture,
        )
        if created is None:
            # Lost a race with a concurrent sign-in for the same new user.
            existing = await self._repository.get_by_email(identity.email)
            if existing is None:
                raise AuthenticationError("provisioning_conflict")
            created = existing

        user = AuthenticatedUser.from_row(created)
        self._require_active(user)

        await self._audit.record(
            action="USER.PROVISIONED",
            resource_type="user",
            resource_id=str(user.id),
            success=True,
            actor_user_id=user.id,
            metadata={"provider": provider, "role": user.role.value},
            **context,
        )
        logger.info(
            "auth.user_provisioned",
            extra={"user_id": str(user.id), "role": user.role.value},
        )
        return user

    @staticmethod
    def _require_active(user: AuthenticatedUser) -> None:
        """Refuse a deactivated account (spec section 23).

        Checked at sign-in *and* on every subsequent request, because a token
        issued before deactivation would otherwise keep working until it expired.
        """
        if not user.is_active:
            raise AuthenticationError(
                "user_inactive",
                "This account has been deactivated. Please contact an administrator.",
            )

    # -- session lookup, on every authenticated request ------------------------

    async def load_active_user(self, user_id: uuid.UUID) -> AuthenticatedUser | None:
        """Load a user for an authenticated request, or None if unusable.

        Returns None both for "no such user" and "deactivated", because the
        caller's response is the same and distinguishing them for the client
        would confirm which user ids exist.

        This read is the reason deactivation takes effect immediately rather
        than at token expiry. It costs one indexed primary-key lookup per
        request, which is the right price for the guarantee.
        """
        row = await self._repository.get_by_id(user_id)
        if row is None or not row["is_active"]:
            return None
        return AuthenticatedUser.from_row(row)
