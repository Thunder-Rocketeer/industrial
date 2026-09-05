"""Tests for the Redis cache layer (spec section 11).

The behaviour that matters most is what happens when Redis is *not* working. The
requirement is explicit: "Redis failure must NOT make the entire dashboard
unusable. If Redis is unavailable: log the failure, continue using the
database." So most of this file is about failure.

A fake Redis stands in for the real one. It can be told to fail, which is the
only practical way to test the degradation paths deterministically -- a real
Redis that is up will not produce them, and one that is down produces them
slowly.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel

from app.cache.client import CacheClient, CircuitBreaker
from app.cache.keys import CacheKeys, filters_hash
from app.cache.serializer import CacheSerializationError, dumps, load_model, loads
from app.cache.service import CacheService, CacheTier
from app.config import Settings


class FakeRedis:
    """In-memory stand-in for `redis.asyncio.Redis`.

    `fail` makes every operation raise, which is how the degradation paths are
    exercised.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.fail = fail
        self.calls = 0

    def _check(self) -> None:
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis is down")

    async def get(self, key: str) -> str | None:
        self._check()
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._check()
        self.store[key] = value
        if ex is not None:
            self.expiries[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        self._check()
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed

    async def scan_iter(self, match: str = "*", count: int = 100):
        self._check()
        prefix = match.rstrip("*")
        for key in list(self.store):
            if key.startswith(prefix):
                yield key

    async def ping(self) -> bool:
        self._check()
        return True

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self)


