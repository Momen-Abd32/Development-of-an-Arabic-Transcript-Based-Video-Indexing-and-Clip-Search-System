"""Local account authentication and role management for the archive UI."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.media.audit_log import AuditLog


class AuthRateLimitError(RuntimeError):
    """Raised when an account has too many recent failed login attempts."""


class AuthManager:
    """PBKDF2-backed user store with administrator/editor/search-only roles."""

    ROLES = {"administrator", "editor", "search_only"}
    USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{3,64}$")
    PASSWORD_MIN_LENGTH = 12
    PASSWORD_MAX_LENGTH = 256
    DEFAULT_ITERATIONS = 600_000

    def __init__(
        self,
        database_path: str | Path = "data/database/processing_queue.db",
        *,
        iterations: int = DEFAULT_ITERATIONS,
        max_failed_attempts: int = 5,
        lockout_minutes: int = 15,
    ):
        if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 10_000:
            raise ValueError("PBKDF2 iterations must be an integer of at least 10,000.")
        if isinstance(max_failed_attempts, bool) or not isinstance(max_failed_attempts, int) or max_failed_attempts < 1:
            raise ValueError("Maximum failed attempts must be a positive integer.")
        if isinstance(lockout_minutes, bool) or not isinstance(lockout_minutes, int) or lockout_minutes < 1:
            raise ValueError("Lockout duration must be a positive integer.")

        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.iterations = iterations
        self.max_failed_attempts = max_failed_attempts
        self.lockout_minutes = lockout_minutes
        self.connection = sqlite3.connect(
            self.database_path,
            timeout=10,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 10000")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS archive_users (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                password_iterations INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (
                    role IN ('administrator', 'editor', 'search_only')
                ),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                session_version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS auth_login_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE,
                attempted_at TEXT NOT NULL,
                succeeded INTEGER NOT NULL CHECK (succeeded IN (0, 1))
            )
        """)
        self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_auth_attempts_user_time
            ON auth_login_attempts(username, attempted_at DESC)
        """)
        user_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(archive_users)")
        }
        if "session_version" not in user_columns:
            self.connection.execute(
                "ALTER TABLE archive_users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0"
            )

    def close(self) -> None:
        self.connection.close()

    @classmethod
    def _normalize_username(cls, username: str) -> str:
        if not isinstance(username, str):
            raise ValueError("Username must be a string.")
        value = username.strip().lower()
        if not cls.USERNAME_PATTERN.fullmatch(value):
            raise ValueError(
                "Username must be 3-64 characters using letters, numbers, dot, dash, or underscore."
            )
        return value

    @classmethod
    def _validate_display_name(cls, display_name: str) -> str:
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("Display name cannot be empty.")
        value = display_name.strip()
        if len(value) > 120:
            raise ValueError("Display name cannot exceed 120 characters.")
        return value

    @classmethod
    def _validate_password(cls, password: str) -> str:
        if not isinstance(password, str):
            raise TypeError("Password must be a string.")
        if not cls.PASSWORD_MIN_LENGTH <= len(password) <= cls.PASSWORD_MAX_LENGTH:
            raise ValueError(
                f"Password must contain {cls.PASSWORD_MIN_LENGTH}-{cls.PASSWORD_MAX_LENGTH} characters."
            )
        return password

    @classmethod
    def _validate_role(cls, role: str) -> str:
        if not isinstance(role, str) or role not in cls.ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(cls.ROLES))}.")
        return role

    def _hash_password(self, password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            self.iterations,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _public_user(row: sqlite3.Row | dict) -> dict:
        return {
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "session_version": row["session_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _record_audit(
        self,
        action: str,
        username: str,
        actor: str,
        details: dict | None = None,
    ) -> None:
        audit = AuditLog(self.database_path)
        try:
            audit.record(
                action=action,
                entity_type="archive_user",
                entity_id=username,
                actor=actor,
                details=details or {},
            )
        finally:
            audit.close()

    def has_users(self) -> bool:
        row = self.connection.execute(
            "SELECT EXISTS(SELECT 1 FROM archive_users)"
        ).fetchone()
        return bool(row[0])

    def bootstrap_admin(
        self,
        username: str,
        password: str,
        display_name: str = "Archive Administrator",
    ) -> bool:
        """Atomically create the first administrator across concurrent starters."""
        username = self._normalize_username(username)
        password = self._validate_password(password)
        display_name = self._validate_display_name(display_name)
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(password, salt)
        now = self._now()

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.has_users():
                self.connection.execute("COMMIT")
                return False
            self.connection.execute(
                """
                INSERT INTO archive_users (
                    username, display_name, password_salt, password_hash,
                    password_iterations, role, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'administrator', 1, ?, ?)
                """,
                (username, display_name, salt, password_hash, self.iterations, now, now),
            )
            self.connection.execute("COMMIT")
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

        self._record_audit(
            "user_created",
            username,
            "bootstrap",
            {"display_name": display_name, "role": "administrator"},
        )
        return True

    def create_user(
        self,
        username: str,
        password: str,
        *,
        display_name: str | None = None,
        role: str = "editor",
        actor: str = "system",
    ) -> dict:
        username = self._normalize_username(username)
        password = self._validate_password(password)
        role = self._validate_role(role)
        display_name = self._validate_display_name(
            display_name if display_name is not None else username
        )
        actor = self._normalize_username(actor) if actor != "bootstrap" else actor
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(password, salt)
        now = self._now()
        try:
            self.connection.execute(
                """
                INSERT INTO archive_users (
                    username, display_name, password_salt, password_hash,
                    password_iterations, role, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    username, display_name, salt, password_hash,
                    self.iterations, role, now, now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Username already exists: {username}") from error
        self._record_audit(
            "user_created",
            username,
            actor,
            {"display_name": display_name, "role": role},
        )
        return self.get_user(username)

    def get_user(self, username: str) -> dict | None:
        try:
            normalized = self._normalize_username(username)
        except ValueError:
            return None
        row = self.connection.execute(
            "SELECT * FROM archive_users WHERE username = ?",
            (normalized,),
        ).fetchone()
        return self._public_user(row) if row else None

    def list_users(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM archive_users ORDER BY username"
        ).fetchall()
        return [self._public_user(row) for row in rows]

    def authenticate(self, username: str, password: str) -> dict | None:
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        normalized = username.strip().lower()
        username_valid = bool(self.USERNAME_PATTERN.fullmatch(normalized))
        # Rate-limit syntactically valid account names independently. Malformed
        # identifiers are still checked with the dummy PBKDF2 hash below, but
        # must not share one global lockout bucket that unrelated bad inputs
        # could exhaust for every other malformed login attempt.
        attempt_key = normalized if username_valid else None
        now = datetime.now(timezone.utc)
        if attempt_key is not None:
            cutoff = (now - timedelta(minutes=self.lockout_minutes)).isoformat()
            attempts = self.connection.execute(
                """
                SELECT COUNT(*) FROM auth_login_attempts
                WHERE username = ? AND succeeded = 0 AND attempted_at >= ?
                """,
                (attempt_key, cutoff),
            ).fetchone()[0]
            if attempts >= self.max_failed_attempts:
                raise AuthRateLimitError(
                    f"Too many failed login attempts. Try again in {self.lockout_minutes} minutes."
                )

        row = None
        if username_valid:
            row = self.connection.execute(
                "SELECT * FROM archive_users WHERE username = ?",
                (normalized,),
            ).fetchone()
        salt = row["password_salt"] if row else b"archive-auth-dummy-salt"
        iterations = row["password_iterations"] if row else self.iterations
        password_valid = len(password) <= self.PASSWORD_MAX_LENGTH
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password[:self.PASSWORD_MAX_LENGTH].encode("utf-8"),
            salt,
            iterations,
        )
        valid = bool(
            username_valid
            and password_valid
            and row
            and row["is_active"]
            and hmac.compare_digest(candidate, row["password_hash"])
        )
        if attempt_key is not None:
            self.connection.execute(
                """
                INSERT INTO auth_login_attempts (username, attempted_at, succeeded)
                VALUES (?, ?, ?)
                """,
                (attempt_key, now.isoformat(), int(valid)),
            )
            self.connection.execute(
                "DELETE FROM auth_login_attempts WHERE attempted_at < ?",
                ((now - timedelta(days=1)).isoformat(),),
            )
        if not valid:
            return None

        if attempt_key is not None:
            self.connection.execute(
                "DELETE FROM auth_login_attempts WHERE username = ?",
                (attempt_key,),
            )
        return self._public_user(row)

    def update_user_role(
        self,
        username: str,
        role: str,
        *,
        actor: str,
    ) -> dict:
        username = self._normalize_username(username)
        role = self._validate_role(role)
        actor = self._normalize_username(actor)

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT * FROM archive_users WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                raise KeyError(f"User not found: {username}")
            previous_role = row["role"]
            if actor == username and role != "administrator":
                raise ValueError("You cannot remove administrator access from your own account.")
            if previous_role == "administrator" and role != "administrator" and row["is_active"]:
                active_admins = self.connection.execute(
                    """
                    SELECT COUNT(*) FROM archive_users
                    WHERE role = 'administrator' AND is_active = 1
                    """
                ).fetchone()[0]
                if active_admins <= 1:
                    raise ValueError("The last active administrator cannot be demoted.")
            now = self._now()
            self.connection.execute(
                """
                UPDATE archive_users
                SET role = ?, session_version = session_version + ?, updated_at = ?
                WHERE username = ?
                """,
                (role, int(previous_role != role), now, username),
            )
            self.connection.execute("COMMIT")
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

        self._record_audit(
            "user_role_updated",
            username,
            actor,
            {"before": previous_role, "after": role},
        )
        return self.get_user(username)

    def set_user_active(
        self,
        username: str,
        is_active: bool,
        *,
        actor: str,
    ) -> dict:
        username = self._normalize_username(username)
        actor = self._normalize_username(actor)
        if not isinstance(is_active, bool):
            raise TypeError("Active status must be a boolean.")

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT * FROM archive_users WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                raise KeyError(f"User not found: {username}")
            if not is_active and actor == username:
                raise ValueError("You cannot deactivate your own signed-in account.")
            if not is_active and row["role"] == "administrator" and row["is_active"]:
                active_admins = self.connection.execute(
                    """
                    SELECT COUNT(*) FROM archive_users
                    WHERE role = 'administrator' AND is_active = 1
                    """
                ).fetchone()[0]
                if active_admins <= 1:
                    raise ValueError("The last active administrator cannot be deactivated.")
            previous_active = bool(row["is_active"])
            now = self._now()
            self.connection.execute(
                """
                UPDATE archive_users
                SET is_active = ?, session_version = session_version + ?, updated_at = ?
                WHERE username = ?
                """,
                (int(is_active), int(previous_active != is_active), now, username),
            )
            self.connection.execute("COMMIT")
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

        self._record_audit(
            "user_activated" if is_active else "user_deactivated",
            username,
            actor,
            {"is_active": is_active},
        )
        return self.get_user(username)

    def reset_password(
        self,
        username: str,
        new_password: str,
        *,
        actor: str,
    ) -> dict:
        username = self._normalize_username(username)
        new_password = self._validate_password(new_password)
        actor = self._normalize_username(actor)
        if self.get_user(username) is None:
            raise KeyError(f"User not found: {username}")
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(new_password, salt)
        now = self._now()
        self.connection.execute(
            """
            UPDATE archive_users
            SET password_salt = ?, password_hash = ?, password_iterations = ?,
                session_version = session_version + 1, updated_at = ?
            WHERE username = ?
            """,
            (salt, password_hash, self.iterations, now, username),
        )
        self.connection.execute(
            "DELETE FROM auth_login_attempts WHERE username = ?",
            (username,),
        )
        self._record_audit("user_password_reset", username, actor)
        return self.get_user(username)

    def change_password(
        self,
        username: str,
        current_password: str,
        new_password: str,
    ) -> dict:
        username = self._normalize_username(username)
        if not isinstance(current_password, str) or len(current_password) > self.PASSWORD_MAX_LENGTH:
            raise ValueError("Current password is invalid.")
        new_password = self._validate_password(new_password)
        row = self.connection.execute(
            "SELECT * FROM archive_users WHERE username = ? AND is_active = 1",
            (username,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Active user not found: {username}")
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            current_password.encode("utf-8"),
            row["password_salt"],
            row["password_iterations"],
        )
        if not hmac.compare_digest(candidate, row["password_hash"]):
            raise ValueError("Current password is incorrect.")
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(new_password, salt)
        now = self._now()
        self.connection.execute(
            """
            UPDATE archive_users
            SET password_salt = ?, password_hash = ?, password_iterations = ?,
                session_version = session_version + 1, updated_at = ?
            WHERE username = ?
            """,
            (salt, password_hash, self.iterations, now, username),
        )
        self._record_audit("user_password_changed", username, username)
        return self.get_user(username)
