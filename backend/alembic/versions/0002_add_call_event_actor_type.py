"""Safely add call_events.actor_type for legacy databases.

Adds ``actor_type`` with server default ``system`` only when the column is missing
(e.g. SQLite DBs created before the audit column existed).

Revision ID: 0002_add_call_event_actor_type
Revises: 0001_initial
Create Date: 2026-05-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_call_event_actor_type"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_events" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_events")}
    if "actor_type" in col_names:
        return
    with op.batch_alter_table("call_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "actor_type",
                sa.String(length=32),
                nullable=False,
                server_default="system",
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_events" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_events")}
    if "actor_type" not in col_names:
        return
    with op.batch_alter_table("call_events") as batch_op:
        batch_op.drop_column("actor_type")
