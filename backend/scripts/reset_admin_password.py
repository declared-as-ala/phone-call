"""Reset an existing admin password (production recovery)."""

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models import AdminUser  # noqa: E402
from app.security import hash_password  # noqa: E402
from scripts.create_admin import validate_password_strength  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset admin password by email.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    email = args.email.strip().lower()
    try:
        validate_password_strength(args.password)
    except ValueError as exc:
        print(f"Refusing weak password: {exc}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        admin = db.scalar(select(AdminUser).where(AdminUser.email == email))
        if not admin:
            print(f"No admin found: {email}", file=sys.stderr)
            return 1
        admin.password_hash = hash_password(args.password)
        admin.is_active = True
        db.add(admin)
        db.commit()
        print(f"Password updated for {email}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
