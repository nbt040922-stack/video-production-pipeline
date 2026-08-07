from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import secrets
from pathlib import Path

import uvicorn

from .api import create_app
from .accounts import AccountError, UserStore, audit_event, migrate_m08
from .runtime import InstanceLock, RuntimeConfig, cleanup_jobs, configure_logging, lan_urls


def serve() -> int:
    config = RuntimeConfig.from_env()
    config.validate()
    configure_logging(config.log_dir)
    urls = lan_urls(config.port)
    print(f"Bound: {config.host}:{config.port}")
    print(f"Local: {urls['local']}")
    for url in urls["lan"]:
        print(f"LAN: {url}")
    with InstanceLock(config.log_dir / "server.lock"):
        logging.getLogger("pipeline.server").info("startup host=%s port=%s", config.host, config.port)
        uvicorn.run(create_app(config=config), host=config.host, port=config.port, access_log=False)
        logging.getLogger("pipeline.server").info("shutdown")
    return 0


def main() -> int:
    _load_env(Path(".env"))
    parser = argparse.ArgumentParser(description="Video Production Pipeline operations")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve")
    commands.add_parser("lan-info")
    commands.add_parser("generate-secret")
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--apply", action="store_true")
    commands.add_parser("create-admin")
    commands.add_parser("migrate-m08")
    users = commands.add_parser("users").add_subparsers(dest="users_command")
    users.add_parser("list")
    create = users.add_parser("create")
    create.add_argument("username", nargs="?")
    create.add_argument("--display-name")
    create.add_argument("--role", choices=("user", "admin"), default="user")
    for name in ("disable", "enable", "reset-password"):
        command = users.add_parser(name)
        command.add_argument("username")
    role = users.add_parser("set-role")
    role.add_argument("username")
    role.add_argument("role", choices=("user", "admin"))
    args = parser.parse_args()

    if args.command in {None, "serve"}:
        return serve()
    config = RuntimeConfig.from_env()
    configure_logging(config.log_dir)
    if args.command == "lan-info":
        urls = lan_urls(config.port)
        print(f"Local:\n{urls['local']}\n")
        print("LAN:")
        print("\n".join(urls["lan"]) or "Không tìm thấy LAN IPv4.")
        return 0
    if args.command == "generate-secret":
        print(secrets.token_urlsafe(48))
        return 0
    if args.command == "cleanup":
        result = cleanup_jobs(
            Path(__import__("os").getenv("PIPELINE_WORKSPACE", "workspace")),
            config.retention_days,
            config.max_completed_jobs,
            dry_run=not args.apply,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    store = UserStore(config.database_path)
    if args.command == "migrate-m08":
        result = migrate_m08(config.database_path, Path(__import__("os").getenv("PIPELINE_WORKSPACE", "workspace")))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    try:
        if args.command == "create-admin":
            if any(user.role == "admin" and user.enabled for user in store.list_users()):
                print("Admin đã tồn tại.")
                return 0
            username = input("Tên đăng nhập admin: ").strip()
            display_name = input("Tên hiển thị: ").strip() or username
            user = store.create_user(username, display_name, _prompt_password(), "admin")
            audit_event("user.create", target=user.username)
            print(f"Đã tạo admin: {user.username}")
            return 0
        if args.command == "users":
            if args.users_command == "list":
                print(json.dumps([user.safe_dict() for user in store.list_users()], ensure_ascii=False, indent=2))
                return 0
            if args.users_command == "create":
                username = args.username or input("Tên đăng nhập: ").strip()
                display_name = args.display_name or input("Tên hiển thị: ").strip() or username
                user = store.create_user(username, display_name, _prompt_password(), args.role)
                action = "create"
            elif args.users_command == "disable":
                user, action = store.set_enabled(args.username, False), "disable"
            elif args.users_command == "enable":
                user, action = store.set_enabled(args.username, True), "enable"
            elif args.users_command == "reset-password":
                user, action = store.reset_password(args.username, _prompt_password()), "reset_password"
            elif args.users_command == "set-role":
                user, action = store.set_role(args.username, args.role), "set_role"
            else:
                parser.print_help()
                return 2
            audit_event(f"user.{action}", target=user.username)
            print(json.dumps(user.safe_dict(), ensure_ascii=False, indent=2))
            return 0
    except AccountError as error:
        print(f"Lỗi [{error.code}]: {error.message}")
        return 1
    return 2


def _prompt_password() -> str:
    password = getpass.getpass("Mật khẩu mới: ")
    if password != getpass.getpass("Nhập lại mật khẩu: "):
        raise AccountError("PASSWORD_MISMATCH", "Hai lần nhập mật khẩu không giống nhau.")
    return password


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("'\""))


if __name__ == "__main__":
    raise SystemExit(main())
