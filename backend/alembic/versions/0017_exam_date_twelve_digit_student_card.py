"""Add exam_date; default student card entry to 12 digits (6+4+2).

Revision ID: 0017
Revises: 0016
"""

from alembic import op
import sqlalchemy as sa

revision = "0017_exam_date_twelve_digit_student_card"
down_revision = "0016_speech_volume"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "exam_date" not in col_names:
        op.add_column(
            "call_sessions",
            sa.Column("exam_date", sa.String(length=32), nullable=False, server_default=""),
        )
    if "expected_digits_count" in col_names:
        op.execute(
            "UPDATE call_sessions SET expected_digits_count = 12 "
            "WHERE expected_digits_count IN (6, 8)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "exam_date" in col_names:
        op.drop_column("call_sessions", "exam_date")
