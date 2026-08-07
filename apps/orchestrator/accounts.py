from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
ROLES = {"user", "admin"}
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


class AccountError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class User:
    id: str
    username: str
    display_name: str
    role: str
    enabled: bool
    created_at: str
    updated_at: str
    last_login_at: str | None
    session_version: int

    def safe_dict(self) -> dict[str, str | bool | None]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
        }


def normalize_username(username: str) -> str:
    value = username.strip().lower()
    if not USERNAME.fullmatch(value):
        raise AccountError("INVALID_USERNAME", "Tên đăng nhập phải dài 3-32 ký tự và chỉ gồm chữ thường, số, ., _, -.")
    return value


def validate_password(password: str) -> None:
    if len(password) < 10 or len(password) > 256:
        raise AccountError("INVALID_PASSWORD", "Mật khẩu phải dài từ 10 đến 256 ký tự.")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "$".join((
        "scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
        base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode(),
    ))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n), r=int(r), p=int(p), dklen=32,
        )
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except (ValueError, TypeError):
        return False


class UserStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'admin')),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    session_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            """)

    def ready(self) -> bool:
        try:
            self.initialize()
            with self._connect() as connection:
                return connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
                ).fetchone() is not None
        except (OSError, sqlite3.Error):
            return False

    def count(self) -> int:
        self.initialize()
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def create_user(self, username: str, display_name: str, password: str, role: str = "user") -> User:
        self.initialize()
        username = normalize_username(username)
        display_name = display_name.strip()
        if not display_name or len(display_name) > 80:
            raise AccountError("INVALID_DISPLAY_NAME", "Tên hiển thị phải dài 1-80 ký tự.")
        if role not in ROLES:
            raise AccountError("INVALID_ROLE", "Role chỉ có thể là user hoặc admin.")
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users(id, username, display_name, password_hash, role, enabled, session_version, created_at, updated_at) VALUES(?,?,?,?,?,1,1,?,?)",
                    (f"u_{uuid4().hex}", username, display_name, hash_password(password), role, now, now),
                )
        except sqlite3.IntegrityError as error:
            raise AccountError("USERNAME_EXISTS", "Tên đăng nhập đã tồn tại.") from error
        return self.get_by_username(username, include_disabled=True)  # type: ignore[return-value]

    def list_users(self) -> list[User]:
        self.initialize()
        with self._connect() as connection:
            return [self._user(row) for row in connection.execute("SELECT * FROM users ORDER BY username")]

    def get_by_id(self, user_id: str, include_disabled: bool = False) -> User | None:
        self.initialize()
        query = "SELECT * FROM users WHERE id=?" + ("" if include_disabled else " AND enabled=1")
        with self._connect() as connection:
            row = connection.execute(query, (user_id,)).fetchone()
        return self._user(row) if row else None

    def get_by_username(self, username: str, include_disabled: bool = False) -> User | None:
        try:
            username = normalize_username(username)
        except AccountError:
            return None
        query = "SELECT * FROM users WHERE username=?" + ("" if include_disabled else " AND enabled=1")
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(query, (username,)).fetchone()
        return self._user(row) if row else None

    def authenticate(self, username: str, password: str) -> User:
        user = self.get_by_username(username, include_disabled=True)
        if not user:
            raise AccountError("INVALID_CREDENTIALS", "Tên đăng nhập hoặc mật khẩu không đúng.")
        if not user.enabled:
            raise AccountError("ACCOUNT_DISABLED", "Tài khoản đã bị vô hiệu hóa.")
        with self._connect() as connection:
            encoded = connection.execute("SELECT password_hash FROM users WHERE id=?", (user.id,)).fetchone()[0]
        if not verify_password(password, encoded):
            raise AccountError("INVALID_CREDENTIALS", "Tên đăng nhập hoặc mật khẩu không đúng.")
        now = _now()
        with self._connect() as connection:
            connection.execute("UPDATE users SET last_login_at=?, updated_at=? WHERE id=?", (now, now, user.id))
        return self.get_by_id(user.id, include_disabled=True)  # type: ignore[return-value]

    def set_enabled(self, username: str, enabled: bool) -> User:
        user = self._required(username)
        if not enabled and user.role == "admin" and user.enabled and self._enabled_admin_count() <= 1:
            raise AccountError("LAST_ADMIN", "Không thể vô hiệu hóa admin cuối cùng.")
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET enabled=?, session_version=session_version+1, updated_at=? WHERE id=?",
                (int(enabled), _now(), user.id),
            )
        return self.get_by_id(user.id, include_disabled=True)  # type: ignore[return-value]

    def reset_password(self, username: str, password: str) -> User:
        user = self._required(username)
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET password_hash=?, session_version=session_version+1, updated_at=? WHERE id=?",
                (hash_password(password), _now(), user.id),
            )
        return self.get_by_id(user.id, include_disabled=True)  # type: ignore[return-value]

    def set_role(self, username: str, role: str) -> User:
        if role not in ROLES:
            raise AccountError("INVALID_ROLE", "Role chỉ có thể là user hoặc admin.")
        user = self._required(username)
        if user.role == "admin" and role != "admin" and user.enabled and self._enabled_admin_count() <= 1:
            raise AccountError("LAST_ADMIN", "Không thể hạ role admin cuối cùng.")
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET role=?, session_version=session_version+1, updated_at=? WHERE id=?",
                (role, _now(), user.id),
            )
        return self.get_by_id(user.id, include_disabled=True)  # type: ignore[return-value]

    def _required(self, username: str) -> User:
        user = self.get_by_username(username, include_disabled=True)
        if not user:
            raise AccountError("USER_NOT_FOUND", "Không tìm thấy tài khoản.")
        return user

    def _enabled_admin_count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[0])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"], username=row["username"], display_name=row["display_name"],
            role=row["role"], enabled=bool(row["enabled"]), created_at=row["created_at"],
            updated_at=row["updated_at"], last_login_at=row["last_login_at"],
            session_version=int(row["session_version"]),
        )


def audit_event(action: str, *, actor: User | None = None, target: str | None = None,
                client_ip: str | None = None, success: bool = True) -> None:
    logging.getLogger("pipeline.audit").info(json.dumps({
        "timestamp": _now(),
        "actor_user_id": actor.id if actor else None,
        "actor_username": actor.username if actor else None,
        "action": action,
        "target": target,
        "client_ip": client_ip,
        "success": success,
    }, ensure_ascii=False, separators=(",", ":")))


def migrate_m08(database_path: Path, workspace: Path) -> dict[str, int | str]:
    database_path = database_path.resolve()
    workspace = workspace.resolve()
    backup = database_path.parent / "m08-backup"
    jobs_backup = backup / "jobs"
    jobs_backup.mkdir(parents=True, exist_ok=True)
    if database_path.is_file() and not (backup / "pipeline.db.pre-m08.bak").exists():
        shutil.copy2(database_path, backup / "pipeline.db.pre-m08.bak")
    copied = 0
    for metadata in workspace.glob("*/metadata/job.json"):
        if metadata.parents[1].resolve().parent != workspace:
            continue
        target = jobs_backup / f"{metadata.parents[1].name}.json"
        if not target.exists():
            shutil.copy2(metadata, target)
            copied += 1
    store = UserStore(database_path)
    store.initialize()
    (backup / "manifest.json").write_text(json.dumps({
        "database": str(database_path), "workspace": str(workspace), "updated_at": _now()
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"database": str(database_path), "backed_up_jobs": copied, "users": store.count()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
