import argparse
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import AdminUser  # noqa: E402
from app.security import hash_password, validate_password_strength  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an admin user for the IVR dashboard.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--full-name", default=None)
    args = parser.parse_args()

    email = args.email.strip().lower()
    try:
        validate_password_strength(args.password)
    except ValueError as exc:
        print(f"Refusing weak password: {exc}", file=sys.stderr)
        return 1

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.scalar(select(AdminUser).where(AdminUser.email == email))
        if existing:
            print(f"Admin already exists: {email}")
            return 0

        admin = AdminUser(
            email=email,
            password_hash=hash_password(args.password),
            full_name=args.full_name,
        )
        db.add(admin)
        db.commit()
        print(f"Admin created: {email}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
