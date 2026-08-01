"""Add nullable ``call_sessions.ivr_outcome`` for terminal IVR disambiguation.

Revision ID: 0003_add_call_session_ivr_outcome
Revises: 0002_add_call_event_actor_type
Create Date: 2026-05-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_call_session_ivr_outcome"
down_revision: Union[str, None] = "0002_add_call_event_actor_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "ivr_outcome" in col_names:
        return
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.add_column(sa.Column("ivr_outcome", sa.String(length=32), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    if "ivr_outcome" not in col_names:
        return
    with op.batch_alter_table("call_sessions") as batch_op:
        batch_op.drop_column("ivr_outcome")
