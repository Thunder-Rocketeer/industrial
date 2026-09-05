"""Structured logging setup.

Spec section 28: log method, path, status, duration and important operational
events -- and never log passwords, tokens, keys or session contents.

Records are emitted as single-line JSON so they can be ingested by a log
aggregator without a custom parser. Extra fields set on a record (for example
``request_id``) are merged into the JSON object automatically.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Attributes present on every LogRecord. Anything outside this set was attached
# by the caller via `logger.info(..., extra={...})` and is treated as context.
_STANDARD_RECORD_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)

# Never serialize these keys even if a caller passes them, so a mistake at one
# call site cannot leak a secret into the logs (spec sections 28 and 65).
_REDACTED_KEYS = frozenset(
    {
        "password",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "cookie",
        "set-cookie",
        "api_key",
        "client_secret",
        "service_role_key",
        "session",
    }
)

REDACTED = "[REDACTED]"


def _extract_context(record: logging.LogRecord) -> dict[str, Any]:
    """Return the caller-supplied `extra` fields, with sensitive keys redacted."""
    return {
        key: (REDACTED if key.lower() in _REDACTED_KEYS else value)
        for key, value in record.__dict__.items()
        if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        payload.update(_extract_context(record))

        if record.exc_info:
            # The traceback goes to the server log only, never to a client
            # response (spec section 68).
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class KeyValueFormatter(logging.Formatter):
    """Human-readable formatter that keeps the structured context visible.

    Used in development, where a wall of JSON is harder to scan than
    ``message key=value key=value``. Redaction rules are identical to the JSON
    formatter, so a secret cannot leak just because the format changed.
    """

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = _extract_context(record)
        if not context:
            return base
        pairs = " ".join(f"{key}={value}" for key, value in context.items())
        return f"{base} {pairs}"


def configure_logging(level: str = "INFO", *, use_json: bool = True) -> None:
    """Install the root logging configuration.

    Called once during application startup. Idempotent: existing handlers are
    replaced, so a reload during development does not duplicate output.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if use_json else KeyValueFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn installs its own handlers; route them through ours instead so all
    # output shares one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)
