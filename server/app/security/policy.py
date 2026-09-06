"""Role-based access control (spec sections 12 and 56).

The whole authorization model is this one file: a set of permissions, and a
matrix mapping each role to the permissions it holds. Spec section 12 is
explicit that permissions must be "centralized rather than hard-coded
independently in every route" -- a route that decides for itself which roles may
call it is a rule nobody can audit, and the second such route is where the
first inconsistency appears.

Routes therefore never name roles. They declare a *permission*, and this module
decides which roles hold it. Changing who may see quality data is one edit here,
not a search across nine route modules.

WHY PERMISSIONS RATHER THAN ROLE LISTS

`require_permission(Permission.QUALITY_READ)` says what the endpoint needs.
`require_role("ADMIN", "QUALITY_ENGINEER", "FACTORY_MANAGER")` says who happens
to qualify today, and goes stale the moment a role is added. The indirection
costs one lookup and buys a model that can be reasoned about as a table.

READ-ONLY, FOR NOW

Phase 3 built a read-only API, so every permission below is a read. The write
permissions are declared anyway, unused, because the matrix is the thing being
designed here and leaving the write column blank would hide the shape of it.
Spec section 56's policy sketch -- "Production Supervisor: Viewer + production
operations" -- only means something once operations exist to grant.
"""

from __future__ import annotations

from enum import Enum

from app.models.enums import RoleCode


class Permission(str, Enum):
    """A single capability an endpoint can require.

    Named for the resource and the action, not for the route, so one permission
    can guard several endpoints over the same data.
    """

    # -- reads ----------------------------------------------------------------
    DASHBOARD_READ = "dashboard:read"
    PRODUCTION_READ = "production:read"
    QUALITY_READ = "quality:read"
    INVENTORY_READ = "inventory:read"
    MACHINES_READ = "machines:read"
    ANALYTICS_READ = "analytics:read"
    ALERTS_READ = "alerts:read"
    MAINTENANCE_READ = "maintenance:read"

    # -- writes (declared, not yet used by any endpoint) ----------------------
    PRODUCTION_WRITE = "production:write"
    QUALITY_WRITE = "quality:write"
    INVENTORY_WRITE = "inventory:write"
    MACHINES_WRITE = "machines:write"
    MAINTENANCE_WRITE = "maintenance:write"
    ALERTS_ACKNOWLEDGE = "alerts:acknowledge"

    # -- administration -------------------------------------------------------
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    AUDIT_READ = "audit:read"


#: Permissions every authenticated user holds.
#:
#: This is the Viewer role's entire grant, and spec section 56 defines every
#: other role as "Viewer + ...". Expressing that literally means a permission
#: added here reaches every role, which is what "Viewer +" is supposed to mean.
_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.DASHBOARD_READ,
        Permission.ANALYTICS_READ,
        Permission.ALERTS_READ,
    }
)

#: Every read permission. Used by the management roles.
_ALL_READS: frozenset[Permission] = frozenset(
    {
        Permission.DASHBOARD_READ,
        Permission.PRODUCTION_READ,
        Permission.QUALITY_READ,
        Permission.INVENTORY_READ,
        Permission.MACHINES_READ,
        Permission.ANALYTICS_READ,
        Permission.ALERTS_READ,
        Permission.MAINTENANCE_READ,
    }
)


#: The permission matrix.
#:
#: Each specialist role gets the Viewer baseline plus its own domain, matching
#: spec section 56. A Quality Engineer can read quality data and the dashboard,
#: and cannot read inventory -- not because inventory is secret, but because a
#: role that grants everything to everyone is not a role model.
ROLE_PERMISSIONS: dict[RoleCode, frozenset[Permission]] = {
    # Full application administration.
    RoleCode.ADMIN: frozenset(Permission),
    # Reads all operational data, plus management functions.
    RoleCode.FACTORY_MANAGER: _ALL_READS
    | {
        Permission.PRODUCTION_WRITE,
        Permission.QUALITY_WRITE,
        Permission.INVENTORY_WRITE,
        Permission.MACHINES_WRITE,
        Permission.MAINTENANCE_WRITE,
        Permission.ALERTS_ACKNOWLEDGE,
        Permission.USERS_READ,
    },
    # Viewer + production operations, and the machines that do the producing.
    RoleCode.PRODUCTION_SUPERVISOR: _VIEWER
    | {
        Permission.PRODUCTION_READ,
        Permission.PRODUCTION_WRITE,
        Permission.MACHINES_READ,
        Permission.MAINTENANCE_READ,
        Permission.ALERTS_ACKNOWLEDGE,
    },
    # Viewer + quality operations. Machines are readable because a defect is
    # attributed to the machine that produced the part, so a quality
    # investigation that cannot see machines is not an investigation.
    RoleCode.QUALITY_ENGINEER: _VIEWER
    | {
        Permission.QUALITY_READ,
        Permission.QUALITY_WRITE,
        Permission.MACHINES_READ,
        Permission.ALERTS_ACKNOWLEDGE,
    },
    # Viewer + inventory operations.
    RoleCode.INVENTORY_MANAGER: _VIEWER
    | {
        Permission.INVENTORY_READ,
        Permission.INVENTORY_WRITE,
        Permission.ALERTS_ACKNOWLEDGE,
    },
    # Reads the dashboard and analytics. Nothing else.
    RoleCode.VIEWER: _VIEWER,
}


class UnknownRoleError(ValueError):
    """Raised when a role code has no entry in the matrix.

    Treated as a failure rather than defaulted to "no permissions", because a
    role in the database with no matrix entry is a deployment mistake and should
    be loud. Silently granting nothing would present as a confusing 403 for one
    group of users.
    """

    def __init__(self, role: str) -> None:
        self.role = role
        super().__init__(
            f"Role {role!r} has no permission mapping. "
            f"Known roles: {', '.join(sorted(r.value for r in ROLE_PERMISSIONS))}."
        )


def permissions_for(role: RoleCode | str) -> frozenset[Permission]:
    """Return every permission a role holds.

    Raises:
        UnknownRoleError: If the role is not in the matrix.
    """
    if isinstance(role, str):
        try:
            role = RoleCode(role)
        except ValueError as exc:
            raise UnknownRoleError(role) from exc

    try:
        return ROLE_PERMISSIONS[role]
    except KeyError as exc:
        raise UnknownRoleError(role.value) from exc


def has_permission(role: RoleCode | str, permission: Permission) -> bool:
    """Whether a role holds a permission.

    Raises:
        UnknownRoleError: If the role is not in the matrix.
    """
    return permission in permissions_for(role)


def has_any_permission(role: RoleCode | str, *permissions: Permission) -> bool:
    """Whether a role holds at least one of the given permissions."""
    held = permissions_for(role)
    return any(permission in held for permission in permissions)


def roles_with(permission: Permission) -> frozenset[RoleCode]:
    """Return every role holding a permission.

    The matrix read the other way round. Used by the documentation generator and
    by tests that assert the matrix is what it claims to be.
    """
    return frozenset(role for role, granted in ROLE_PERMISSIONS.items() if permission in granted)
