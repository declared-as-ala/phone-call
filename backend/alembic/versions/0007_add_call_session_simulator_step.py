"""Safely add missing ``call_sessions.simulator_step`` to legacy databases.

Revision ID: 0007_add_call_session_simulator_step
Revises: 0006_telephony_event_receipts
Create Date: 2026-05-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_add_call_session_simulator_step"
down_revision: Union[str, None] = "0006_telephony_event_receipts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "simulator_step" in col_names:
        return
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "simulator_step",
                sa.String(length=32),
                nullable=False,
                server_default="idle",
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "simulator_step" not in col_names:
        return
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("simulator_step")
