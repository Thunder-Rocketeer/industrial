"""Audit trail data access (spec section 22).

`audit_logs` is append-only, enforced by a database trigger from Phase 2. This
repository therefore has an insert and reads, and no update or delete -- not by
convention, but because the database would reject them.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from app.repositories.base import BaseRepository, WhereBuilder


class AuditRepository(BaseRepository):
    """Writes and reads the security audit trail."""

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
        """Append one audit entry.

        `metadata` is redacted by the service before it arrives here -- this
        layer writes what it is given. The insert is deliberately not returning
        anything: nothing downstream needs the id, and an audit write should be
        as cheap as possible so it is never the reason a login is slow.
        """
        statement = sql.SQL("""
            insert into public.audit_logs
                (actor_user_id, action, resource_type, resource_id,
                 success, request_id, ip_address, user_agent, metadata)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """)
        await self.execute(
            statement,
            [
                actor_user_id,
                action,
                resource_type,
                resource_id,
                success,
                request_id,
                ip_address,
                user_agent,
                Jsonb(metadata or {}),
            ],
        )

    async def list_entries(
        self,
        *,
        limit: int,
        offset: int,
        actor_user_id: uuid.UUID | None = None,
        action: str | None = None,
        success: bool | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Read the trail, newest first. For a future administration screen."""
        where = WhereBuilder()
        where.add_if(actor_user_id, "a.actor_user_id = %s", actor_user_id)
        where.add_if(action, "a.action = %s", action)
        if success is not None:
            where.add("a.success = %s", success)

        source = sql.SQL("""
            public.audit_logs a
            left join public.users u on u.id = a.actor_user_id
        """)

        statement = sql.SQL("""
            select
                a.id, a.actor_user_id, u.email as actor_email,
                a.action, a.resource_type, a.resource_id,
                a.success, a.request_id, a.ip_address, a.user_agent,
                a.metadata, a.occurred_at
            from {source}
            {where}
            order by a.occurred_at desc, a.id desc
            limit %s offset %s
        """).format(source=source, where=where.clause())

        rows = await self.fetch_all(statement, [*where.params, limit, offset])
        total = await self.count(source, where)
        return rows, total
