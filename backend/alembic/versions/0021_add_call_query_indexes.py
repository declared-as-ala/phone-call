"""add indexes used by call history and event queries

Revision ID: 0021_add_call_query_indexes
Revises: 0020_index_admin_login_attempt_ip
Create Date: 2026-08-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0021_add_call_query_indexes"
down_revision = "0020_index_admin_login_attempt_ip"
branch_labels = None
depends_on = None

_INDEXES = (
    ("call_events", "ix_call_events_session_id", ["session_id"]),
    ("call_sessions", "ix_call_sessions_status", ["status"]),
    ("call_sessions", "ix_call_sessions_created_at", ["created_at"]),
)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())
    for table_name, index_name, columns in _INDEXES:
        if table_name not in tables:
            continue
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name not in existing:
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())
    for table_name, index_name, _columns in reversed(_INDEXES):
        if table_name not in tables:
            continue
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)
