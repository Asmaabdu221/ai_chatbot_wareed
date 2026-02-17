"""Add user email and password_hash for JWT authentication

Revision ID: a1b2c3d4e5f6
Revises: 8e2be79a3ff3
Create Date: 2026-02-05

Adds email (unique, nullable) and password_hash (nullable) to users table
for platform-agnostic JWT auth (Web + Mobile). Existing anonymous users keep NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "8e2be79a3ff3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
