"""Add admin users table.

Revision ID: 0009_add_admin_users
Revises: 0008_add_call_session_wrong_code_attempts
Create Date: 2026-05-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_add_admin_users"
down_revision: Union[str, None] = "0008_add_call_session_wrong_code_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "admin_users" in insp.get_table_names():
        return
    op.create_table(
        "admin_users",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_users_email", "admin_users", ["email"], unique=True)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "admin_users" not in insp.get_table_names():
        return
    op.drop_index("ix_admin_users_email", table_name="admin_users")
    op.drop_table("admin_users")
