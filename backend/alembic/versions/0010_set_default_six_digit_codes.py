"""Use six digit verification codes by default.

Revision ID: 0010_set_default_six_digit_codes
Revises: 0009_add_admin_users
Create Date: 2026-05-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_set_default_six_digit_codes"
down_revision: Union[str, None] = "0009_add_admin_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "expected_digits_count" not in col_names:
        return
    op.execute("UPDATE call_sessions SET expected_digits_count = 6 WHERE expected_digits_count = 8")


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "expected_digits_count" not in col_names:
        return
    op.execute("UPDATE call_sessions SET expected_digits_count = 8 WHERE expected_digits_count = 6")
