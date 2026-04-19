"""Add leads table for phone-capture lead persistence

Revision ID: c1d2e3f4g5h6
Revises: b2c3d4e5f6g7
Create Date: 2026-04-19

Creates the leads table that persists LeadDraft objects captured during the
phone-collection conversation flow.  Includes a lead_status ENUM and indexes
for efficient lookup by conversation, phone, and status.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID


revision: str = "c1d2e3f4g5h6"
down_revision: Union[str, None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    lead_status_enum = postgresql.ENUM(
        "new", "delivered", "failed", "closed",
        name="lead_status",
        create_type=False,
    )
    lead_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "leads",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("phone", sa.String(30), nullable=False),
        sa.Column("latest_intent", sa.String(100), nullable=False, server_default=""),
        sa.Column("latest_action", sa.String(100), nullable=False, server_default=""),
        sa.Column("summary_hint", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(50), nullable=False, server_default="chatbot"),
        sa.Column("status", lead_status_enum, nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="leads_pkey"),
    )

    op.create_index("ix_leads_created_at", "leads", ["created_at"], unique=False)
    op.create_index("ix_leads_conversation_id", "leads", ["conversation_id"], unique=False)
    op.create_index("ix_leads_status", "leads", ["status"], unique=False)
    op.create_index("ix_leads_conversation_phone", "leads", ["conversation_id", "phone"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_leads_conversation_phone", table_name="leads")
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_conversation_id", table_name="leads")
    op.drop_index("ix_leads_created_at", table_name="leads")
    op.drop_table("leads")

    lead_status_enum = postgresql.ENUM(
        "new", "delivered", "failed", "closed",
        name="lead_status",
        create_type=False,
    )
    lead_status_enum.drop(op.get_bind(), checkfirst=True)
