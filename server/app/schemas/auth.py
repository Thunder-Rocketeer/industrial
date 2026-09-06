"""Authentication response models (spec section 14).

The governing rule for this module is what these models *omit*. Spec section 14
lists what must never be returned -- the Google client secret, the JWT signing
key, provider access tokens, refresh tokens, internal security metadata -- and
the way to guarantee that is a model that has no field for any of them. A
response built from an explicit model cannot leak a column someone adds to the
users table later.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import RoleCode


class CurrentUser(BaseModel):
    """The authenticated user, as the frontend sees them.

    Everything here is either display data or an authorization fact the frontend
    needs to decide what to *show*. It decides nothing about access: the backend
    has already enforced that, and `permissions` is a convenience for hiding
    buttons, never a grant.
    """

    id: UUID
    email: str = Field(description="Verified email address from the identity provider.")
    name: str = Field(description="Display name.")
    role: RoleCode = Field(description="Role code, e.g. FACTORY_MANAGER.")
    role_label: str = Field(description="Human-readable role name, e.g. Factory Manager.")
    avatar_url: str | None = Field(
        default=None, description="Profile image URL. Always https, or absent."
    )
    is_active: bool = Field(description="False accounts cannot call protected endpoints.")
    last_login_at: datetime | None = Field(default=None, description="Previous sign-in (UTC).")

    permissions: list[str] = Field(
        default_factory=list,
        description=(
            "Permissions this role holds. For deciding what the UI offers, never "
            "for authorization -- the backend enforces every check independently."
        ),
    )


class LoginChallenge(BaseModel):
    """Where to send the browser to begin sign-in.

    Returned by the JSON form of the login endpoint so a single-page frontend
    can navigate deliberately rather than following a redirect it did not
    expect.
    """

    authorization_url: str = Field(description="Google authorization endpoint, with parameters.")


class LogoutResult(BaseModel):
    """Outcome of a logout."""

    logged_out: bool = Field(description="Always true; logout is idempotent.")
    session_revoked: bool = Field(
        description=(
            "Whether the token was added to the revocation store. False means "
            "Redis was unavailable: the cookie is cleared regardless, and the "
            "token expires on its own shortly."
        )
    )


class CsrfToken(BaseModel):
    """A CSRF token for the double-submit check.

    Also set as a readable cookie. Returned in the body as well so a frontend
    can seed its state without parsing `document.cookie`.
    """

    csrf_token: str = Field(description="Echo this in the X-CSRF-Token header.")


class AuthStatus(BaseModel):
    """Whether authentication is usable, for diagnostics.

    Reports configuration, never a credential -- `google_configured` says
    whether a client id and secret are present, and nothing about their values.
    """

    authentication_required: bool = Field(
        description="Whether protected endpoints demand a session."
    )
    google_configured: bool = Field(
        description="Whether Google OAuth credentials are configured on the server."
    )
    login_url: str = Field(description="Where the browser should begin sign-in.")
