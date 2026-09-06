"""Run the API server: `python -m app`.

Exists so the server starts correctly on every platform without anyone having
to remember a flag. On Windows, uvicorn defaults to `ProactorEventLoop`, which
psycopg's async mode cannot use -- the pool then fails to connect and every
database-backed endpoint errors. See `app.runtime` for the detail.

This is a convenience entry point for development and for the Windows case.
Production still runs the documented command:

    gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w $WORKERS
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from app.config import get_settings


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="python -m app", description=__doc__)
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload on source changes. Never use in production (spec section 22).",
    )
    args = parser.parse_args(argv)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        # The whole reason this module exists. Named as an import string
        # because uvicorn resolves an unrecognised --loop value that way.
        loop="app.runtime:loop_factory",
        # Do not let uvicorn interpret X-Forwarded-For.
        #
        # It does so by default, and rewrites `request.client` from the header
        # whenever the peer is in `forwarded_allow_ips` (default 127.0.0.1).
        # That silently overrides the application's own, more careful rule in
        # `app.security.rate_limit.client_identifier`, which honours the header
        # only up to `TRUSTED_PROXY_COUNT` hops and ignores it entirely when no
        # proxy is configured.
        #
        # The consequence is not theoretical: with uvicorn deciding, a client
        # can rotate X-Forwarded-For and get a fresh rate-limit bucket for every
        # request, which removes the limit altogether -- including on the
        # authentication endpoints. Verified in Phase 7 by
        # `tools/e2e_probe.py ratelimit`.
        #
        # One component owns this decision, and it is the one that knows how
        # many proxies are actually in front.
        proxy_headers=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
