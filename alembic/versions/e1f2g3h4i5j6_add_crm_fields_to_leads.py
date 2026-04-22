"""Add CRM sync fields to leads table

Revision ID: e1f2g3h4i5j6
Revises: d1e2f3g4h5i6
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2g3h4i5j6"
down_revision: Union[str, None] = "d1e2f3g4h5i6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column(
            "crm_status",
            sa.String(length=30),
            nullable=False,
            server_default="pending",
            comment="CRM sync state (pending/synced/failed/disabled)",
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "crm_provider",
            sa.String(length=50),
            nullable=True,
            comment="CRM provider key used for the last sync attempt",
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "crm_external_id",
            sa.String(length=255),
            nullable=True,
            comment="External CRM lead identifier returned by provider",
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "crm_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of the latest CRM sync attempt",
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "crm_error_message",
            sa.Text(),
            nullable=True,
            comment="Latest CRM sync error message when crm_status=failed",
        ),
    )
    op.add_column(
        "leads",
        sa.Column(
            "crm_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of CRM retry attempts after initial sync failure",
        ),
    )
    op.create_index("ix_leads_crm_status", "leads", ["crm_status"], unique=False)

    # Keep defaults for existing rows, but rely on application defaults for new writes.
    op.alter_column("leads", "crm_status", server_default=None)
    op.alter_column("leads", "crm_retry_count", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_leads_crm_status", table_name="leads")
    op.drop_column("leads", "crm_retry_count")
    op.drop_column("leads", "crm_error_message")
    op.drop_column("leads", "crm_last_attempt_at")
    op.drop_column("leads", "crm_external_id")
    op.drop_column("leads", "crm_provider")
    op.drop_column("leads", "crm_status")
