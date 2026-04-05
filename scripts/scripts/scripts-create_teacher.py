scripts/create_teacher.py

#!/usr/bin/env python3
# ════════════════════════════════════════════════════════════════════════
# Create or reset a teacher account.
#
# Usage:
#   python scripts/create_teacher.py <username> <password>
#   docker exec fotnssj-teacher python scripts/create_teacher.py alice pass
# ════════════════════════════════════════════════════════════════════════
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY",  "create-teacher-script")
os.environ.setdefault("ADMIN_USER",  "admin")
os.environ.setdefault("ADMIN_PASS",  "placeholder")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434")

import fotnssj


def create(username: str, password: str):
    auth = fotnssj.teacher_auth

    if len(password) < 12:
        print("Error: password must be at least 12 characters.")
        sys.exit(1)

    if username in auth._accounts:
        print(f"Account '{username}' already exists.")
        choice = input("Reset password? [y/N]: ").strip().lower()
        if choice != "y":
            print("Aborted.")
            sys.exit(0)
        del auth._accounts[username]

    ok = auth.create_account(username, password)
    if ok:
        print(f"✓ Teacher account created: {username}")
        print(f"  Login at: http://localhost:5002/teacher/login")
    else:
        print("Failed to create account.")
        sys.exit(1)


def list_teachers():
    auth = fotnssj.teacher_auth
    if not auth._accounts:
        print("No teacher accounts.")
        return
    print("Teacher accounts:")
    for u in auth._accounts:
        print(f"  - {u}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "list":
        list_teachers()
    elif cmd == "help" or len(sys.argv) < 3:
        print("Usage:")
        print("  python scripts/create_teacher.py <username> <password>")
        print("  python scripts/create_teacher.py list")
    else:
        create(sys.argv[1], sys.argv[2])