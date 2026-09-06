"""Token revocation (spec section 8).

A stateless JWT stays valid until it expires. Clearing the cookie removes the
browser's copy, but a token captured beforehand still verifies, so "log out"
means nothing on its own. The fix is a denylist of revoked `jti` values that
authentication consults on every request.

TWO PROPERTIES KEEP IT BOUNDED

**Every entry expires.** The TTL is the token's own remaining lifetime -- at most
`ACCESS_TOKEN_EXPIRE_MINUTES`. Once the token would have expired anyway, the
entry is useless and Redis drops it. Spec section 8: "Do not create an unbounded
permanent blacklist."

**Only revoked tokens are stored**, never issued ones. The list is proportional
to logouts in the last few minutes, not to sessions.

THE OUTAGE TRADE-OFF, STATED PLAINLY

If Redis is unavailable the revocation check cannot run, and there are only two
options: reject every request, or accept a revoked token until it expires.

This module accepts, and logs loudly. Rejecting would mean a Redis outage logs
out every user of a dashboard that is otherwise perfectly able to serve them --
turning a cache outage into a total outage, which is exactly the failure mode
Phase 3 was built to avoid.

The exposure is bounded and small: a revoked token remains usable for at most
its remaining lifetime, 15 minutes by default and 60 by configuration limit. For
an internal factory dashboard that is the right trade. An application where
immediate revocation is a hard requirement should use short-lived tokens with a
server-side session lookup instead, and accept the per-request database read.
"""

from __future__ import annotations

from app.cache.client import CacheClient
from app.utils.logging import get_logger

logger = get_logger(__name__)

#: Key prefix. Separate from the cache namespace because this is security state,
#: not a cached computation -- a `FLUSHDB` of cached aggregates must not
#: silently un-revoke sessions, and keeping the prefixes distinct makes a
#: targeted flush possible.
REVOCATION_PREFIX = "auth:revoked:jti"

#: Marker value. The key's existence is the signal; the value is never read.
_REVOKED = "1"


class TokenRevocationStore:
    """Redis-backed denylist of revoked token identifiers."""

    def __init__(self, cache: CacheClient, prefix: str = REVOCATION_PREFIX) -> None:
        self._cache = cache
        self._prefix = prefix

    def _key(self, token_id: str) -> str:
        return f"{self._prefix}:{token_id}"

    async def revoke(self, token_id: str, ttl_seconds: int) -> bool:
        """Mark a token as revoked until it would have expired.

        Args:
            token_id: The token's `jti`.
            ttl_seconds: Remaining lifetime. A value of zero or less means the
                token has already expired, so there is nothing to revoke.

        Returns:
            True if the entry was stored. False means Redis was unavailable --
            the caller should still clear the cookie, which is what actually
            ends the session for a cooperating browser.
        """
        if ttl_seconds <= 0:
            # Already expired. Storing an entry would be a no-op with a TTL.
            return True

        stored = await self._cache.set(self._key(token_id), _REVOKED, ttl_seconds)
        if not stored:
            logger.warning(
                "auth.revocation_not_recorded",
                extra={"reason": "cache_unavailable", "ttl_seconds": ttl_seconds},
            )
        return stored

    async def is_revoked(self, token_id: str) -> bool:
        """Whether a token has been revoked.

        Returns False when Redis is unavailable. See the module docstring for
        why that is the chosen direction, and what it costs.
        """
        if not self._cache.available:
            logger.warning(
                "auth.revocation_check_skipped",
                extra={"reason": "cache_unavailable"},
            )
            return False

        return await self._cache.get(self._key(token_id)) is not None
