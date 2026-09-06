"""CSRF protection for cookie-authenticated requests (spec sections 10 and 59).

The attack this prevents: a page on `evil.example` submits a form or fires a
`fetch` at this API. The browser attaches the session cookie automatically --
that is what cookies do -- so without a second factor the request is
indistinguishable from one the user meant to make.

Spec section 59 is explicit that CORS is not the answer. CORS governs whether
the attacker's JavaScript may *read the response*; the request still arrives and
the side effect still happens. A form post needs no CORS permission at all.

TWO INDEPENDENT CHECKS, BOTH REQUIRED

**Origin/Referer must name a configured frontend.** A cross-site request carries
the attacker's origin, and browsers do not let script forge this header.

**A CSRF token must appear in both a cookie and a header, and match.** The
double-submit pattern. An attacker can cause the cookie to be sent but cannot
read it to construct the matching header, because the same-origin policy stops
them reading a response from this API.

Either alone would be close to sufficient; both are used because they fail in
different ways. Origin checking breaks if a browser omits the header; the token
check breaks if the token leaks. Requiring both means one failure is not enough.

`SameSite=Lax` on the session cookie is a third layer, applied by the browser.
It is not relied on alone: it does not cover top-level GET navigation, and
support for it has varied.

SAFE METHODS ARE EXEMPT

`GET`, `HEAD` and `OPTIONS` skip the check because they must not change state --
which is a property of this API worth stating rather than assuming. Every Phase
3 endpoint is a read, and no `GET` in this codebase writes. If one ever did, it
would need to become a `POST`, not an exemption here.
"""

from __future__ import annotations

import hmac

from starlette.requests import Request

from app.config import Settings
from app.security.redirects import is_allowed_origin

#: Methods that must not change state, and so need no CSRF token.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Header the frontend echoes the CSRF cookie in.
CSRF_HEADER = "X-CSRF-Token"

#: Paths exempt from the token check.
#:
#: The OAuth callback is a top-level navigation *from Google*, so it carries no
#: CSRF token and its origin is not ours. It is not unprotected: the OAuth
#: `state` parameter is the CSRF defence for that specific endpoint, and it is
#: validated by Authlib before anything else happens (spec section 59).
CSRF_EXEMPT_PATH_SUFFIXES = ("/auth/google/callback",)


class CsrfError(Exception):
    """A state-changing request failed CSRF validation.

    Carries a reason for the server log. The client is told only that the
    request was rejected: naming which check failed would let an attacker
    iterate towards passing it.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def is_exempt(request: Request) -> bool:
    """Whether a request skips CSRF validation."""
    if request.method.upper() in SAFE_METHODS:
        return True
    return any(request.url.path.endswith(suffix) for suffix in CSRF_EXEMPT_PATH_SUFFIXES)


def validate(request: Request, settings: Settings) -> None:
    """Run both CSRF checks, or raise.

    Only applied to requests that actually carry a session. An unauthenticated
    POST has no cookie for an attacker to ride, so demanding a CSRF token would
    reject legitimate anonymous calls without preventing anything.

    Raises:
        CsrfError: If the request is cross-site or the token is absent or wrong.
    """
    if is_exempt(request):
        return

    # No session cookie means there is nothing to protect.
    if not request.cookies.get(settings.session_cookie_name):
        return

    # --- Check 1: the request originates from a configured frontend ----------
    # `Origin` is preferred; `Referer` is the fallback for the few cases that
    # omit it. Neither can be set by script in a browser.
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not is_allowed_origin(origin, settings):
        raise CsrfError("origin_not_allowed")

    # --- Check 2: double-submit token ----------------------------------------
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get(CSRF_HEADER)

    if not cookie_token or not header_token:
        raise CsrfError("csrf_token_missing")

    # Constant-time comparison. A timing-based comparison could in principle let
    # an attacker recover the token byte by byte; `compare_digest` costs nothing
    # and removes the question.
    if not hmac.compare_digest(cookie_token, header_token):
        raise CsrfError("csrf_token_mismatch")
