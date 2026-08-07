from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from secrets import token_urlsafe
from typing import Any


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    access_password: str = ""
    session_secret: str = ""
    session_ttl_hours: int = 12
    database_path: Path = Path("data/pipeline.db")
    max_active_jobs_per_user: int = 5
    frontend_dist: Path = Path("dist")
    log_dir: Path = Path("logs")
    min_free_disk_gb: float = 30
    retention_days: int = 7
    max_completed_jobs: int = 100
    allow_insecure: bool = False

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            environment=os.getenv("PIPELINE_ENV", "development").lower(),
            host=os.getenv("PIPELINE_HOST", "127.0.0.1"),
            port=int(os.getenv("PIPELINE_PORT", "8000")),
            access_password=os.getenv("PIPELINE_ACCESS_PASSWORD", ""),
            session_secret=os.getenv("PIPELINE_SESSION_SECRET", ""),
            session_ttl_hours=int(os.getenv("PIPELINE_SESSION_TTL_HOURS", "12")),
            database_path=Path(os.getenv("PIPELINE_DATABASE_PATH", "data/pipeline.db")).resolve(),
            max_active_jobs_per_user=int(os.getenv("PIPELINE_MAX_ACTIVE_JOBS_PER_USER", "5")),
            frontend_dist=Path(os.getenv("PIPELINE_FRONTEND_DIST", "dist")).resolve(),
            log_dir=Path(os.getenv("PIPELINE_LOG_DIR", "logs")).resolve(),
            min_free_disk_gb=float(os.getenv("PIPELINE_MIN_FREE_DISK_GB", "30")),
            retention_days=int(os.getenv("PIPELINE_JOB_RETENTION_DAYS", "7")),
            max_completed_jobs=int(os.getenv("PIPELINE_MAX_COMPLETED_JOBS", "100")),
            allow_insecure=os.getenv("PIPELINE_ALLOW_INSECURE", "").lower() in {"1", "true", "yes"},
        )

    @property
    def lan_mode(self) -> bool:
        return self.environment == "production" or self.host not in {"127.0.0.1", "localhost", "::1"}

    @property
    def auth_enabled(self) -> bool:
        return bool(self.session_secret)

    def validate(self) -> None:
        if self.lan_mode and not self.auth_enabled and not self.allow_insecure:
            raise RuntimeError(
                "LAN mode requires PIPELINE_SESSION_SECRET. "
                "Set PIPELINE_ALLOW_INSECURE=true only for isolated development."
            )
        if self.auth_enabled and len(self.session_secret) < 32:
            raise RuntimeError("PIPELINE_SESSION_SECRET must contain at least 32 characters.")


