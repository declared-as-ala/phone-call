"""Add speech_volume_percent per call session."""

from alembic import op
import sqlalchemy as sa

revision: str = "0016_speech_volume"
down_revision = "0015_speech_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column(
            "speech_volume_percent",
            sa.Integer(),
            nullable=False,
            server_default="88",
        ),
    )


def downgrade() -> None:
    op.drop_column("call_sessions", "speech_volume_percent")
