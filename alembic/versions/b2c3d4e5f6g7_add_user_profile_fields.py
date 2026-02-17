"""Add user profile fields (display_name, username, avatar_url)

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-13

Adds display_name, username (unique), avatar_url to users table for profile editing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("username", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(512), nullable=True))
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "username")
    op.drop_column("users", "display_name")
