"""add call_sessions.language

Revision ID: 0018_add_call_session_language
Revises: 0017_exam_date_twelve_digit_student_card
Create Date: 2026-07-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0018_add_call_session_language"
down_revision = "0017_exam_date_twelve_digit_student_card"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add a non-nullable language column with a temporary server_default so existing
    # rows are populated. Make this idempotent and SQLite-safe: only add the column
    # if it doesn't already exist, and avoid ALTER COLUMN on SQLite (not supported).
    conn = op.get_bind()
    pragma = conn.execute(sa.text("PRAGMA table_info('call_sessions')")).fetchall()
    existing_cols = [r[1] for r in pragma]
    if "language" not in existing_cols:
        op.add_column(
            "call_sessions",
            sa.Column("language", sa.String(length=16), nullable=False, server_default=sa.text("'en'")),
        )

    # For non-SQLite dialects, remove the server_default for cleanliness.
    if conn.engine.dialect.name != "sqlite":
        with op.get_context().autocommit_block():
            op.alter_column("call_sessions", "language", server_default=None)


def downgrade() -> None:
    op.drop_column("call_sessions", "language")
