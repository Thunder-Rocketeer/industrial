"""Mint short-lived sessions for the browser test suite.

    python -m tools.mint_test_sessions ../client/e2e/.auth/sessions.json

WHY THIS EXISTS, AND WHAT IT IS NOT

The Playwright suite has to drive an authenticated application: eight pages,
six roles, filters, pagination and RBAC. None of that is reachable without a
session, and a session cannot be obtained from Google without a human typing a
password into Google's own form.

So the suite authenticates the way the spec's own session-expiry section
sanctions -- a controlled, short-lived test token -- minted here with the
application's `issue_access_token` and presented in the real session cookie.

That means everything downstream of the cookie is genuinely exercised in the
browser: signature verification, issuer and audience checks, expiry, the
revocation denylist, the user lookup, the active-account check, and RBAC.

It also means the Google handshake itself is **not** exercised: the redirect to
Google, a person authenticating, the authorization code, the token exchange and
the ID-token validation. `docs/browser-e2e.md` records those as BLOCKED and this
file is not evidence to the contrary.

Six roles are minted because RBAC has six roles to test, and one Google account
could only ever produce one of them.

OUTPUT

A JSON file the Playwright fixtures read. It contains bearer material, so it is
written into a gitignored directory and the tokens expire in fifteen minutes.
Nothing here is printed to stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.security.jwt import issue_access_token  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m tools.mint_test_sessions <output.json>", file=sys.stderr)
        return 2

    output = Path(args[0]).resolve()
    settings = get_settings()

    with psycopg.connect(settings.database_url, connect_timeout=20) as conn, conn.cursor() as cur:
        cur.execute(
            "select r.code, u.id, u.email, u.full_name from public.users u "
            "join public.roles r on r.id = u.role_id where u.is_active"
        )
        rows = cur.fetchall()

    if not rows:
        print("No active users. Run `python -m app.db.seed` first.", file=sys.stderr)
        return 1

    sessions = {}
    for role, user_id, email, name in rows:
        token, claims = issue_access_token(user_id=user_id, role=role, settings=settings)
        sessions[role] = {
            "token": token,
            "email": email,
            "name": name,
            "userId": str(user_id),
            "expiresAt": claims.expires_at.isoformat(),
        }

    payload = {
        "cookieName": settings.session_cookie_name,
        "csrfCookieName": settings.csrf_cookie_name,
        "apiBaseUrl": f"http://localhost:{settings.port}{settings.api_v1_prefix}",
        "sessions": sessions,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Roles only. Never the tokens.
    print(f"Wrote {len(sessions)} sessions to {output.name}: {', '.join(sorted(sessions))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
