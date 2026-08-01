"""Add speech_engine and luvvoice_voice_id per call session."""

from alembic import op
import sqlalchemy as sa

revision: str = "0015_speech_engine"
down_revision = "0014_outbound_caller_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column(
            "speech_engine",
            sa.String(length=16),
            nullable=False,
            server_default="luvvoice",
        ),
    )
    op.add_column(
        "call_sessions",
        sa.Column("luvvoice_voice_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("call_sessions", "luvvoice_voice_id")
    op.drop_column("call_sessions", "speech_engine")
