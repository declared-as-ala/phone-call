"""Add outbound_caller_id per call session."""

from alembic import op
import sqlalchemy as sa

revision: str = "0014_outbound_caller_id"
down_revision = "0013_call_session_outbound_trunk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column("outbound_caller_id", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("call_sessions", "outbound_caller_id")
