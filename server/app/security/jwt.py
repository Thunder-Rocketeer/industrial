"""Application JWT issuing and validation (spec sections 55 and 32).

The one rule that matters most here, stated first: **the accepted signing
algorithm comes from configuration, never from the token.**

A JWT carries its own `alg` header, and a library that trusts it can be talked
into two classic attacks. `alg: none` asks the verifier to skip signature
checking entirely. Algorithm confusion asks an RS256 verifier to treat the
*public* key as an HMAC secret, so a token signed with the public key --
which is public -- verifies. Both are defeated by passing an explicit
`algorithms=[...]` list to the decoder and never reading the header, which is
what `decode_access_token` does.

PyJWT is used rather than Authlib's JOSE module. Authlib handles the OIDC side
of the flow (where it validates Google's ID token against Google's JWKS), and
PyJWT handles the application's own tokens. Two libraries for two jobs is
deliberate: the application tokens need strict, explicit, easily-audited
validation, and PyJWT's `decode` makes every check a visible argument.

CLAIMS ARE MINIMAL (spec section 6)

    sub   the application user's UUID
    iss   this application
    aud   this API
    iat   issued at
    exp   expires
    jti   unique token id, so it can be revoked
    typ   token purpose, so an access token cannot be replayed as something else
    role  the user's role code

`role` is included, and that is a deliberate trade with a stated cost: it saves
a database read on every request, but a role change does not take effect until
the token expires -- at most `ACCESS_TOKEN_EXPIRE_MINUTES`. That window is
acceptable because the token is short-lived, and because the revocation store
gives an operator a way to end a session immediately. Nothing else goes in:
no email, no name, no provider token. A JWT is signed, not encrypted, and
anyone holding it can read every claim.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import Settings

UTC = timezone.utc

#: Signing algorithms this application will accept.
#:
#: An explicit allow-list, checked against configuration at startup. `none` is
#: absent and can never be added: the guard below rejects it by name regardless
#: of what is configured.
SUPPORTED_ALGORITHMS = frozenset({"HS256", "HS384", "HS512", "RS256", "ES256"})

#: Algorithms that must never be accepted, whatever the configuration says.
FORBIDDEN_ALGORITHMS = frozenset({"none", "None", "NONE", ""})

#: Value of the `typ` claim on an access token. A token minted for one purpose
#: must not be usable for another, so the purpose is signed rather than implied.
ACCESS_TOKEN_TYPE = "access"

#: Claims that must be present. Listed for PyJWT's `require` option, so a token
#: missing any of them is rejected structurally rather than by a later
#: `KeyError` somewhere in a dependency.
REQUIRED_CLAIMS = ("sub", "iss", "aud", "exp", "iat", "jti", "typ")

#: Tolerance for clock skew between the issuing and verifying process. Thirty
#: seconds is enough for ordinary NTP drift and short enough that it does not
#: meaningfully extend a token's life.
LEEWAY_SECONDS = 30


class TokenError(Exception):
    """Base class for every token failure.

    Carries a stable `code` so the route layer can map it to a response without
    matching on message text, and a `message` written to be safe to return to a
    client -- it says the token is unusable, never why in a way that would help
    someone forge a better one.
    """

    code = "TOKEN_INVALID"
    message = "Your session is not valid. Please sign in again."


class TokenExpiredError(TokenError):
    """The token is past its `exp`.

    Distinguished from other failures because it is the one that happens to
    legitimate users constantly, and the frontend handles it differently: a
    quiet redirect to sign in rather than an error.
    """

    code = "TOKEN_EXPIRED"
    message = "Your session has expired. Please sign in again."


class TokenRevokedError(TokenError):
    """The token's `jti` is in the revocation store."""

    code = "TOKEN_REVOKED"
    message = "Your session has been ended. Please sign in again."


class TokenConfigurationError(RuntimeError):
    """The application's own JWT configuration is unusable.

    Not a `TokenError`: this is a deployment fault, not a client fault, and it
    must surface as a 500 rather than a 401. Telling a user to sign in again
    when the server has no signing key would send them round a loop forever.
    """


