"""Open redirect protection (spec section 21).

An open redirect turns a trusted domain into a phishing tool: a link to
`https://real-app.example/login?next=https://evil.example` looks legitimate,
carries the real domain in the visible URL, and lands the victim somewhere else
still believing they arrived where they intended. After an OAuth login it is
worse than usual, because the user has just typed a password and is primed to
trust whatever comes next.

The defence is to never redirect to a caller-supplied URL. Instead the caller
supplies a *path*, which is validated against the configured frontend origin and
appended to it. Anything that is not a plain in-application path is discarded
and the default destination is used -- discarded silently rather than rejected
with an error, because a bad `next` is not worth failing a successful login over,
and the audit log records it.

WHY A HAND-WRITTEN PARSER AND NOT A REGEX

The rejected forms below are each a real bypass of a naive "does it start with
a slash" check:

    //evil.example/x        scheme-relative: a browser reads this as a full URL
    /\\evil.example/x        backslashes, which some browsers normalise to slashes
    /%2f%2fevil.example     percent-encoded slashes, decoded after validation
    https://evil.example    absolute, obviously
    javascript:alert(1)     not navigation at all
    /path\\n/x               a control character, for header splitting

Each is checked explicitly, because a single regex covering all of them is
unreadable and therefore unreviewable.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from app.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

#: Characters that must never appear in a redirect path. A newline or carriage
#: return in a `Location` header is a response-splitting primitive; the null
#: byte truncates in some parsers.
_FORBIDDEN_CHARACTERS = ("\r", "\n", "\t", "\x00", "\\")

#: Schemes that are never navigation to our own frontend.
_FORBIDDEN_SCHEMES = ("javascript:", "data:", "vbscript:", "file:", "about:")

#: Longest acceptable path. A redirect target is a route, not a payload.
_MAX_PATH_LENGTH = 512


def is_safe_relative_path(candidate: str) -> bool:
    """Whether a string is a plain in-application path, safe to append.

    Safe means: begins with a single `/`, contains no control characters or
    backslashes, declares no scheme or authority, and is still all of those
    things after percent-decoding -- the decoding pass is what catches
    `/%2f%2fevil.example`, which passes every other check until a browser
    decodes it.
    """
    if not candidate or len(candidate) > _MAX_PATH_LENGTH:
        return False

    lowered = candidate.strip().lower()
    if any(lowered.startswith(scheme) for scheme in _FORBIDDEN_SCHEMES):
        return False

    # Check the raw form and the decoded form. A single decode is enough:
    # browsers do not decode repeatedly, so a double-encoded value stays inert.
    for form in (candidate, unquote(candidate)):
        if any(character in form for character in _FORBIDDEN_CHARACTERS):
            return False
        if not form.startswith("/"):
            return False
        # `//host` and `/\host` are read as scheme-relative URLs, not paths.
        if form.startswith("//"):
            return False
        # A parsed netloc or scheme means it was never a bare path.
        parsed = urlparse(form)
        if parsed.scheme or parsed.netloc:
            return False

    return True


def resolve_post_login_redirect(
    candidate: str | None,
    settings: Settings,
    *,
    default_url: str | None = None,
) -> str:
    """Return a safe absolute URL to send the browser to after login.

    Args:
        candidate: The caller-supplied destination. A path such as
            `/production?line=A`. Anything else is discarded.
        default_url: Where to go when `candidate` is absent or unsafe. Defaults
            to the configured login-success URL.

    Returns:
        An absolute URL built from the configured frontend origin. The origin
        always comes from configuration, never from the request, so the browser
        can only ever be sent to the application's own frontend.
    """
    fallback = default_url or settings.frontend_login_success_url

    if candidate is None:
        return fallback

    if not is_safe_relative_path(candidate):
        # Logged, not raised: a malformed `next` should not fail a login that
        # otherwise succeeded. The audit trail records the attempt.
        logger.warning(
            "auth.redirect_rejected",
            extra={"reason": "unsafe_redirect_target", "length": len(candidate)},
        )
        return fallback

    origin = _origin_of(fallback)
    if origin is None:
        return fallback

    return f"{origin}{candidate}"


def _origin_of(url: str) -> str | None:
    """Return the scheme and authority of a configured URL, or None.

    Used to rebase a validated path onto the frontend's origin. Returns None for
    a malformed configuration rather than guessing, so the caller falls back to
    the configured URL unchanged.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def is_allowed_origin(origin: str | None, settings: Settings) -> bool:
    """Whether an `Origin` or `Referer` header names a configured frontend.

    Used by the CSRF check. Compared against the CORS allow-list, which is the
    same set of origins the browser application is served from -- so there is
    one list to keep correct rather than two that can disagree.

    A missing origin is not allowed. Some legitimate clients omit `Origin` on
    same-origin requests, but this application's browser client is cross-origin
    (the frontend and API are on different ports), so an absent header on a
    state-changing request is not something to wave through.
    """
    if not origin:
        return False

    parsed = urlparse(origin)
    if not parsed.scheme or not parsed.netloc:
        return False

    # "*" means every browser origin is a permitted frontend.
    if "*" in settings.cors_allowed_origins:
        return True

    normalized = f"{parsed.scheme}://{parsed.netloc}"
    return normalized in {
        _origin_of(allowed) or allowed for allowed in settings.cors_allowed_origins
    }