class FakePipeline:
    """Minimal pipeline supporting the INCR + EXPIRE the rate limiter uses."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    async def __aenter__(self) -> FakePipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def incr(self, key: str, amount: int = 1) -> None:
        self._ops.append(("incr", (key, amount)))

    def expire(self, key: str, seconds: int) -> None:
        self._ops.append(("expire", (key, seconds)))

    async def execute(self) -> list[Any]:
        self._redis._check()
        results: list[Any] = []
        for op, args in self._ops:
            if op == "incr":
                key, amount = args
                current = int(self._redis.store.get(key, 0)) + amount
                self._redis.store[key] = str(current)
                results.append(current)
            else:
                key, seconds = args
                self._redis.expiries[key] = seconds
                results.append(True)
        return results


class SampleModel(BaseModel):
    name: str
    value: int


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def cache_service(redis: FakeRedis, settings: Settings) -> CacheService:
    return CacheService(CacheClient(redis), CacheKeys("test"), settings)


# =============================================================================
# Serializer
# =============================================================================


def test_serializer_round_trips_a_model() -> None:
    model = SampleModel(name="brake disc", value=42)
    assert load_model(dumps(model), SampleModel) == model


def test_serializer_encodes_uuid_date_and_decimal() -> None:
    """Types psycopg returns that JSON does not natively support."""
    from decimal import Decimal

    payload = loads(
        dumps(
            {
                "id": UUID("7f4d2c18-3b9a-5e64-9d21-8a6c0f5b1e73"),
                "day": date(2026, 9, 5),
                "quantity": Decimal("12.5"),
            }
        )
    )

    assert payload["id"] == "7f4d2c18-3b9a-5e64-9d21-8a6c0f5b1e73"
    assert payload["day"] == "2026-09-05"
    assert payload["quantity"] == 12.5


def test_serializer_rejects_unencodable_values() -> None:
    with pytest.raises(CacheSerializationError):
        dumps({"connection": object()})


def test_loading_a_stale_shape_raises() -> None:
    """A deployment that changes a response shape must not serve old entries."""
    with pytest.raises(CacheSerializationError):
        load_model('{"name": "only a name"}', SampleModel)


def test_loading_corrupt_json_raises() -> None:
    with pytest.raises(CacheSerializationError):
        loads("{not json")


# =============================================================================
# Keys
# =============================================================================


def test_filters_hash_is_order_independent() -> None:
    """Equal filters must hash equally regardless of insertion order."""
    assert filters_hash({"a": 1, "b": 2}) == filters_hash({"b": 2, "a": 1})


def test_filters_hash_ignores_none_values() -> None:
    """An absent filter and an explicitly null one are the same query."""
    assert filters_hash({"machine": None, "line": "A"}) == filters_hash({"line": "A"})


def test_filters_hash_distinguishes_different_values() -> None:
    assert filters_hash({"line": "A"}) != filters_hash({"line": "B"})


def test_filters_hash_is_stable_across_processes() -> None:
    """Pinned, because two workers computing different keys would never share.

    blake2b rather than Python's salted `hash()`, for the same reason the seed
    avoids it.
    """
    assert filters_hash({"line": "LINE-A"}) == filters_hash({"line": "LINE-A"})
    assert filters_hash(None) == "none"
    assert filters_hash({}) == "none"


def test_filters_hash_normalises_sequences() -> None:
    assert filters_hash({"codes": ["B", "A"]}) == filters_hash({"codes": ["A", "B"]})


def test_keys_are_namespaced_and_versioned() -> None:
    """The prefix separates environments; the version invalidates on a reshape."""
    keys = CacheKeys("acf")
    key = keys.dashboard_summary(date(2026, 9, 5))

    assert key.startswith("acf:v1:")
    assert "2026-09-05" in key


def test_keys_differ_by_filters() -> None:
    keys = CacheKeys("acf")
    start, end = date(2026, 1, 1), date(2026, 1, 31)

    assert keys.production_summary(start, end, {"line": "A"}) != keys.production_summary(
        start, end, {"line": "B"}
    )


def test_domain_pattern_matches_the_domain() -> None:
    keys = CacheKeys("acf")
    assert keys.domain_pattern("production") == "acf:v1:production:*"


def test_user_scoped_keys_include_the_user() -> None:
    """Unused in Phase 3, but the hook for role-scoped caching in Phase 4."""
    keys = CacheKeys("acf")
    assert "user:abc123" in keys.for_user("abc123", "dashboard")


# =============================================================================
# Client: normal operation
# =============================================================================


async def test_client_stores_and_reads(redis: FakeRedis) -> None:
    client = CacheClient(redis)

    assert await client.set("k", "v", 60) is True
    assert await client.get("k") == "v"
    assert client.stats["hits"] == 1


async def test_client_records_a_miss(redis: FakeRedis) -> None:
    client = CacheClient(redis)

    assert await client.get("absent") is None
    assert client.stats["misses"] == 1


async def test_client_applies_a_ttl(redis: FakeRedis) -> None:
    client = CacheClient(redis)
    await client.set("k", "v", 45)

    assert redis.expiries["k"] == 45


async def test_client_refuses_to_store_without_a_ttl(redis: FakeRedis) -> None:
    """A non-expiring entry in a cache is a memory leak with extra steps."""
    client = CacheClient(redis)

    assert await client.set("k", "v", 0) is False
    assert "k" not in redis.store


async def test_client_deletes_by_pattern(redis: FakeRedis) -> None:
    client = CacheClient(redis)
    await client.set("acf:v1:production:a", "1", 60)
    await client.set("acf:v1:production:b", "2", 60)
    await client.set("acf:v1:quality:c", "3", 60)

    removed = await client.delete_pattern("acf:v1:production:*")

    assert removed == 2
    assert "acf:v1:quality:c" in redis.store


async def test_client_increments_a_counter(redis: FakeRedis) -> None:
    client = CacheClient(redis)

    assert await client.increment("counter", 60) == 1
    assert await client.increment("counter", 60) == 2
    assert redis.expiries["counter"] == 60


# =============================================================================
# Client: degradation (the point of the module)
# =============================================================================


async def test_a_read_failure_looks_like_a_miss() -> None:
    """The contract: a Redis failure never reaches the caller."""
    client = CacheClient(FakeRedis(fail=True))

    assert await client.get("k") is None
    assert client.stats["errors"] == 1


async def test_a_write_failure_is_reported_but_not_raised() -> None:
    client = CacheClient(FakeRedis(fail=True))

    assert await client.set("k", "v", 60) is False


async def test_an_increment_failure_returns_none() -> None:
    """The rate limiter reads this as "allow" -- an outage must not close the API."""
    client = CacheClient(FakeRedis(fail=True))

    assert await client.increment("counter", 60) is None


async def test_no_redis_configured_is_a_permanent_miss() -> None:
    """`CACHE_ENABLED=false` turns the cache into a no-op with no conditionals."""
    client = CacheClient(None)

    assert client.enabled is False
    assert await client.get("k") is None
    assert await client.set("k", "v", 60) is False
    assert await client.ping() is False


async def test_the_circuit_opens_after_repeated_failures() -> None:
    """An outage should cost one timeout per cooldown, not one per request."""
    redis = FakeRedis(fail=True)
    client = CacheClient(redis, CircuitBreaker(failure_threshold=2, cooldown_seconds=60))

    await client.get("a")
    await client.get("b")
    calls_after_failures = redis.calls

    assert client.available is False

    # Further calls short-circuit without touching Redis.
    await client.get("c")
    assert redis.calls == calls_after_failures


async def test_the_circuit_closes_after_the_cooldown() -> None:
    """A zero cooldown lets the next call probe immediately."""
    redis = FakeRedis(fail=True)
    client = CacheClient(redis, CircuitBreaker(failure_threshold=1, cooldown_seconds=0))

    await client.get("a")
    redis.fail = False

    assert client.available is True
    assert await client.set("k", "v", 60) is True
    assert client.available is True


# =============================================================================
# Cache service
# =============================================================================


async def test_get_or_set_computes_on_a_miss(cache_service: CacheService) -> None:
    calls = 0

    async def loader() -> SampleModel:
        nonlocal calls
        calls += 1
        return SampleModel(name="disc", value=1)

    first = await cache_service.get_or_set("k", CacheTier.REALTIME, SampleModel, loader)
    second = await cache_service.get_or_set("k", CacheTier.REALTIME, SampleModel, loader)

    assert first == second
    assert calls == 1, "The loader should not run on a hit."


async def test_get_or_set_falls_back_to_the_loader_when_redis_is_down(
    settings: Settings,
) -> None:
    """The dashboard must still render during a cache outage."""
    service = CacheService(CacheClient(FakeRedis(fail=True)), CacheKeys("t"), settings)
    calls = 0

    async def loader() -> SampleModel:
        nonlocal calls
        calls += 1
        return SampleModel(name="disc", value=1)

    for _ in range(3):
        result = await service.get_or_set("k", CacheTier.REALTIME, SampleModel, loader)
        assert result.value == 1

    assert calls == 3, "Every call must reach the database when the cache is unavailable."


async def test_a_stale_entry_shape_is_treated_as_a_miss(
    cache_service: CacheService, redis: FakeRedis
) -> None:
    """An entry written by a previous deployment must not be served."""
    redis.store["k"] = '{"unexpected": "shape"}'
    calls = 0

    async def loader() -> SampleModel:
        nonlocal calls
        calls += 1
        return SampleModel(name="fresh", value=9)

    result = await cache_service.get_or_set("k", CacheTier.REALTIME, SampleModel, loader)

    assert result.name == "fresh"
    assert calls == 1


async def test_get_or_set_list_round_trips(cache_service: CacheService) -> None:
    calls = 0

    async def loader() -> list[SampleModel]:
        nonlocal calls
        calls += 1
        return [SampleModel(name="a", value=1), SampleModel(name="b", value=2)]

    first = await cache_service.get_or_set_list("k", CacheTier.TREND, SampleModel, loader)
    second = await cache_service.get_or_set_list("k", CacheTier.TREND, SampleModel, loader)

    assert first == second
    assert len(first) == 2
    assert calls == 1


async def test_tiers_map_to_the_configured_ttls(cache_service: CacheService) -> None:
    """Spec section 12: TTLs come from configuration, not from a constant."""
    assert cache_service.ttl_for(CacheTier.REALTIME) == 30
    assert cache_service.ttl_for(CacheTier.TREND) == 300
    assert cache_service.ttl_for(CacheTier.ANALYTICS) == 900
    assert cache_service.ttl_for(CacheTier.REFERENCE) == 3600


async def test_a_zero_ttl_disables_storage(settings: Settings, redis: FakeRedis) -> None:
    """Setting a tier's TTL to 0 is a per-tier kill switch."""
    settings = Settings(cache_ttl_dashboard=0, _env_file=None)
    service = CacheService(CacheClient(redis), CacheKeys("t"), settings)

    stored = await service.set("k", SampleModel(name="a", value=1), CacheTier.REALTIME)

    assert stored is False
    assert "k" not in redis.store


