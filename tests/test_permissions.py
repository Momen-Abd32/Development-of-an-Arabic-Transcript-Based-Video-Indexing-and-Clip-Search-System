import pytest

from src.security.permissions import ROLE_PERMISSIONS, has_role_permission


@pytest.mark.parametrize(
    "role,permission,expected",
    [
        ("administrator", "users", True),
        ("administrator", "audit", True),
        ("editor", "notes", True),
        ("editor", "users", False),
        ("search_only", "search", True),
        ("search_only", "qa", True),
        ("search_only", "notes", False),
        ("search_only", "upload", False),
        ("unknown", "search", False),
    ],
)
def test_archive_role_permissions(role, permission, expected):
    assert has_role_permission(
        role, permission, authentication_enabled=True
    ) is expected


def test_user_administration_is_disabled_without_authentication():
    assert not has_role_permission(
        "administrator", "users", authentication_enabled=False
    )


def test_role_permission_sets_are_not_shared_mutable_aliases():
    assert "notes" not in ROLE_PERMISSIONS["search_only"]
    assert "users" not in ROLE_PERMISSIONS["editor"]
