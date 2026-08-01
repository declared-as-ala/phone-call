"""Add ``call_sessions.dtmf_buffer`` for webhook DTMF digit accumulation.

Revision ID: 0004_add_call_session_dtmf_buffer
Revises: 0003_add_call_session_ivr_outcome
Create Date: 2026-05-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_call_session_dtmf_buffer"
down_revision: Union[str, None] = "0003_add_call_session_ivr_outcome"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "dtmf_buffer" in col_names:
        return
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("dtmf_buffer", sa.String(length=32), nullable=False, server_default="")
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "dtmf_buffer" not in col_names:
        return
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("dtmf_buffer")
