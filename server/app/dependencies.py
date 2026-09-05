"""Shared FastAPI dependencies.

Injectable providers used across routers. Authentication, RBAC, database
sessions and the Redis client are added here in Phase 3; keeping them in one
module means route handlers declare what they need rather than constructing it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
"""Injects the cached application settings."""