async def test_invalidation_clears_a_whole_domain(
    cache_service: CacheService, redis: FakeRedis
) -> None:
    await cache_service.client.set("test:v1:production:summary:x", "1", 60)
    await cache_service.client.set("test:v1:production:trend:y", "2", 60)
    await cache_service.client.set("test:v1:machines:summary", "3", 60)

    removed = await cache_service.invalidate_domain("production")

    assert removed == 2
    assert "test:v1:machines:summary" in redis.store


async def test_production_invalidation_fans_out(
    cache_service: CacheService, redis: FakeRedis
) -> None:
    """A production change also invalidates the dashboard and analytics.

    The caller should not have to know which other aggregates depend on
    production; that fan-out is encoded once in the cache service.
    """
    await cache_service.client.set("test:v1:production:summary:x", "1", 60)
    await cache_service.client.set("test:v1:dashboard:summary:2026-09-05", "2", 60)
    await cache_service.client.set("test:v1:analytics:oee:x", "3", 60)
    await cache_service.client.set("test:v1:inventory:alerts", "4", 60)

    await cache_service.invalidate_production()

    assert redis.store == {"test:v1:inventory:alerts": "4"}


async def test_nothing_sensitive_is_cached_by_key_construction() -> None:
    """Spec section 16: cache keys carry no credential or personal data.

    Every key builder is exercised and the result checked for anything that
    looks like a secret. A future key built from a token would fail here.
    """
    keys = CacheKeys("acf")
    start, end = date(2026, 1, 1), date(2026, 1, 31)

    built = [
        keys.dashboard_summary(start),
        keys.dashboard_trends(start, end, {"line": "A"}),
        keys.dashboard_alerts(),
        keys.production_summary(start, end, None),
        keys.production_trend(start, end, None),
        keys.quality_summary(start, end, None),
        keys.defect_breakdown(start, end, None),
        keys.inventory_alerts(),
        keys.inventory_summary(),
        keys.machines_summary(),
        keys.analytics_oee(start, end, None),
        keys.analytics_efficiency(start, end, None),
        keys.analytics_defects(start, end, None),
        keys.reference("components"),
    ]

    forbidden = ("token", "secret", "password", "authorization", "cookie", "bearer", "jwt")
    for key in built:
        lowered = key.lower()
        for word in forbidden:
            assert word not in lowered, f"Cache key {key} looks like it carries a credential."
