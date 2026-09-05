"""Tests for Redis-backed rate limiting (spec section 60).

Three properties are load-bearing and each has its own section below:

  * the limit is actually enforced, and returns 429 with a `Retry-After`
  * a client cannot forge its own identity to reset its bucket
  * a Redis outage fails *open*, because an unavailable cache must not take the
    API offline
"""

from __future__ import annotations

import pytest

from app.cache.client import CacheClient
from app.security.rate_limit import (
    RateLimiter,
    RateLimitPolicy,
    client_identifier,
    parse_rate_limit,
)
from tests.test_cache import FakeRedis


class FakeClient:
    """Minimal stand-in for `starlette.requests.Request.client`."""

    def __init__(self, host: str) -> None:
        self.host = host


class FakeRequest:
    """Minimal stand-in for a request, for identity derivation."""

    def __init__(self, host: str = "203.0.113.7", headers: dict[str, str] | None = None) -> None:
        self.client = FakeClient(host)
        self.headers = headers or {}
        self.state = type("State", (), {})()


# =============================================================================
# Policy parsing
# =============================================================================


@pytest.mark.parametrize(
    ("policy", "limit", "window"),
    [
        ("10/second", 10, 1),
        ("120/minute", 120, 60),
        ("1000/hour", 1000, 3600),
        ("5000/day", 5000, 86_400),
        ("  60 / minute  ", 60, 60),
        ("30/MINUTE", 30, 60),
    ],
)
def test_policies_parse(policy: str, limit: int, window: int) -> None:
    parsed = parse_rate_limit(policy)

    assert parsed.limit == limit
    assert parsed.window_seconds == window


@pytest.mark.parametrize(
    "policy",
    ["", "abc", "10", "/minute", "10/fortnight", "0/minute", "-5/minute", "10 minutes"],
)
def test_malformed_policies_are_rejected(policy: str) -> None:
    """Validated at startup, so a typo cannot silently disable a limit."""
    with pytest.raises(ValueError, match="Invalid rate limit"):
        parse_rate_limit(policy)


def test_window_boundaries_are_aligned() -> None:
    """Fixed windows align to the clock, so a bucket is shared across workers."""
    policy = RateLimitPolicy(limit=10, window_seconds=60, source="10/minute")

    assert policy.window_start(1_000_000_000.0) == 1_000_000_000 - (1_000_000_000 % 60)
    assert policy.reset_at(1_000_000_000.0) == policy.window_start(1_000_000_000.0) + 60


# =============================================================================
# Client identity -- the part an attacker would try to control
# =============================================================================


def test_identity_falls_back_to_the_peer_address() -> None:
    assert client_identifier(FakeRequest(host="198.51.100.4"), 0) == "ip:198.51.100.4"


def test_a_forwarded_header_is_ignored_without_a_configured_proxy() -> None:
    """The attack this prevents.

    With no proxy in front, `X-Forwarded-For` is attacker-controlled. Honouring
    it would let a client send a new value on every request and get a fresh
    bucket each time -- an unlimited rate limit that looks configured.
    """
    request = FakeRequest(host="198.51.100.4", headers={"x-forwarded-for": "1.2.3.4"})

    assert client_identifier(request, trusted_proxy_count=0) == "ip:198.51.100.4"


def test_only_the_trusted_hop_is_read_from_a_forwarded_header() -> None:
    """With one proxy, only the right-most entry is evidence.

    Everything to its left was supplied by the client. Reading the left-most
    entry -- the usual mistake -- would be reading attacker-controlled data.
    """
    request = FakeRequest(
        host="10.0.0.1",
        headers={"x-forwarded-for": "spoofed.value, 203.0.113.9"},
    )

    assert client_identifier(request, trusted_proxy_count=1) == "ip:203.0.113.9"


def test_a_short_forwarded_chain_falls_back_to_the_peer() -> None:
    """Fewer hops than configured means the header is not trustworthy."""
    request = FakeRequest(host="10.0.0.1", headers={"x-forwarded-for": "1.2.3.4"})

    assert client_identifier(request, trusted_proxy_count=2) == "ip:10.0.0.1"


