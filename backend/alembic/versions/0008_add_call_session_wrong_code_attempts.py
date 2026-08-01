"""Safely add missing ``call_sessions.wrong_code_attempts`` to legacy databases.

Revision ID: 0008_add_call_session_wrong_code_attempts
Revises: 0007_add_call_session_simulator_step
Create Date: 2026-05-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_call_session_wrong_code_attempts"
down_revision: Union[str, None] = "0007_add_call_session_simulator_step"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "wrong_code_attempts" in col_names:
        return
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "wrong_code_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "wrong_code_attempts" not in col_names:
        return
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("wrong_code_attempts")
