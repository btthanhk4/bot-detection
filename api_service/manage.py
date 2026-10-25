"""Administrative commands for dashboard accounts.

Run inside the API container:

    python -m api_service.manage create-admin --username admin
    python -m api_service.manage reset-password --username admin
    python -m api_service.manage list-users

Without ``--password`` a strong random password is generated and printed once.
"""

import argparse
import getpass
import secrets
import string
import sys

from api_service import auth


def generate_password(length: int = 18) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if auth.validate_new_password(candidate) is None:
            return candidate


def _password_from_args(args) -> tuple:
    if args.password:
        return args.password, False
    if args.prompt:
        value = getpass.getpass("Mật khẩu: ")
        if value != getpass.getpass("Nhập lại: "):
            raise SystemExit("Hai mật khẩu không khớp")
        return value, False
    return generate_password(), True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-admin", "reset-password"):
        command = sub.add_parser(name)
        command.add_argument("--username", required=True)
        command.add_argument("--password", help="Avoid: appears in shell history")
        command.add_argument("--prompt", action="store_true", help="Ask for the password interactively")
        if name == "create-admin":
            command.add_argument("--role", choices=auth.ROLES, default="admin")
    sub.add_parser("list-users")
    args = parser.parse_args(argv)

    if auth.get_users_collection() is None:
        print("Không kết nối được MongoDB", file=sys.stderr)
        return 2

    if args.command == "list-users":
        for user in auth.get_users_collection().find({}, {"_id": 0, "password_hash": 0}):
            print(f"{user['username']:<24} {user.get('role', '?'):<8} last_login={user.get('last_login_at')}")
        return 0

    password, generated = _password_from_args(args)
    try:
        if args.command == "create-admin":
            auth.create_user(args.username, password, args.role, replace=False)
            action = "Đã tạo"
        else:
            existing = auth.find_user(args.username, use_cache=False)
            if not existing:
                print("Không có tài khoản này", file=sys.stderr)
                return 1
            auth.create_user(args.username, password, existing.get("role", "admin"), replace=True)
            action = "Đã đặt lại mật khẩu cho"
    except Exception as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    print(f"{action} tài khoản {args.username}")
    if generated:
        print(f"Mật khẩu (chỉ hiển thị một lần): {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