def test_an_authenticated_user_is_bucketed_by_identity() -> None:
    """Phase 4 populates this, so users behind one NAT are not lumped together."""
    request = FakeRequest()
    request.state.user_id = "user-123"

    assert client_identifier(request, 0) == "user:user-123"


# =============================================================================
# Enforcement
# =============================================================================


async def test_requests_within_the_limit_are_allowed() -> None:
    limiter = RateLimiter(CacheClient(FakeRedis()))
    policy = parse_rate_limit("3/minute")

    for expected_remaining in (2, 1, 0):
        result = await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)
        assert result.allowed is True
        assert result.remaining == expected_remaining


async def test_exceeding_the_limit_is_refused() -> None:
    limiter = RateLimiter(CacheClient(FakeRedis()))
    policy = parse_rate_limit("2/minute")

    await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)
    await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)
    result = await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)

    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after >= 1


async def test_clients_have_separate_buckets() -> None:
    limiter = RateLimiter(CacheClient(FakeRedis()))
    policy = parse_rate_limit("1/minute")

    first = await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)
    second = await limiter.check(identifier="ip:2.2.2.2", scope="test", policy=policy)

    assert first.allowed is True
    assert second.allowed is True


async def test_scopes_have_separate_buckets() -> None:
    """Analytics has its own stricter limit and must not consume the general one."""
    limiter = RateLimiter(CacheClient(FakeRedis()))
    policy = parse_rate_limit("1/minute")

    first = await limiter.check(identifier="ip:1.1.1.1", scope="production", policy=policy)
    second = await limiter.check(identifier="ip:1.1.1.1", scope="analytics", policy=policy)

    assert first.allowed is True
    assert second.allowed is True


async def test_a_new_window_resets_the_allowance() -> None:
    limiter = RateLimiter(CacheClient(FakeRedis()))
    policy = parse_rate_limit("1/minute")

    first = await limiter.check(
        identifier="ip:1.1.1.1", scope="test", policy=policy, now=1_000_000_000.0
    )
    blocked = await limiter.check(
        identifier="ip:1.1.1.1", scope="test", policy=policy, now=1_000_000_010.0
    )
    next_window = await limiter.check(
        identifier="ip:1.1.1.1", scope="test", policy=policy, now=1_000_000_070.0
    )

    assert first.allowed is True
    assert blocked.allowed is False
    assert next_window.allowed is True


async def test_headers_describe_the_allowance() -> None:
    limiter = RateLimiter(CacheClient(FakeRedis()))
    policy = parse_rate_limit("5/minute")

    result = await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)
    headers = result.headers()

    assert headers["X-RateLimit-Limit"] == "5"
    assert headers["X-RateLimit-Remaining"] == "4"
    assert "X-RateLimit-Reset" in headers
    assert "Retry-After" not in headers, "Only sent when the request is refused."


async def test_a_refusal_carries_retry_after() -> None:
    limiter = RateLimiter(CacheClient(FakeRedis()))
    policy = parse_rate_limit("1/minute")

    await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)
    refused = await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)

    assert refused.allowed is False
    assert int(refused.headers()["Retry-After"]) >= 1


# =============================================================================
# Degradation
# =============================================================================


async def test_a_redis_outage_fails_open() -> None:
    """An unavailable cache must not close the API.

    Failing closed would convert a Redis outage into a total outage, which is a
    worse failure than briefly unlimited requests.
    """
    limiter = RateLimiter(CacheClient(FakeRedis(fail=True)))
    policy = parse_rate_limit("1/minute")

    for _ in range(5):
        result = await limiter.check(identifier="ip:1.1.1.1", scope="test", policy=policy)
        assert result.allowed is True
        assert result.remaining == policy.limit


async def test_no_cache_configured_fails_open() -> None:
    limiter = RateLimiter(CacheClient(None))

    result = await limiter.check(
        identifier="ip:1.1.1.1", scope="test", policy=parse_rate_limit("1/minute")
    )

    assert result.allowed is True
