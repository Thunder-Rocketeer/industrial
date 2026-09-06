"""Google OAuth 2.0 / OpenID Connect via Authlib (spec section 1).

Spec section 1 is explicit: "Do NOT implement the OAuth authorization code flow
manually. Use Authlib." This module is a thin wrapper around Authlib's Starlette
integration, and the thinness is the point -- every security-critical step is
handled by the library rather than reimplemented here.

WHAT AUTHLIB DOES, THAT THIS MODULE DELIBERATELY DOES NOT

  * generates and stores the `state`, and rejects a callback whose state does
    not match the one it issued -- this is the CSRF defence for the callback
  * generates the `nonce`, puts it in the authorization request, and verifies it
    appears in the returned ID token -- this is what stops an ID token obtained
    elsewhere being replayed into our callback
  * generates the PKCE `code_verifier` and `code_challenge`
  * exchanges the authorization code server-side, over TLS, with the client
    secret -- the code never passes through the browser as anything but an
    opaque value
  * fetches Google's JWKS and verifies the ID token's signature against it
  * validates `iss`, `aud`, `exp` and `iat` on the ID token

Reimplementing any of that would mean reimplementing a security protocol, which
is what the specification forbids and what goes wrong.

DISCOVERY RATHER THAN HARD-CODED ENDPOINTS

The client is registered with Google's discovery document rather than literal
authorization and token URLs. Google rotates its signing keys and has changed
endpoint URLs before; discovery means the application follows both without a
release. The issuer is still pinned in configuration and verified.

GRACEFUL ABSENCE

Google credentials are frequently not configured in development. This module
reports that as a fact (`is_configured`) rather than raising at import, so the
rest of the API keeps working and only the login endpoints report themselves
unavailable (spec section 35).
"""

from __future__ import annotations

from typing import Any

from authlib.integrations.starlette_client import OAuth, OAuthError

from app.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

#: Registered client name, used to look the client up on the registry.
GOOGLE_CLIENT_NAME = "google"

#: Google's OIDC discovery document.
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

#: Scopes requested.
#:
#: Minimal, per spec section 1: `openid` for the ID token, `email` and `profile`
#: for the display fields on `/auth/me`. No Drive, no Calendar, no offline
#: access -- the application never calls a Google API after login, so a refresh
#: token would be a credential with no purpose and real custody obligations.
GOOGLE_SCOPES = "openid email profile"


class OAuthNotConfiguredError(RuntimeError):
    """Google credentials are absent.

    Raised only when a login is actually attempted, never at import, so an
    unconfigured development environment still serves every other endpoint.
    """


class OAuthIdentityError(Exception):
    """The callback did not yield a usable, verified Google identity.

    Deliberately coarse. The distinctions -- bad state, bad nonce, expired code,
    unverified email -- are recorded in the audit log and the server log; the
    client is told only that sign-in failed, because a caller iterating against
    a detailed error is exactly the threat.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class GoogleIdentity:
    """A verified Google identity, reduced to what the application stores.

    Constructed only from claims Authlib has already verified against Google's
    signing keys. Nothing here comes from a query parameter, and nothing the
    browser sent is trusted (spec section 1: "Do not trust an email address
    merely because it was supplied by the browser").
    """

    __slots__ = ("email", "email_verified", "name", "picture", "subject")

    def __init__(
        self,
        *,
        subject: str,
        email: str,
        email_verified: bool,
        name: str,
        picture: str | None,
    ) -> None:
        self.subject = subject
        self.email = email
        self.email_verified = email_verified
        self.name = name
        self.picture = picture

    def __repr__(self) -> str:
        # The email is deliberately absent: this object appears in log lines and
        # tracebacks, and an address there is personal data (spec section 18).
        return f"GoogleIdentity(subject={self.subject[:6]}..., verified={self.email_verified})"


def is_configured(settings: Settings) -> bool:
    """Whether Google credentials are present."""
    return bool(settings.google_client_id and settings.google_client_secret)


def build_oauth_registry(settings: Settings) -> OAuth:
    """Create the Authlib registry with Google registered.

    Returned even when unconfigured -- the registry is harmless without
    credentials, and the login route checks `is_configured` before using it.
    """
    oauth = OAuth()

    if not is_configured(settings):
        logger.info(
            "auth.google_not_configured",
            extra={"reason": "client_id_or_secret_missing"},
        )
        return oauth

    oauth.register(
        name=GOOGLE_CLIENT_NAME,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url=GOOGLE_DISCOVERY_URL,
        client_kwargs={
            "scope": GOOGLE_SCOPES,
            # PKCE. Not strictly required for a confidential client that keeps
            # its secret server-side, but it costs nothing and closes
            # authorization-code interception if the secret is ever exposed.
            "code_challenge_method": "S256",
        },
    )
    logger.info("auth.google_configured")
    return oauth


def extract_identity(token: dict[str, Any]) -> GoogleIdentity:
    """Turn Authlib's verified token response into a `GoogleIdentity`.

    The `userinfo` block is the parsed ID token: Authlib has already verified
    its signature, issuer, audience, expiry and nonce by the time this runs.
    What is left is to insist the claims are usable.

    Raises:
        OAuthIdentityError: If a required claim is missing, or the email is
            unverified.
    """
    claims = token.get("userinfo") or {}

    subject = claims.get("sub")
    if not subject or not isinstance(subject, str):
        raise OAuthIdentityError("missing_subject")

    email = claims.get("email")
    if not email or not isinstance(email, str):
        raise OAuthIdentityError("missing_email")

    # An unverified email must not be accepted. Google will issue an ID token
    # for an account whose address it has not confirmed, and treating that as an
    # identity would let someone register an address they do not control and
    # inherit whatever the account-restriction rules grant it.
    if not claims.get("email_verified", False):
        raise OAuthIdentityError("email_not_verified")

    picture = claims.get("picture")
    if picture is not None and not (isinstance(picture, str) and picture.startswith("https://")):
        # Stored and later rendered by the frontend; anything but https is
        # discarded rather than trusted. The database enforces this too.
        picture = None

    return GoogleIdentity(
        subject=subject,
        email=email.strip().lower(),
        email_verified=True,
        name=str(claims.get("name") or email.split("@")[0]),
        picture=picture,
    )


def describe_oauth_error(error: OAuthError) -> str:
    """Reduce an Authlib error to a short reason code for logging.

    The exception's own message can contain the authorization code or parts of
    the token response, neither of which belongs in a log (spec section 22).
    """
    return getattr(error, "error", None) or "oauth_error"
