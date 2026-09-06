"""Event-loop policy selection.

WHY THIS MODULE EXISTS

Python 3.8+ on Windows defaults to `ProactorEventLoop`, and psycopg's async
mode cannot run on it:

    Psycopg cannot use the 'ProactorEventLoop' to run in async mode. Please use
    a compatible event loop, for instance by setting
    'asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())'

The consequence is total on Windows: every connection attempt fails, the pool
times out, `/health/ready` reports the database unhealthy, and every endpoint
that touches PostgreSQL returns an error. Nothing in the unit suite catches it,
because those tests never open a real pool -- which is exactly why it survived
until the stack was run end to end.

SETTING THE POLICY IS NOT ENOUGH FOR UVICORN

Uvicorn 0.36+ selects the loop through a *factory*, not the policy, and
`uvicorn/loops/asyncio.py` returns `ProactorEventLoop` on win32 outright:

    def asyncio_loop_factory(use_subprocess: bool = False):
        if sys.platform == "win32" and not use_subprocess:
            return asyncio.ProactorEventLoop
        return asyncio.SelectorEventLoop

So `asyncio.set_event_loop_policy(...)` is simply ignored under uvicorn, and the
policy call below only helps other entry points that build their own loop.
Uvicorn has to be told directly, either with

    uvicorn app.main:app --loop asyncio:SelectorEventLoop

or by using `python -m app`, which does it for you. `Config.get_loop_factory`
falls through to `import_from_string(self.loop)` for any value it does not
recognise, and returns that object as the factory -- so the flag names a
zero-argument callable returning a loop, which `asyncio.SelectorEventLoop` is.

WHAT IT COSTS

`SelectorEventLoop` on Windows has two limits worth knowing:

  * it cannot spawn subprocesses on the loop (`asyncio.create_subprocess_*`);
  * `select()` caps out around 512 sockets per loop.

Neither binds this application: it spawns no subprocesses, and a single worker
holds a bounded database pool plus one Redis connection, nowhere near the cap.
On Linux -- where production runs -- this function does nothing at all, because
the default policy there is already compatible.
"""

from __future__ import annotations

import asyncio
import sys

from app.utils.logging import get_logger

logger = get_logger(__name__)

_applied = False


def configure_event_loop_policy() -> bool:
    """Install a psycopg-compatible event loop policy on Windows.

    Safe to call more than once and from any platform. Returns True when a
    policy was installed, False when the platform's default is already
    compatible.
    """
    global _applied

    if sys.platform != "win32":
        return False

    if _applied:
        return True

    policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy is None:  # pragma: no cover - not reachable on a real win32 build
        return False

    asyncio.set_event_loop_policy(policy())
    _applied = True
    logger.info(
        "runtime.event_loop_policy_set",
        extra={"policy": "WindowsSelectorEventLoopPolicy", "reason": "psycopg_async"},
    )
    return True


def loop_factory() -> asyncio.AbstractEventLoop:
    """Return an event loop psycopg can use, for uvicorn's `--loop` option.

    Referenced as `app.runtime:loop_factory`. On Windows this is a selector
    loop; everywhere else it is whatever the platform default constructor
    gives, so passing this flag is harmless on Linux.
    """
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