@dataclass(frozen=True)
class TokenClaims:
    """The validated contents of an access token."""

    subject: uuid.UUID
    role: str
    token_id: str
    issued_at: datetime
    expires_at: datetime

    @property
    def seconds_remaining(self) -> int:
        """Seconds until expiry, floored at zero.

        Used to size the revocation entry's TTL: an entry only needs to outlive
        the token it revokes.
        """
        remaining = (self.expires_at - datetime.now(tz=UTC)).total_seconds()
        return max(0, int(remaining))


def resolve_algorithm(settings: Settings) -> str:
    """Return the configured signing algorithm, or refuse.

    Raises:
        TokenConfigurationError: If the configured algorithm is forbidden or
            unsupported. Checked at issue and verify time rather than only at
            startup, so a setting mutated at runtime cannot widen what is
            accepted.
    """
    algorithm = (settings.jwt_algorithm or "").strip()

    if algorithm in FORBIDDEN_ALGORITHMS:
        raise TokenConfigurationError(
            f"JWT_ALGORITHM={algorithm!r} disables signature verification and is refused."
        )
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise TokenConfigurationError(
            f"JWT_ALGORITHM={algorithm!r} is not supported. "
            f"Choose one of {sorted(SUPPORTED_ALGORITHMS)}."
        )
    return algorithm


def _signing_key(settings: Settings) -> str:
    """Return the key used to sign, refusing an empty one.

    An empty secret would produce tokens anyone can forge. Failing here rather
    than signing with `""` is the difference between an outage and a silent
    total compromise.
    """
    key = settings.secret_key
    if not key:
        raise TokenConfigurationError(
            "SECRET_KEY is not set, so tokens cannot be signed. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )
    return key


def issue_access_token(
    *,
    user_id: uuid.UUID,
    role: str,
    settings: Settings,
    issued_at: datetime | None = None,
    token_id: str | None = None,
) -> tuple[str, TokenClaims]:
    """Mint a short-lived access token.

    Args:
        user_id: The application user's UUID. Becomes `sub`.
        role: The user's role code, resolved server-side. Never from a request.
        issued_at: Overridable for tests; defaults to now.
        token_id: Overridable for tests; defaults to a fresh UUID4.

    Returns:
        The encoded token and its claims. The claims are returned so the caller
        can size the cookie's `max_age` and record the `jti` without decoding
        what it just encoded.
    """
    algorithm = resolve_algorithm(settings)
    key = _signing_key(settings)

    now = issued_at or datetime.now(tz=UTC)
    expires = now + timedelta(minutes=settings.access_token_expire_minutes)
    jti = token_id or str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": jti,
        "typ": ACCESS_TOKEN_TYPE,
        "role": role,
    }

    token = jwt.encode(payload, key, algorithm=algorithm)
    claims = TokenClaims(
        subject=user_id,
        role=role,
        token_id=jti,
        issued_at=now,
        expires_at=expires,
    )
    return token, claims


def decode_access_token(token: str, settings: Settings) -> TokenClaims:
    """Validate a token and return its claims.

    Checks, in the order PyJWT applies them: the signature against the
    configured algorithm only, then `exp`, `iat`, `aud` and `iss`, then that
    every required claim is present, and finally that the token was minted as an
    access token and carries a usable subject and role.

    Raises:
        TokenExpiredError: The token is past `exp`.
        TokenError: Any other validation failure.
        TokenConfigurationError: The application's own configuration is unusable.
    """
    algorithm = resolve_algorithm(settings)
    key = _signing_key(settings)

    if not token or not token.strip():
        raise TokenError

    try:
        payload = jwt.decode(
            token,
            key,
            # The critical argument. An explicit list means the `alg` header is
            # matched against it rather than obeyed, which is what defeats both
            # `alg: none` and algorithm confusion.
            algorithms=[algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            leeway=LEEWAY_SECONDS,
            options={
                "require": list(REQUIRED_CLAIMS),
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError from exc
    except jwt.PyJWTError as exc:
        # Every other PyJWT failure -- bad signature, wrong issuer, wrong
        # audience, missing claim, malformed token -- collapses to one error.
        # The distinction matters to the server log, not to the client: telling
        # a caller *which* check failed helps them iterate towards a token that
        # passes.
        raise TokenError from exc

    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise TokenError

    try:
        subject = uuid.UUID(str(payload["sub"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise TokenError from exc

    role = payload.get("role")
    if not isinstance(role, str) or not role:
        raise TokenError

    return TokenClaims(
        subject=subject,
        role=role,
        token_id=str(payload["jti"]),
        issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
