"""Initial schema: call_sessions, call_events (with actor_type), verification_attempts.

Creates the full current model set when no ``call_sessions`` table exists (greenfield /
empty database). If tables already exist (e.g. legacy ``create_all``), this revision is a
no-op so a follow-up revision can add missing columns safely.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "call_sessions" in insp.get_table_names():
        return

    op.create_table(
        "call_sessions",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("university", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("verification_code_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column(
            "simulator_step",
            sa.String(length=32),
            nullable=False,
            server_default="idle",
        ),
        sa.Column(
            "wrong_code_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "call_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.CHAR(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "actor_type",
            sa.String(length=32),
            nullable=False,
            server_default="system",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["call_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "verification_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.CHAR(length=36), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("digit_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["call_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    for name in ("verification_attempts", "call_events", "call_sessions"):
        if name in insp.get_table_names():
            op.drop_table(name)
