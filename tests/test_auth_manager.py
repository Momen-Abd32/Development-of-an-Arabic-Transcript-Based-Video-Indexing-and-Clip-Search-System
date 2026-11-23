import pytest

from src.media.audit_log import AuditLog
from src.security.auth_manager import AuthManager, AuthRateLimitError


PASSWORD = "Correct-Horse-2026!"


@pytest.fixture
def auth(tmp_path):
    manager = AuthManager(
        tmp_path / "users.db",
        iterations=10_000,
        max_failed_attempts=3,
        lockout_minutes=15,
    )
    yield manager
    manager.close()


def test_create_user_and_authenticate_without_exposing_password_hash(auth):
    created = auth.create_user(
        "Editor_One",
        PASSWORD,
        display_name="Archive Editor",
        role="editor",
    )

    assert created["username"] == "editor_one"
    assert created["display_name"] == "Archive Editor"
    assert created["role"] == "editor"
    assert created["is_active"] is True
    assert "password_hash" not in created
    assert "password_salt" not in created

    authenticated = auth.authenticate("EDITOR_ONE", PASSWORD)
    assert authenticated == created


def test_passwords_use_unique_salts_and_are_not_stored_in_plaintext(auth):
    first = auth.create_user("editor_a", PASSWORD)
    second = auth.create_user("editor_b", PASSWORD)

    rows = auth.connection.execute(
        "SELECT password_salt, password_hash FROM archive_users ORDER BY username"
    ).fetchall()

    assert rows[0]["password_salt"] != rows[1]["password_salt"]
    assert rows[0]["password_hash"] != rows[1]["password_hash"]
    assert PASSWORD.encode() not in rows[0]["password_hash"]
    assert first["username"] == "editor_a"
    assert second["username"] == "editor_b"


def test_authentication_rejects_wrong_password_unknown_and_malformed_usernames(auth):
    auth.create_user("editor_one", PASSWORD)

    assert auth.authenticate("editor_one", "wrong-password") is None
    assert auth.authenticate("missing_user", PASSWORD) is None
    assert auth.authenticate("editor_one" + "x" * 70, PASSWORD) is None
    assert auth.authenticate("editor_one", PASSWORD + "x" * 300) is None


def test_malformed_username_attempts_do_not_lock_a_valid_account(auth):
    auth.create_user("editor_one", PASSWORD)
    for _ in range(4):
        assert auth.authenticate("editor_one" + "x" * 70, "wrong") is None

    assert auth.authenticate("editor_one", PASSWORD)["username"] == "editor_one"


def test_failed_logins_are_rate_limited_and_password_reset_clears_lockout(auth):
    auth.create_user("editor_one", PASSWORD)
    for _ in range(3):
        assert auth.authenticate("editor_one", "incorrect-password") is None

    with pytest.raises(AuthRateLimitError):
        auth.authenticate("editor_one", PASSWORD)

    auth.reset_password(
        "editor_one",
        "New-Password-2026!",
        actor="system",
    )
    assert auth.authenticate("editor_one", "New-Password-2026!")["username"] == "editor_one"


def test_disabled_user_cannot_authenticate(auth):
    auth.create_user("editor_one", PASSWORD)
    auth.set_user_active("editor_one", False, actor="system")

    assert auth.get_user("editor_one")["is_active"] is False
    assert auth.authenticate("editor_one", PASSWORD) is None


def test_bootstrap_creates_only_the_first_administrator(auth):
    assert auth.bootstrap_admin("admin_one", PASSWORD, "Primary Admin") is True
    assert auth.bootstrap_admin("admin_two", PASSWORD, "Second Admin") is False
    assert auth.list_users() == [
        {
            "username": "admin_one",
            "display_name": "Primary Admin",
            "role": "administrator",
            "is_active": True,
            "session_version": 0,
            "created_at": auth.get_user("admin_one")["created_at"],
            "updated_at": auth.get_user("admin_one")["updated_at"],
        }
    ]


def test_user_role_changes_and_last_admin_protection(auth):
    auth.create_user("admin_one", PASSWORD, role="administrator")
    auth.create_user("admin_two", PASSWORD, role="administrator")
    auth.create_user("editor_one", PASSWORD, role="editor")

    with pytest.raises(ValueError, match="own account"):
        auth.update_user_role("admin_one", "editor", actor="admin_two")

    changed = auth.update_user_role(
        "editor_one",
        "search_only",
        actor="admin_one",
    )
    assert changed["role"] == "search_only"

    auth.update_user_role("admin_two", "editor", actor="admin_one")
    with pytest.raises(ValueError, match="last active administrator"):
        auth.update_user_role("admin_one", "editor", actor="admin_one")


