"""Session and CSRF cookie handling (spec sections 7 and 55.4).

Two cookies, with deliberately different visibility:

**The session cookie** carries the access token and is `HttpOnly`. Application
JavaScript cannot read it, which removes the entire class of XSS token theft --
a script injected into the page can still make requests as the user, but it
cannot exfiltrate the token to be replayed later from somewhere else. This is
why spec section 55.4 forbids `localStorage`: anything JavaScript can read, an
injected script can read.

**The CSRF cookie** is deliberately *not* `HttpOnly`, because the double-submit
pattern requires the frontend to read it and echo it in a header. It is not a
secret in the same sense: it protects against a cross-site form post, and a
cross-site attacker cannot read it thanks to the same-origin policy. Marking it
`HttpOnly` would break the pattern without adding protection.

Every attribute is environment-configurable so that development over HTTP works
without weakening production, and the production configuration check refuses to
start if `COOKIE_SECURE` is off.
"""

from __future__ import annotations

import secrets

from fastapi import Response

from app.config import Settings

#: Bytes of entropy in a CSRF token. 32 bytes is 256 bits -- far beyond
#: guessable, and short enough to sit comfortably in a header.
CSRF_TOKEN_BYTES = 32


def _cookie_kwargs(settings: Settings) -> dict[str, object]:
    """Shared cookie attributes.

    `domain` is omitted when unset rather than passed as an empty string: an
    empty domain would be sent literally and produce a cookie no browser
    accepts. Leaving it out gives a host-only cookie, which is the tighter
    default.
    """
    kwargs: dict[str, object] = {
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "path": "/",
    }
    if settings.cookie_domain:
        kwargs["domain"] = settings.cookie_domain
    return kwargs


def set_session_cookie(
    response: Response,
    token: str,
    settings: Settings,
    max_age_seconds: int | None = None,
) -> None:
    """Attach the session cookie.

    `max_age` matches the token's lifetime, so the browser discards the cookie
    at roughly the moment the token stops verifying. Without it the cookie would
    be a session cookie that outlives its own contents, and every request after
    expiry would carry a token only to be rejected.
    """
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age_seconds or settings.access_token_expire_minutes * 60,
        # The point of the whole design: unreadable from JavaScript.
        httponly=True,
        **_cookie_kwargs(settings),
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Remove the session cookie.

    The attributes must match those used to set it -- a browser treats a cookie
    with a different path or domain as a different cookie and will not remove
    it, leaving the session apparently un-logged-out.
    """
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        domain=settings.cookie_domain or None,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def generate_csrf_token() -> str:
    """Return a fresh CSRF token.

    `secrets.token_urlsafe` rather than `random`: this value must be
    unpredictable, and the `random` module is seeded predictably.
    """
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def set_csrf_cookie(response: Response, token: str, settings: Settings) -> None:
    """Attach the CSRF cookie.

    Readable by JavaScript on purpose -- see the module docstring. Its lifetime
    matches the session so the two expire together; a CSRF token outliving its
    session would fail every check and look like a bug.
    """
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=False,
        **_cookie_kwargs(settings),
    )


def clear_csrf_cookie(response: Response, settings: Settings) -> None:
    """Remove the CSRF cookie."""
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path="/",
        domain=settings.cookie_domain or None,
        secure=settings.cookie_secure,
        httponly=False,
        samesite=settings.cookie_samesite,
    )


def read_session_token(cookies: dict[str, str], settings: Settings) -> str | None:
    """Extract the access token from the request cookies.

    The only place the token is read from. Deliberately not accepting an
    `Authorization: Bearer` header as well: two accepted locations means two
    code paths to secure, and the browser client has no use for the header form.
    """
    token = cookies.get(settings.session_cookie_name)
    return token.strip() if token and token.strip() else None
