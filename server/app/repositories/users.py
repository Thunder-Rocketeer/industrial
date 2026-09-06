"""User and role data access.

Follows the same rules as every other repository (spec section 19): database
access only, parameterised values, no business logic. The provisioning *policy*
-- who may sign in, what role they get -- lives in the auth service; this module
only reads and writes rows.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import sql

from app.repositories.base import BaseRepository, WhereBuilder

_USER_COLUMNS = sql.SQL("""
    u.id, u.email, u.full_name, u.avatar_url,
    u.provider, u.provider_subject,
    u.role_id, r.code as role_code, r.name as role_name, r.rank as role_rank,
    u.is_active, u.last_login_at, u.created_at, u.updated_at
""")

_USER_FROM = sql.SQL("""
    public.users u
    join public.roles r on r.id = u.role_id
""")


class UserRepository(BaseRepository):
    """Reads and writes application users."""

    async def get_by_provider_identity(
        self, *, provider: str, subject: str
    ) -> dict[str, Any] | None:
        """Find a user by their stable provider identity.

        The primary sign-in lookup. `(provider, provider_subject)` is the
        identity key -- never the email, which can be reassigned.
        """
        statement = sql.SQL("""
            select {columns}
            from {source}
            where u.provider = %s and u.provider_subject = %s
        """).format(columns=_USER_COLUMNS, source=_USER_FROM)
        return await self.fetch_one(statement, [provider, subject])

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        """Find a user by email address.

        Used only to claim a seeded account on its owner's first sign-in. It is
        not an authentication path: the caller has already verified the Google
        identity and confirmed the address is verified before reaching here.
        """
        statement = sql.SQL("""
            select {columns}
            from {source}
            where u.email = %s
        """).format(columns=_USER_COLUMNS, source=_USER_FROM)
        return await self.fetch_one(statement, [email.strip().lower()])

    async def get_by_id(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        """Load a user by their application UUID.

        Called on every authenticated request, which is what makes the
        `is_active` check meaningful: a deactivated user is rejected on their
        next request rather than when their token happens to expire.
        """
        statement = sql.SQL("""
            select {columns}
            from {source}
            where u.id = %s
        """).format(columns=_USER_COLUMNS, source=_USER_FROM)
        return await self.fetch_one(statement, [user_id])

    async def get_role_by_code(self, code: str) -> dict[str, Any] | None:
        """Resolve a role code to its row."""
        statement = sql.SQL("""
            select id, code, name, rank
            from public.roles
            where code = %s
        """)
        return await self.fetch_one(statement, [code])

    async def create_user(
        self,
        *,
        email: str,
        full_name: str,
        role_id: uuid.UUID,
        provider: str,
        provider_subject: str,
        avatar_url: str | None,
    ) -> dict[str, Any] | None:
        """Insert a newly provisioned user and return the full row.

        `role_id` is resolved by the service from configuration, never from
        anything the request supplied (spec section 5).

        `ON CONFLICT (email) DO NOTHING` handles the race where two sign-ins for
        the same new user arrive together: the second insert returns no row, and
        the caller falls back to reading the one the first created.
        """
        statement = sql.SQL("""
            insert into public.users
                (email, full_name, role_id, provider, provider_subject,
                 avatar_url, is_active, last_login_at)
            values (%s, %s, %s, %s, %s, %s, true, now())
            on conflict (email) do nothing
            returning id
        """)
        row = await self.fetch_one(
            statement,
            [
                email.strip().lower(),
                full_name,
                role_id,
                provider,
                provider_subject,
                avatar_url,
            ],
        )
        if row is None:
            return None
        return await self.get_by_id(row["id"])

    async def claim_identity(
        self,
        *,
        user_id: uuid.UUID,
        provider: str,
        provider_subject: str,
        full_name: str,
        avatar_url: str | None,
    ) -> dict[str, Any] | None:
        """Attach a provider identity to an existing user, on first sign-in.

        The `provider_subject is null` guard is the security-critical part. It
        means an account can only be claimed while unclaimed: once a subject is
        attached, a different Google account presenting the same email address
        cannot take it over. Without the guard, an address reassigned inside a
        Workspace domain would hand the previous holder's role to its new owner.
        """
        statement = sql.SQL("""
            update public.users
            set provider = %s,
                provider_subject = %s,
                full_name = %s,
                avatar_url = %s,
                last_login_at = now()
            where id = %s
              and provider_subject is null
            returning id
        """)
        row = await self.fetch_one(
            statement, [provider, provider_subject, full_name, avatar_url, user_id]
        )
        if row is None:
            return None
        return await self.get_by_id(row["id"])

    async def record_login(
        self,
        *,
        user_id: uuid.UUID,
        full_name: str,
        avatar_url: str | None,
    ) -> dict[str, Any] | None:
        """Update the login timestamp and refresh the profile fields.

        Name and avatar are refreshed on every sign-in because they are display
        data owned by Google. The email and role are deliberately *not* touched:
        the email is part of the account's identity within this application, and
        the role is assigned here, never by the provider.
        """
        statement = sql.SQL("""
            update public.users
            set last_login_at = now(),
                full_name = %s,
                avatar_url = %s
            where id = %s
            returning id
        """)
        row = await self.fetch_one(statement, [full_name, avatar_url, user_id])
        if row is None:
            return None
        return await self.get_by_id(row["id"])

    async def set_active(self, *, user_id: uuid.UUID, is_active: bool) -> bool:
        """Enable or disable an account.

        No endpoint exposes this yet; it exists so deactivation can be performed
        from a console or a future admin route, and so the behaviour is testable.
        """
        statement = sql.SQL("""
            update public.users
            set is_active = %s
            where id = %s
            returning id
        """)
        return await self.fetch_one(statement, [is_active, user_id]) is not None

    async def list_users(
        self, *, limit: int, offset: int, active_only: bool = False
    ) -> tuple[list[dict[str, Any]], int]:
        """List users, for a future administration screen."""
        where = WhereBuilder()
        if active_only:
            where.add("u.is_active = true")

        statement = sql.SQL("""
            select {columns}
            from {source}
            {where}
            order by r.rank, u.email
            limit %s offset %s
        """).format(columns=_USER_COLUMNS, source=_USER_FROM, where=where.clause())

        rows = await self.fetch_all(statement, [*where.params, limit, offset])
        total = await self.count(_USER_FROM, where)
        return rows, total