def test_user_activation_and_self_deactivation_protection(auth):
    auth.create_user("admin_one", PASSWORD, role="administrator")
    auth.create_user("admin_two", PASSWORD, role="administrator")
    auth.create_user("editor_one", PASSWORD, role="editor")

    with pytest.raises(ValueError, match="own signed-in"):
        auth.set_user_active("admin_one", False, actor="admin_one")

    deactivated = auth.set_user_active(
        "editor_one",
        False,
        actor="admin_one",
    )
    assert deactivated["is_active"] is False

    auth.set_user_active("editor_one", True, actor="admin_one")
    assert auth.get_user("editor_one")["is_active"] is True


def test_last_active_administrator_cannot_be_deactivated(auth):
    auth.create_user("admin_one", PASSWORD, role="administrator")
    with pytest.raises(ValueError, match="last active administrator"):
        auth.set_user_active("admin_one", False, actor="admin_two")


def test_password_reset_and_self_service_password_change(auth):
    auth.create_user("editor_one", PASSWORD)
    with pytest.raises(ValueError, match="Current password"):
        auth.change_password("editor_one", "wrong-password", "New-Password-2026!")

    auth.change_password("editor_one", PASSWORD, "New-Password-2026!")
    assert auth.authenticate("editor_one", PASSWORD) is None
    assert auth.authenticate("editor_one", "New-Password-2026!") is not None


@pytest.mark.parametrize(
    "username",
    ["", "ab", "contains space", "bad/name", "user@host"],
)
def test_username_validation(username, auth):
    with pytest.raises(ValueError, match="Username"):
        auth.create_user(username, PASSWORD)


@pytest.mark.parametrize("password", ["", "short", "x" * 257, None])
def test_password_validation(password, auth):
    with pytest.raises((TypeError, ValueError)):
        auth.create_user("editor_one", password)


def test_role_validation(auth):
    with pytest.raises(ValueError, match="Role"):
        auth.create_user("editor_one", PASSWORD, role="owner")


def test_audit_events_record_user_changes_without_password_material(auth, tmp_path):
    auth.create_user("editor_one", PASSWORD, actor="admin_one")
    auth.update_user_role("editor_one", "search_only", actor="admin_one")
    auth.reset_password(
        "editor_one",
        "New-Password-2026!",
        actor="admin_one",
    )
    auth.close()

    audit = AuditLog(tmp_path / "users.db")
    try:
        events = audit.list_events(entity_type="archive_user", entity_id="editor_one")
        actions = [event["action"] for event in reversed(events)]
        assert actions == [
            "user_created",
            "user_role_updated",
            "user_password_reset",
        ]
        assert all("password_hash" not in str(event["details"]) for event in events)
        assert all("password_salt" not in str(event["details"]) for event in events)
    finally:
        audit.close()



def test_role_activation_and_password_changes_increment_session_version(auth):
    user = auth.create_user("editor_one", PASSWORD, role="editor")
    assert user["session_version"] == 0

    user = auth.update_user_role("editor_one", "search_only", actor="system")
    assert user["session_version"] == 1

    user = auth.set_user_active("editor_one", False, actor="system")
    assert user["session_version"] == 2

    user = auth.set_user_active("editor_one", True, actor="system")
    assert user["session_version"] == 3

    user = auth.reset_password(
        "editor_one",
        "New-Password-2026!",
        actor="system",
    )
    assert user["session_version"] == 4

    user = auth.change_password(
        "editor_one",
        "New-Password-2026!",
        "Another-Password-2026!",
    )
    assert user["session_version"] == 5


def test_auth_manager_adds_session_version_to_legacy_user_schema(tmp_path):
    import sqlite3

    database = tmp_path / "legacy-users.db"
    connection = sqlite3.connect(database)
    connection.execute("""
        CREATE TABLE archive_users (
            username TEXT PRIMARY KEY COLLATE NOCASE,
            display_name TEXT NOT NULL,
            password_salt BLOB NOT NULL,
            password_hash BLOB NOT NULL,
            password_iterations INTEGER NOT NULL,
            role TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    connection.commit()
    connection.close()

    manager = AuthManager(database, iterations=10_000)
    try:
        columns = {
            row["name"]
            for row in manager.connection.execute("PRAGMA table_info(archive_users)")
        }
        assert "session_version" in columns
    finally:
        manager.close()
