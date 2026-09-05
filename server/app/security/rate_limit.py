"""Redis-backed API rate limiting (spec section 60).

A fixed-window counter per (client, policy, window). Redis holds the counters so
limits hold across every Gunicorn worker and every instance -- an in-process
counter would let a client multiply its allowance by the worker count, which is
the usual reason naive rate limiting does nothing under load.

Two properties matter more than the algorithm:

**Client identity cannot be forged.** The bucket key is the peer address, and
`X-Forwarded-For` is consulted only when `TRUSTED_PROXY_COUNT` says a proxy is
genuinely in front of the application -- and then only the correct number of
entries from the right. Trusting the raw header would let any client reset its
own bucket by sending a different value each request.

**Redis being down must not close the API.** A failure fails *open*: the request
is allowed and the outage is logged. The alternative, failing closed, converts a
cache outage into a total outage.

Fixed windows are used rather than a sliding log because they cost one round
trip and no per-request storage. The known cost is burst tolerance at a window
boundary: a client can spend its allowance at the end of one window and again at
the start of the next. For protecting a dashboard API from accidental hammering
that is an acceptable trade; a sliding window would be worth the extra cost only
for endpoints where precise fairness matters.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.requests import Request

logger = get_logger(__name__)

#: "<count>/<period>", for example "120/minute".
_POLICY_PATTERN = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour|day)\s*$", re.IGNORECASE)

_PERIOD_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86_400,
}


@dataclass(frozen=True)
class RateLimitPolicy:
    """A parsed rate limit: `limit` requests per `window_seconds`."""

    limit: int
    window_seconds: int
    source: str

    def window_start(self, now: float) -> int:
        """Return the epoch second the current window began at."""
        return int(now) - (int(now) % self.window_seconds)

    def reset_at(self, now: float) -> int:
        """Return the epoch second the current window ends at."""
        return self.window_start(now) + self.window_seconds


def parse_rate_limit(policy: str) -> RateLimitPolicy:
    """Parse a policy string such as ``"120/minute"``.

    Raises:
        ValueError: If the string is malformed or the count is not positive.
            Called from configuration validation so a typo fails at startup
            rather than silently disabling a limit.
    """
    match = _POLICY_PATTERN.match(policy)
    if not match:
        raise ValueError(
            f"Invalid rate limit {policy!r}. "
            f"Expected '<count>/<period>' where period is one of "
            f"{', '.join(sorted(_PERIOD_SECONDS))}."
        )

    count = int(match.group(1))
    if count < 1:
        raise ValueError(f"Invalid rate limit {policy!r}: the count must be at least 1.")

    return RateLimitPolicy(
        limit=count,
        window_seconds=_PERIOD_SECONDS[match.group(2).lower()],
        source=policy,
    )


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of one rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: int
    #: Seconds until the window resets. Only meaningful when `allowed` is False.
    retry_after: int

    def headers(self) -> dict[str, str]:
        """Standard rate-limit headers for the response."""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_at),
        }
        if not self.allowed:
            headers["Retry-After"] = str(self.retry_after)
        return headers


def client_identifier(request: Request, trusted_proxy_count: int) -> str:
    """Derive the rate-limit bucket key for a request.

    An authenticated user id is preferred once Phase 4 populates it, so a user
    behind a shared NAT is not throttled by their neighbours. Until then the
    peer address is used.

    `X-Forwarded-For` is honoured only up to `trusted_proxy_count` entries from
    the right-hand side -- the portion a trusted proxy actually appended.
    Everything to the left was supplied by the client and is not evidence of
    anything. With no proxy configured the header is ignored completely.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"

    if trusted_proxy_count > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if len(hops) >= trusted_proxy_count:
            # The right-most entry was appended by the closest trusted proxy.
            return f"ip:{hops[-trusted_proxy_count]}"

    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


class RateLimiter:
    """Fixed-window rate limiter backed by Redis.

    Args:
        cache: The shared cache client. Its circuit breaker and failure handling
            are reused, so a Redis outage degrades the limiter the same way it
            degrades caching.
    """

    def __init__(self, cache: object) -> None:
        self._cache = cache

    async def check(
        self,
        *,
        identifier: str,
        scope: str,
        policy: RateLimitPolicy,
        now: float | None = None,
    ) -> RateLimitResult:
        """Consume one unit of the client's allowance.

        Returns an allowing result if Redis is unavailable: an outage must not
        take the API offline.
        """
        now = now if now is not None else time.time()
        window_start = policy.window_start(now)
        reset_at = window_start + policy.window_seconds
        key = f"ratelimit:{scope}:{identifier}:{window_start}"

        count = await self._cache.increment(key, ttl_seconds=policy.window_seconds)

        if count is None:
            # Redis unavailable. Fail open, and say so.
            logger.warning(
                "ratelimit.unavailable",
                extra={"scope": scope, "reason": "cache_unavailable"},
            )
            return RateLimitResult(
                allowed=True,
                limit=policy.limit,
                remaining=policy.limit,
                reset_at=reset_at,
                retry_after=0,
            )

        allowed = count <= policy.limit
        return RateLimitResult(
            allowed=allowed,
            limit=policy.limit,
            remaining=max(0, policy.limit - count),
            reset_at=reset_at,
            retry_after=max(1, reset_at - int(now)) if not allowed else 0,
        )
