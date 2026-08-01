"""add admin_login_attempts table + admin_users.token_version

Revision ID: 0019_admin_login_attempts_and_token_version
Revises: 0018_add_call_session_language
Create Date: 2026-08-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0019_admin_login_attempts_and_token_version"
down_revision = "0018_add_call_session_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    admin_cols = [r[1] for r in conn.execute(sa.text("PRAGMA table_info('admin_users')")).fetchall()]
    if "token_version" not in admin_cols:
        op.add_column(
            "admin_users",
            sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        if conn.engine.dialect.name != "sqlite":
            with op.get_context().autocommit_block():
                op.alter_column("admin_users", "token_version", server_default=None)

    existing_tables = sa.inspect(conn).get_table_names()
    if "admin_login_attempts" not in existing_tables:
        op.create_table(
            "admin_login_attempts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("ip_address", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_admin_login_attempts_email", "admin_login_attempts", ["email"]
        )
        op.create_index(
            "ix_admin_login_attempts_created_at", "admin_login_attempts", ["created_at"]
        )


def downgrade() -> None:
    op.drop_index("ix_admin_login_attempts_created_at", table_name="admin_login_attempts")
    op.drop_index("ix_admin_login_attempts_email", table_name="admin_login_attempts")
    op.drop_table("admin_login_attempts")
    op.drop_column("admin_users", "token_version")
