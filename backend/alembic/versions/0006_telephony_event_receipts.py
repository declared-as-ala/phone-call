"""Telephony webhook idempotency: ``telephony_event_receipts``.

Revision ID: 0006_telephony_event_receipts
Revises: 0005_dtmf_buffer_encryption_and_meta
Create Date: 2026-05-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_telephony_event_receipts"
down_revision: Union[str, None] = "0005_dtmf_buffer_encryption_and_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "telephony_event_receipts" in insp.get_table_names():
        return
    op.create_table(
        "telephony_event_receipts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("call_id", sa.CHAR(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["call_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_telephony_event_receipt_provider_event",
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "telephony_event_receipts" in insp.get_table_names():
        op.drop_table("telephony_event_receipts")
