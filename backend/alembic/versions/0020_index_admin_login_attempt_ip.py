"""index admin login attempts by IP address

Revision ID: 0020_index_admin_login_attempt_ip
Revises: 0019_admin_login_attempts_and_token_version
Create Date: 2026-08-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0020_index_admin_login_attempt_ip"
down_revision = "0019_admin_login_attempts_and_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "admin_login_attempts" not in inspector.get_table_names():
        return
    existing = {index["name"] for index in inspector.get_indexes("admin_login_attempts")}
    if "ix_admin_login_attempts_ip_address" not in existing:
        op.create_index(
            "ix_admin_login_attempts_ip_address",
            "admin_login_attempts",
            ["ip_address"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "admin_login_attempts" not in inspector.get_table_names():
        return
    existing = {index["name"] for index in inspector.get_indexes("admin_login_attempts")}
    if "ix_admin_login_attempts_ip_address" in existing:
        op.drop_index("ix_admin_login_attempts_ip_address", table_name="admin_login_attempts")
