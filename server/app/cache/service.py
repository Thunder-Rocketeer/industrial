"""Cache-aside orchestration and centralised invalidation.

Services call `get_or_set` and never touch Redis directly. That keeps three
concerns in one place instead of repeated at every call site: TTL selection,
the decision that a cache failure is a miss rather than an error, and
invalidation (spec section 13: "Keep cache invalidation centralized in the
service/cache layer. Avoid duplicated cache logic across route handlers").

Cached values are validated against their Pydantic model on read. A deployment
that changes a response shape therefore treats entries written by the previous
version as misses and replaces them, rather than serving stale-shaped data until
the TTL expires.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TypeVar

from pydantic import BaseModel

from app.cache.client import CacheClient
from app.cache.keys import CacheKeys
from app.cache.serializer import CacheSerializationError, dumps, load_model, loads
from app.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


class CacheTier(str, Enum):
    """Volatility tiers from spec section 12.

    A tier is named at the call site; the TTL comes from configuration, so all
    four are tunable per environment without touching a service.
    """

    #: Dashboard summary and KPI cards. Seconds.
    REALTIME = "realtime"
    #: Trend and chart data over recent periods. Minutes.
    TREND = "trend"
    #: Historical analytics that change slowly.
    ANALYTICS = "analytics"
    #: Components, machines, lines, shifts, defect types.
    REFERENCE = "reference"


class CacheService:
    """Cache-aside reads with per-tier TTLs.

    Args:
        client: The Redis wrapper. Already degrades gracefully.
        keys: Key builder.
        settings: Supplies the configurable TTL for each tier.
    """

    def __init__(self, client: CacheClient, keys: CacheKeys, settings: Settings) -> None:
        self._client = client
        self._keys = keys
        self._settings = settings

    @property
    def keys(self) -> CacheKeys:
        return self._keys

    @property
    def client(self) -> CacheClient:
        return self._client

    def ttl_for(self, tier: CacheTier) -> int:
        """Return the configured TTL, in seconds, for a tier."""
        return {
            CacheTier.REALTIME: self._settings.cache_ttl_dashboard,
            CacheTier.TREND: self._settings.cache_ttl_trends,
            CacheTier.ANALYTICS: self._settings.cache_ttl_analytics,
            CacheTier.REFERENCE: self._settings.cache_ttl_reference,
        }[tier]

    async def get_or_set(
        self,
        key: str,
        tier: CacheTier,
        model: type[TModel],
        loader: Callable[[], Awaitable[TModel]],
    ) -> TModel:
        """Return a cached value, computing and storing it on a miss.

        `loader` runs only on a miss. Any cache problem -- outage, corrupt entry,
        a shape from a previous deployment -- is treated as a miss, so the
        response is always correct even when the cache is not.

        Note this does not guard against a cache stampede: several concurrent
        misses will each run the loader. For dashboard aggregates that is
        acceptable, and a lock would add a failure mode of its own. It would be
        worth revisiting for a query expensive enough that duplicate execution
        hurts.
        """
        raw = await self._client.get(key)
        if raw is not None:
            try:
                value = load_model(raw, model)
            except CacheSerializationError:
                # Stale shape or corrupt entry. Log and recompute rather than
                # failing the request.
                logger.info("cache.entry_rejected", extra={"cache_key": key})
            else:
                logger.debug("cache.hit", extra={"cache_key": key})
                return value

        value = await loader()
        await self.set(key, value, tier)
        return value

    async def get_or_set_list(
        self,
        key: str,
        tier: CacheTier,
        model: type[TModel],
        loader: Callable[[], Awaitable[list[TModel]]],
    ) -> list[TModel]:
        """List-valued counterpart of `get_or_set`.

        Trends and breakdowns are sequences rather than single models, and a
        JSON array is not a Pydantic model, so it needs its own validation path
        rather than being forced through `load_model`.
        """
        raw = await self._client.get(key)
        if raw is not None:
            try:
                payload = loads(raw)
                if not isinstance(payload, list):
                    raise CacheSerializationError("Cached value is not a list.")
                return [model.model_validate(item) for item in payload]
            except (CacheSerializationError, ValueError, TypeError):
                logger.info("cache.entry_rejected", extra={"cache_key": key})

        values = await loader()
        await self.set_list(key, values, tier)
        return values

    async def set_list(self, key: str, values: list[BaseModel], tier: CacheTier) -> bool:
        """Store a list of models. Never raises."""
        ttl = self.ttl_for(tier)
        if ttl <= 0:
            return False
        try:
            payload = dumps([value.model_dump(mode="json") for value in values])
        except CacheSerializationError:
            logger.warning("cache.serialize_failed", extra={"cache_key": key})
            return False
        return await self._client.set(key, payload, ttl)

    async def set(self, key: str, value: BaseModel, tier: CacheTier) -> bool:
        """Store a model. Never raises."""
        ttl = self.ttl_for(tier)
        if ttl <= 0:
            return False
        try:
            payload = dumps(value)
        except CacheSerializationError:
            logger.warning("cache.serialize_failed", extra={"cache_key": key})
            return False
        return await self._client.set(key, payload, ttl)

    # -- invalidation ---------------------------------------------------------

    async def invalidate_domain(self, domain: str) -> int:
        """Drop every cached entry for one domain.

        Called after a write that changes what a domain's aggregates would
        return. Phase 3 is read-only, so nothing calls this yet -- it exists so
        that the first mutating endpoint has an obvious, single place to
        invalidate from rather than inventing its own scheme.
        """
        removed = await self._client.delete_pattern(self._keys.domain_pattern(domain))
        if removed:
            logger.info("cache.invalidated", extra={"domain": domain, "keys": removed})
        return removed

    async def invalidate_production(self) -> None:
        """Invalidate everything a production write affects.

        Production feeds the dashboard summary, trends and OEE, so a change
        there invalidates more than the production domain alone. Encoding that
        fan-out here is the point: a caller should not have to know which other
        aggregates depend on production.
        """
        for domain in ("production", "dashboard", "analytics"):
            await self.invalidate_domain(domain)

    async def invalidate_quality(self) -> None:
        for domain in ("quality", "dashboard", "analytics"):
            await self.invalidate_domain(domain)

    async def invalidate_inventory(self) -> None:
        for domain in ("inventory", "dashboard"):
            await self.invalidate_domain(domain)

    async def invalidate_machines(self) -> None:
        for domain in ("machines", "dashboard", "analytics"):
            await self.invalidate_domain(domain)
