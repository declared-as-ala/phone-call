"""Set final default for code_sent_prompt using {code_length} placeholder."""

from __future__ import annotations

import datetime as dt
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_code_sent_code_length_placeholder"
down_revision: Union[str, None] = "0011_speech_scripts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TEMPLATE = (
    "Your verification code has been sent to your device. "
    "Please enter the {code_length} digit code now."
)
LEGACY_TEMPLATE = (
    "Your verification code has been sent to your device. "
    "Please enter the 6 digit code now."
)


def upgrade() -> None:
    conn = op.get_bind()
    now = dt.datetime.now(dt.timezone.utc)
    conn.execute(
        sa.text(
            "UPDATE speech_script_templates SET template = :t, updated_at = :u "
            "WHERE script_key = 'code_sent_prompt'"
        ),
        {"t": NEW_TEMPLATE, "u": now},
    )


def downgrade() -> None:
    conn = op.get_bind()
    now = dt.datetime.now(dt.timezone.utc)
    conn.execute(
        sa.text(
            "UPDATE speech_script_templates SET template = :t, updated_at = :u "
            "WHERE script_key = 'code_sent_prompt'"
        ),
        {"t": LEGACY_TEMPLATE, "u": now},
    )
