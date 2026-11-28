"""Centralized role-to-feature authorization policy for the local archive UI."""

ROLE_PERMISSIONS = {
    "administrator": {
        "upload", "transcript", "search", "visual", "cross_modal", "qa",
        "evaluation", "notes", "clips", "archive", "queue", "dashboard",
        "audit", "users",
    },
    "editor": {
        "upload", "transcript", "search", "visual", "cross_modal", "qa",
        "evaluation", "notes", "clips", "archive", "queue", "dashboard", "audit",
    },
    "search_only": {"search", "visual", "cross_modal", "qa", "dashboard"},
}


def has_role_permission(role: str, permission: str, *, authentication_enabled: bool) -> bool:
    """Return whether a role can access a feature in the authenticated UI."""
    if role not in ROLE_PERMISSIONS or not isinstance(permission, str):
        return False
    if permission == "users" and not authentication_enabled:
        return False
    return permission in ROLE_PERMISSIONS[role]
