"""Speech script templates KV table.

Revision ID: 0011_speech_scripts
Revises: 0010_set_default_six_digit_codes
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_speech_scripts"
down_revision: Union[str, None] = "0010_set_default_six_digit_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_ROWS: tuple[tuple[str, str], ...] = (
    (
        "consent_prompt",
        "Hello {name}. This is {organization}. You have an exam verification. "
        "To continue, press 1 or 2.",
    ),
    ("declined_prompt", "Verification declined. Goodbye."),
    (
        "admin_send_code_instruction_prompt",
        "Please wait while the administrator sends your verification code.",
    ),
    (
        "code_sent_prompt",
        "Your verification code has been sent to your device. Please enter the {code_length} digit code now.",
    ),
    ("pending_admin_verification_prompt", "Please wait while the administrator verifies your code."),
    ("approved_prompt", "Approved. Thank you."),
    ("rejected_retry_prompt", "Code not verified. Please try again."),
    ("failed_prompt", "Verification failed. Please contact the administration."),
    ("goodbye_prompt", "Thank you. Goodbye."),
)


def upgrade() -> None:
    op.create_table(
        "speech_script_templates",
        sa.Column("script_key", sa.String(length=64), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("script_key", name="pk_speech_script_templates"),
    )
    conn = op.get_bind()
    now = dt.datetime.now(dt.timezone.utc)
    for key, template in DEFAULT_ROWS:
        conn.execute(
            sa.text(
                "INSERT INTO speech_script_templates (script_key, template, updated_at) "
                "VALUES (:script_key, :template, :updated_at)"
            ),
            {"script_key": key, "template": template, "updated_at": now},
        )


def downgrade() -> None:
    op.drop_table("speech_script_templates")
