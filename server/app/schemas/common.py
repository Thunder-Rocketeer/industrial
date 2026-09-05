"""Shared response envelopes and query parameter models.

Spec section 24 defines the response shapes; section 63 requires that every
externally supplied value is validated. These generic models are reused by the
domain routers added in Phase 3.
"""

from __future__ import annotations

from datetime import date
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")

# Spec section 64: bound page size so a client cannot request the whole table.
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class Envelope(BaseModel, Generic[T]):
    """Envelope for a single resource or an aggregate response."""

    data: T


class PaginationMeta(BaseModel):
    """Pagination metadata accompanying a list response."""

    page: int = Field(ge=1, description="1-based page number.")
    page_size: int = Field(ge=1, le=MAX_PAGE_SIZE, description="Items per page.")
    total: int = Field(ge=0, description="Total items matching the filter.")


class PaginatedResponse(BaseModel, Generic[T]):
    """Envelope for a paginated list response."""

    data: list[T]
    pagination: PaginationMeta


class ErrorDetail(BaseModel):
    """Client-safe error body (spec section 68).

    Deliberately carries no stack trace, SQL, path or connection detail. The
    technical cause is written to the server log against the same request ID.
    """

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable message safe to display.")
    details: dict[str, list[str]] | None = Field(
        default=None, description="Field-level validation messages, when applicable."
    )
    #: Also returned as the X-Request-ID header. Carried in the body as well so
    #: a user can quote it from an error message without opening devtools, and
    #: an operator can find the matching server log (spec section 17).
    request_id: str | None = Field(
        default=None, description="Correlation ID matching the server-side log entry."
    )


class ErrorResponse(BaseModel):
    """Top-level error envelope."""

    error: ErrorDetail


class PaginationParams(BaseModel):
    """Validated pagination query parameters."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, description="1-based page number.")
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Items per page (max {MAX_PAGE_SIZE}).",
    )

    @property
    def offset(self) -> int:
        """Zero-based offset for the database query."""
        return (self.page - 1) * self.page_size


class DateRangeParams(BaseModel):
    """Validated inclusive date range."""

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = Field(default=None, description="Inclusive start date (UTC).")
    end_date: date | None = Field(default=None, description="Inclusive end date (UTC).")

    @model_validator(mode="after")
    def _check_order(self) -> DateRangeParams:
        """Spec section 63: end_date must not precede start_date."""
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class HealthStatus(BaseModel):
    """Liveness response."""

    status: str = Field(description="'ok' when the process is serving requests.")
    app: str = Field(description="Application name.")
    version: str = Field(description="Application version.")
    environment: str = Field(description="Deployment environment.")