class SessionAuth:
    cookie_name = "pipeline_session"

    def __init__(self, secret: str, ttl_hours: int = 12) -> None:
        self.secret = secret.encode("utf-8")
        self.ttl = timedelta(hours=ttl_hours)

    def issue(self, user_id: str, session_version: int, now: datetime | None = None) -> str:
        issued = now or datetime.now(timezone.utc)
        payload = {
            "uid": user_id,
            "sv": session_version,
            "exp": int((issued + self.ttl).timestamp()),
            "nonce": token_urlsafe(12),
        }
        encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
        signature = hmac.new(self.secret, encoded, hashlib.sha256).digest()
        return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"

    def decode(self, token: str | None, now: datetime | None = None) -> dict[str, Any] | None:
        if not token or "." not in token:
            return False
        encoded, supplied = token.split(".", 1)
        try:
            expected = hmac.new(self.secret, encoded.encode(), hashlib.sha256).digest()
            signature = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            current = int((now or datetime.now(timezone.utc)).timestamp())
            if not hmac.compare_digest(signature, expected) or int(payload["exp"]) <= current:
                return None
            if not isinstance(payload.get("uid"), str) or not isinstance(payload.get("sv"), int):
                return None
            return payload
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def valid(self, token: str | None, now: datetime | None = None) -> bool:
        return self.decode(token, now) is not None


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                    handle.write(str(os.getpid()))
                self.acquired = True
                return
            except FileExistsError:
                try:
                    pid = int(self.path.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    pid = 0
                if pid and process_exists(pid):
                    raise RuntimeError(f"Production server already running with PID {pid}.")
                self.path.unlink(missing_ok=True)
        raise RuntimeError("Could not acquire production instance lock.")

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def lan_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if not address.startswith(("127.", "169.254.")):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def lan_urls(port: int) -> dict[str, list[str] | str]:
    return {
        "local": f"http://127.0.0.1:{port}",
        "lan": [f"http://{address}:{port}" for address in lan_ipv4_addresses()],
    }


def is_local_client(host: str | None) -> bool:
    return bool(host and (host in {"127.0.0.1", "::1", "localhost", "testclient"} or host in lan_ipv4_addresses()))


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for name, filename in (("pipeline.server", "server.log"), ("pipeline.access", "access.log"), ("pipeline.worker", "worker.log"), ("pipeline.audit", "audit.log")):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = RotatingFileHandler(log_dir / filename, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s") if name == "pipeline.audit" else formatter)
            logger.addHandler(handler)
            logger.propagate = False


def readiness(config: RuntimeConfig, workspace: Path, manager: Any, user_store: Any = None) -> dict[str, Any]:
    free_gb = shutil.disk_usage(workspace).free / 1024**3
    database_ready = bool(user_store and user_store.ready()) if config.auth_enabled else True
    user_setup_ready = bool(user_store and user_store.count()) if config.auth_enabled else True
    checks = {
        "frontend": config.frontend_dist.joinpath("index.html").is_file(),
        "workspace_writable": workspace.is_dir() and os.access(workspace, os.W_OK),
        "source": manager.source_readiness().get("status") != "missing_dependency",
        "hook": manager.hook_readiness().get("status") != "missing_dependency",
        "review": manager.review_readiness().get("status") != "missing_dependency",
        "composer": manager.composer_readiness().get("status") != "missing_dependency",
        "queue": manager.queue_readiness().get("status") == "ready",
        "disk": free_gb >= config.min_free_disk_gb,
        "authentication": config.auth_enabled or config.allow_insecure,
        "database_ready": database_ready,
        "user_setup_ready": user_setup_ready,
    }
    return {
        "status": "ready" if all(checks.values()) else "degraded",
        "checks": checks,
        "free_disk_gb": round(free_gb, 1),
        "minimum_free_disk_gb": config.min_free_disk_gb,
        "user_setup_required": not user_setup_ready,
    }


def cleanup_jobs(
    workspace: Path,
    retention_days: int,
    max_completed_jobs: int,
    dry_run: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = workspace.resolve()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    deleted: list[str] = []
    reclaimed = 0
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []

    for metadata in root.glob("*/metadata/job.json"):
        job_dir = metadata.parents[1]
        if job_dir.is_symlink() or job_dir.resolve().parent != root:
            continue
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            timestamp = datetime.fromisoformat(payload.get("finished_at") or payload["created_at"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if payload.get("status") in {"queued", "validating", "downloading", "processing", "composing", "validating_output"}:
            continue
        candidates.append((timestamp, job_dir, payload))

    for timestamp, job_dir, payload in sorted(candidates, reverse=True):
        if timestamp >= cutoff:
            continue
        size = sum(item.stat().st_size for item in job_dir.rglob("*") if item.is_file() and not item.is_symlink())
        deleted.append(job_dir.name)
        reclaimed += size
        if not dry_run:
            shutil.rmtree(job_dir)

    completed_count = sum(payload.get("status") == "completed" for _, _, payload in candidates)
    return {
        "dry_run": dry_run,
        "deleted_job_ids": deleted,
        "reclaimed_bytes": reclaimed,
        "completed_jobs": completed_count,
        "max_completed_jobs": max_completed_jobs,
        "completed_over_limit": max(0, completed_count - max_completed_jobs),
    }
