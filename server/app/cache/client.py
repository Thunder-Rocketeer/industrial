"""Redis client with graceful degradation (spec section 11).

The contract this module exists to guarantee: **a Redis failure must never
surface to a caller.** Every operation returns `None` or `False` instead of
raising, so a service that cannot reach the cache simply reads the database and
serves a slightly slower but entirely correct response.

Two things make that guarantee real rather than aspirational.

**Short timeouts.** The cache exists to make requests faster. A one-second
command timeout means the worst case for an unhealthy Redis is one second of
added latency, not the thirty-second default that would make the dashboard feel
broken.

**A circuit breaker.** Without one, every request during an outage pays the full
timeout — turning a cache outage into a latency outage. After a few consecutive
failures the breaker opens and calls return immediately for a cooldown period,
then a single request is allowed through to test recovery. So an outage costs
one timeout per cooldown window rather than one per request.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis

logger = get_logger(__name__)


class CircuitBreaker:
    """Stops calling a failing dependency for a cooldown period.

    Closed by default. It opens after `failure_threshold` consecutive failures
    and closes again on the first success after the cooldown elapses.
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0) -> None:
        self._failure_threshold = max(1, failure_threshold)
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        """True while calls should be skipped."""
        if self._opened_at is None:
            return False
        # Once the cooldown has elapsed, allow one probe through. The breaker
        # stays nominally open until that probe reports back.
        return time.monotonic() - self._opened_at < self._cooldown_seconds

    def record_success(self) -> None:
        if self._opened_at is not None:
            logger.info("cache.circuit_closed")
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold and self._opened_at is None:
            self._opened_at = time.monotonic()
            logger.warning(
                "cache.circuit_opened",
                extra={
                    "consecutive_failures": self._consecutive_failures,
                    "cooldown_seconds": self._cooldown_seconds,
                },
            )
        elif self._opened_at is not None:
            # A probe failed; restart the cooldown.
            self._opened_at = time.monotonic()


class CacheClient:
    """Async Redis wrapper that never raises to its caller.

    Args:
        redis: A connected `redis.asyncio.Redis`, or `None` to disable caching
            entirely. Passing `None` is how tests and the `CACHE_ENABLED=false`
            switch turn the cache into a no-op without conditionals at every
            call site.
        breaker: Circuit breaker. One is created if not supplied.
    """

    def __init__(
        self,
        redis: Redis | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._redis = redis
        self._breaker = breaker or CircuitBreaker()
        self._hits = 0
        self._misses = 0
        self._errors = 0

    @property
    def enabled(self) -> bool:
        """True when a backing Redis is configured."""
        return self._redis is not None

    @property
    def available(self) -> bool:
        """True when the cache should be consulted right now."""
        return self._redis is not None and not self._breaker.is_open

    @property
    def stats(self) -> dict[str, int]:
        """Counters for logging and the readiness endpoint."""
        return {"hits": self._hits, "misses": self._misses, "errors": self._errors}

    def _handle_failure(self, operation: str, exc: Exception) -> None:
        """Record a failure without letting it escape.

        Only the exception type is logged, never its message: a Redis error can
        carry the connection string, which would put credentials in the log
        (spec section 18).
        """
        self._errors += 1
        self._breaker.record_failure()
        logger.warning(
            "cache.operation_failed",
            extra={"operation": operation, "error_type": type(exc).__name__},
        )

    async def get(self, key: str) -> str | None:
        """Return a cached value, or `None` on miss, outage or open breaker."""
        if not self.available:
            return None
        try:
            value = await self._redis.get(key)
        except Exception as exc:
            self._handle_failure("get", exc)
            return None

        self._breaker.record_success()
        if value is None:
            self._misses += 1
            return None

        self._hits += 1
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Store a value. Returns False if it could not be stored."""
        if not self.available:
            return False
        if ttl_seconds <= 0:
            # A non-expiring entry in a cache is a memory leak with extra steps.
            return False
        try:
            await self._redis.set(key, value, ex=ttl_seconds)
        except Exception as exc:
            self._handle_failure("set", exc)
            return False

        self._breaker.record_success()
        return True

    async def delete(self, *keys: str) -> int:
        """Delete keys. Returns the number removed, or 0 on failure."""
        if not self.available or not keys:
            return 0
        try:
            removed = await self._redis.delete(*keys)
        except Exception as exc:
            self._handle_failure("delete", exc)
            return 0

        self._breaker.record_success()
        return int(removed)

    async def delete_pattern(self, pattern: str) -> int:
        """Delete every key matching a glob.

        Uses SCAN rather than KEYS: `KEYS` blocks the Redis event loop for the
        whole scan, which on a shared instance stalls every other client.
        """
        if not self.available:
            return 0
        try:
            removed = 0
            batch: list[str] = []
            async for key in self._redis.scan_iter(match=pattern, count=500):
                batch.append(key)
                if len(batch) >= 500:
                    removed += int(await self._redis.delete(*batch))
                    batch.clear()
            if batch:
                removed += int(await self._redis.delete(*batch))
        except Exception as exc:
            self._handle_failure("delete_pattern", exc)
            return 0

        self._breaker.record_success()
        return removed

    async def increment(self, key: str, ttl_seconds: int) -> int | None:
        """Increment a counter, setting its expiry on first use.

        Backs the rate limiter. Returns `None` when Redis is unavailable, which
        the limiter treats as "allow" -- an outage must not close the API.

        The INCR and EXPIRE are pipelined so the counter cannot be left without
        an expiry if the connection drops between them, which would make the
        limit permanent for that client.
        """
        if not self.available:
            return None
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(key, 1)
                pipe.expire(key, ttl_seconds)
                results = await pipe.execute()
        except Exception as exc:
            self._handle_failure("increment", exc)
            return None

        self._breaker.record_success()
        return int(results[0])

    async def ping(self) -> bool:
        """Check connectivity, for the readiness endpoint."""
        if self._redis is None:
            return False
        try:
            await self._redis.ping()
        except Exception as exc:
            self._handle_failure("ping", exc)
            return False

        self._breaker.record_success()
        return True


async def create_redis(settings: object) -> Redis | None:
    """Build a Redis client from settings, or `None` if caching is off.

    Connection failures are not raised: the application must start whether or
    not Redis is reachable, and the client degrades from there.
    """
    if not getattr(settings, "cache_enabled", True):
        logger.info("cache.disabled", extra={"reason": "cache_enabled=false"})
        return None

    url = getattr(settings, "redis_url", "").strip()
    if not url:
        logger.info("cache.disabled", extra={"reason": "redis_url_not_set"})
        return None

    try:
        from redis.asyncio import Redis

        client = Redis.from_url(
            url,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_command_timeout_seconds,
            retry_on_timeout=False,
            health_check_interval=30,
        )
        await client.ping()
    except Exception as exc:
        # Never log the URL: it can carry a password.
        logger.warning(
            "cache.unavailable_at_startup",
            extra={"error_type": type(exc).__name__},
        )
        return None

    logger.info("cache.connected")
    return client
