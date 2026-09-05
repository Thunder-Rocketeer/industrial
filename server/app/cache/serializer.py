"""Cache value serialization.

Cached values are Pydantic models and plain aggregates, so JSON is the right
wire format: it is inspectable with `redis-cli`, survives a schema addition
without a decode error, and carries no code-execution risk.

Pickle is deliberately not used. Unpickling data from a shared store is remote
code execution if anything can write to that store, and the convenience it buys
here is nil.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel

TModel = TypeVar("TModel", bound=BaseModel)


class CacheSerializationError(RuntimeError):
    """Raised when a value cannot be encoded for the cache."""


def _default(value: Any) -> Any:
    """Encode the types that appear in query results but not in JSON."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        # Always ISO-8601 with the offset, so UTC survives the round trip.
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        # float, not str: these are quantities and rates that the frontend
        # charts numerically. Precision beyond a float is not meaningful for
        # a dashboard aggregate.
        return float(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"Cannot serialize {type(value).__name__} for the cache.")


def dumps(value: Any) -> str:
    """Encode a value for storage.

    Raises:
        CacheSerializationError: If the value contains something unencodable.
            Raised rather than silently skipping the write, because a value the
            cache cannot hold is a bug worth surfacing in development.
    """
    try:
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        return json.dumps(value, default=_default, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise CacheSerializationError(str(exc)) from exc


def loads(raw: str | bytes) -> Any:
    """Decode a stored value.

    Raises:
        CacheSerializationError: If the payload is not valid JSON. Callers treat
            this as a miss: a corrupt entry should cost one database read, not
            an error response.
    """
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise CacheSerializationError(str(exc)) from exc


def load_model(raw: str | bytes, model: type[TModel]) -> TModel:
    """Decode a stored value into a Pydantic model.

    Validating on read is what makes a deployment that changes a response shape
    safe: an entry written by the previous version fails validation, is treated
    as a miss, and is replaced. Without it, stale-shaped data would be returned
    to clients until the TTL expired.

    Raises:
        CacheSerializationError: If the payload is malformed or no longer
            matches the model.
    """
    try:
        return model.model_validate_json(raw)
    except Exception as exc:
        raise CacheSerializationError(str(exc)) from exc
