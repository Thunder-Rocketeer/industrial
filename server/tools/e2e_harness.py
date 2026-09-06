"""Shared scaffolding for the live end-to-end probe.

Separated from the suites so the authentication story has one place to live and
be read, because it is the part most easily misread.

HOW THE PROBE AUTHENTICATES, AND WHAT THAT DOES NOT PROVE

Sessions are minted with the application's own `issue_access_token` and sent in
the real session cookie. Everything downstream of that cookie is therefore
genuinely exercised: signature verification, issuer and audience checks,
expiry, the revocation denylist, the user lookup, the active-account check and
RBAC all run exactly as they do in production.

What this does **not** exercise is the Google handshake -- the redirect to
Google, a human authenticating, the authorization code, the token exchange and
ID-token validation. That needs a browser and a real Google account. The probe
never claims otherwise; the OAuth checks it does run cover only the parts
reachable without one (that the authorization redirect is well formed, and that
hostile `next` values cannot escape the origin).

Tokens are minted in-process. None is written to disk or logged.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.security.jwt import issue_access_token

DEFAULT_BASE = "http://127.0.0.1:8000/api/v1"


@dataclass
class Results:
    """Accumulates checks so one failure does not stop the run."""

    passed: int = 0
    failed: int = 0
    notes: list[str] = field(default_factory=list)

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  [PASS] {label}" + (f" - {detail}" if detail else ""))
        else:
            self.failed += 1
            print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))
        return bool(ok)

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  [NOTE] {text}")

    def summary(self) -> int:
        print("=" * 70)
        print(f"{self.passed} passed, {self.failed} failed")
        for note in self.notes:
            print(f"  note: {note}")
        return 1 if self.failed else 0


def seeded_users() -> dict[str, uuid.UUID]:
    """Map role code to user id, read from the live database."""
    settings = get_settings()
    users: dict[str, uuid.UUID] = {}
    with psycopg.connect(settings.database_url, connect_timeout=20) as conn, conn.cursor() as cur:
        cur.execute(
            "select r.code, u.id from public.users u "
            "join public.roles r on r.id = u.role_id where u.is_active"
        )
        for code, user_id in cur.fetchall():
            users[code] = user_id
    return users


def client_for(role: str, users: dict[str, uuid.UUID], base: str) -> httpx.Client:
    """An HTTP client carrying a real session cookie for `role`."""
    settings = get_settings()
    token, _ = issue_access_token(user_id=users[role], role=role, settings=settings)
    client = httpx.Client(base_url=base, timeout=45.0)
    client.cookies.set(settings.session_cookie_name, token, domain="127.0.0.1")
    return client


def token_client(token: str, base: str) -> httpx.Client:
    """A client carrying an arbitrary token, for the rejection cases."""
    settings = get_settings()
    client = httpx.Client(base_url=base, timeout=45.0)
    client.cookies.set(settings.session_cookie_name, token, domain="127.0.0.1")
    return client


def anon_client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=45.0)


def parse_limit(spec: str) -> tuple[int, int]:
    """Parse a rate-limit spec such as `120/minute` into (count, seconds)."""
    count, _, unit = spec.partition("/")
    seconds = {"second": 1, "minute": 60, "hour": 3600}.get(unit.strip(), 60)
    return int(count), seconds
