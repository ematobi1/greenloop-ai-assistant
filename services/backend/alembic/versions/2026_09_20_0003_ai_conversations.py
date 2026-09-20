"""AI conversations: owner scoping, message ordering, provider metadata

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

BACKFILL_SEQUENCE = """
UPDATE messages SET sequence = (
    SELECT COUNT(*) FROM messages AS earlier
    WHERE earlier.conversation_id = messages.conversation_id
      AND (earlier.created_at, earlier.id) <= (messages.created_at, messages.id)
)
"""


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column("owner", sa.String(50), nullable=False, server_default="local")
        )
        batch.add_column(sa.Column("provider", sa.String(50), nullable=True))
        batch.add_column(sa.Column("model", sa.String(100), nullable=True))
        batch.add_column(sa.Column("instructions", sa.Text(), nullable=True))
        batch.create_index(op.f("ix_conversations_owner"), ["owner"])

    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("status", sa.String(20), nullable=False, server_default="complete")
        )
        batch.add_column(sa.Column("provider", sa.String(50), nullable=True))
        batch.add_column(sa.Column("model", sa.String(100), nullable=True))

    op.execute(BACKFILL_SEQUENCE)

    with op.batch_alter_table("messages") as batch:
        batch.create_check_constraint(
            op.f("ck_messages_status_valid"), "status IN ('complete', 'incomplete', 'failed')"
        )
        batch.create_unique_constraint(
            op.f("uq_messages_conversation_id_sequence"), ["conversation_id", "sequence"]
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint(op.f("uq_messages_conversation_id_sequence"), type_="unique")
        batch.drop_constraint(op.f("ck_messages_status_valid"), type_="check")
        batch.drop_column("model")
        batch.drop_column("provider")
        batch.drop_column("status")
        batch.drop_column("sequence")

    with op.batch_alter_table("conversations") as batch:
        batch.drop_index(op.f("ix_conversations_owner"))
        batch.drop_column("instructions")
        batch.drop_column("model")
        batch.drop_column("provider")
        batch.drop_column("owner")
