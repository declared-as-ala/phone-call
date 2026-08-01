"""Widen ``dtmf_buffer`` for ciphertext; add ``expected_digits_count``, ``buffer_updated_at``.

Clears legacy plaintext buffers (pre-encryption).

Revision ID: 0005_dtmf_buffer_encryption_and_meta
Revises: 0004_add_call_session_dtmf_buffer
Create Date: 2026-05-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_dtmf_buffer_encryption_and_meta"
down_revision: Union[str, None] = "0004_add_call_session_dtmf_buffer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return

    col_names = {c["name"] for c in insp.get_columns("call_sessions")}

    with op.batch_alter_table("call_sessions") as batch_op:
        if "expected_digits_count" not in col_names:
            batch_op.add_column(
                sa.Column(
                    "expected_digits_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="8",
                )
            )
        if "buffer_updated_at" not in col_names:
            batch_op.add_column(sa.Column("buffer_updated_at", sa.DateTime(timezone=True), nullable=True))

    if "dtmf_buffer" in col_names:
        with op.batch_alter_table("call_sessions") as batch_op:
            batch_op.alter_column(
                "dtmf_buffer",
                existing_type=sa.String(length=32),
                type_=sa.String(length=512),
                existing_nullable=False,
            )

    op.execute(sa.text("UPDATE call_sessions SET dtmf_buffer = ''"))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" not in insp.get_table_names():
        return
    col_names = {c["name"] for c in insp.get_columns("call_sessions")}
    with op.batch_alter_table("call_sessions") as batch_op:
        if "buffer_updated_at" in col_names:
            batch_op.drop_column("buffer_updated_at")
        if "expected_digits_count" in col_names:
            batch_op.drop_column("expected_digits_count")
        if "dtmf_buffer" in col_names:
            batch_op.alter_column(
                "dtmf_buffer",
                existing_type=sa.String(length=512),
                type_=sa.String(length=32),
                existing_nullable=False,
            )
