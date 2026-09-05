"""Deterministic cache key construction (spec section 12).

Two rules make these keys safe to rely on.

**Stable filter hashing.** A key must depend on the filter *values*, never on
the order they happened to arrive in or on how Python rendered them. Filters are
therefore normalised -- sorted by name, `None` dropped, dates and UUIDs rendered
canonically -- and hashed with blake2b. Python's `hash()` is unusable here for
the same reason it was unusable in the seed: it is salted per process, so two
workers would compute different keys for identical filters and neither would
ever see the other's entry.

**Namespacing.** Every key carries a configurable prefix and a schema version.
The prefix keeps environments sharing one Redis from colliding; the version lets
a response-shape change invalidate everything at once by being bumped, rather
than requiring a flush.

Spec section 16: keys must never contain a credential, a token, or personal
data. They are built only from resource names, dates and filter values. When
role-scoped data arrives, the authorization context has to become part of the
key -- `for_user` exists for that and is unused until then.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any
from uuid import UUID

#: Bumped when a cached response shape changes in a way older entries cannot
#: satisfy. Cheaper and safer than flushing a shared Redis.
SCHEMA_VERSION = "v1"

#: Keys are truncated to this many hex characters. 16 hex digits is 64 bits;
#: collisions are not a practical concern at dashboard cardinality, and short
#: keys keep `redis-cli --scan` output readable.
_HASH_LENGTH = 16


def _normalize(value: Any) -> Any:
    """Render a filter value canonically so equal filters hash identically."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        # Before the int check: bool is a subclass of int.
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        # Sorted, so ["A", "B"] and ["B", "A"] are the same filter.
        return sorted(_normalize(item) for item in value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items())}
    if hasattr(value, "value"):  # Enum
        return str(value.value)
    return str(value)


def filters_hash(filters: dict[str, Any] | None) -> str:
    """Return a short, stable hash of a filter set.

    Keys with a `None` value are dropped rather than hashed, so "no machine
    filter" produces the same hash whether the parameter was absent or
    explicitly null.
    """
    if not filters:
        return "none"

    normalized = {
        key: _normalize(value) for key, value in sorted(filters.items()) if value is not None
    }
    if not normalized:
        return "none"

    payload = repr(normalized).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=8).hexdigest()[:_HASH_LENGTH]


class CacheKeys:
    """Builds namespaced cache keys.

    Args:
        prefix: Environment namespace, from `CACHE_KEY_PREFIX`.
    """

    def __init__(self, prefix: str = "acf") -> None:
        self._prefix = prefix.strip(":") or "acf"

    def _build(self, *parts: object) -> str:
        segments = [self._prefix, SCHEMA_VERSION, *(str(part) for part in parts)]
        return ":".join(segments)

    # -- dashboard ------------------------------------------------------------

    def dashboard_summary(self, on_date: date) -> str:
        return self._build("dashboard", "summary", on_date.isoformat())

    def dashboard_trends(self, start: date, end: date, filters: dict[str, Any] | None) -> str:
        return self._build(
            "dashboard", "trends", start.isoformat(), end.isoformat(), filters_hash(filters)
        )

    def dashboard_alerts(self) -> str:
        return self._build("dashboard", "alerts")

    # -- production -----------------------------------------------------------

    def production_summary(self, start: date, end: date, filters: dict[str, Any] | None) -> str:
        return self._build(
            "production", "summary", start.isoformat(), end.isoformat(), filters_hash(filters)
        )

    def production_trend(self, start: date, end: date, filters: dict[str, Any] | None) -> str:
        return self._build(
            "production", "trend", start.isoformat(), end.isoformat(), filters_hash(filters)
        )

    # -- quality --------------------------------------------------------------

    def quality_summary(self, start: date, end: date, filters: dict[str, Any] | None) -> str:
        return self._build(
            "quality", "summary", start.isoformat(), end.isoformat(), filters_hash(filters)
        )

    def defect_breakdown(self, start: date, end: date, filters: dict[str, Any] | None) -> str:
        return self._build(
            "quality", "defects", start.isoformat(), end.isoformat(), filters_hash(filters)
        )

    # -- inventory ------------------------------------------------------------

    def inventory_alerts(self) -> str:
        return self._build("inventory", "alerts")

    def inventory_summary(self) -> str:
        return self._build("inventory", "summary")

    # -- machines -------------------------------------------------------------

    def machines_summary(self) -> str:
        return self._build("machines", "summary")

    # -- analytics ------------------------------------------------------------

    def analytics_oee(self, start: date, end: date, filters: dict[str, Any] | None) -> str:
        return self._build(
            "analytics", "oee", start.isoformat(), end.isoformat(), filters_hash(filters)
        )

    def analytics_efficiency(self, start: date, end: date, filters: dict[str, Any] | None) -> str:
        return self._build(
            "analytics", "efficiency", start.isoformat(), end.isoformat(), filters_hash(filters)
        )

    def analytics_defects(self, start: date, end: date, filters: dict[str, Any] | None) -> str:
        return self._build(
            "analytics", "defects", start.isoformat(), end.isoformat(), filters_hash(filters)
        )

    # -- reference data -------------------------------------------------------

    def reference(self, resource: str) -> str:
        return self._build("reference", resource)

    # -- invalidation ---------------------------------------------------------

    def domain_pattern(self, domain: str) -> str:
        """Glob matching every key in a domain, for invalidation.

        Spec section 13: invalidation is centralised in the cache service, which
        is the only caller of this.
        """
        return self._build(domain, "*")

    def for_user(self, user_id: str, *parts: object) -> str:
        """Namespace a key to one user.

        Unused in Phase 3 -- every cached value is currently factory-wide
        aggregate data with no per-user component. It exists so that when
        role-scoped data is introduced in Phase 4 there is one obvious place to
        add the authorization context, rather than a scramble to find every key
        that silently became user-specific.
        """
        return self._build("user", user_id, *parts)
