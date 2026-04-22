"""Add role column to users table

Revision ID: d1e2f3g4h5i6
Revises: c1d2e3f4g5h6
Create Date: 2026-04-21

Adds a nullable VARCHAR(20) role column to the users table.
NULL means a regular chat user with no internal access.
Valid values: 'admin', 'supervisor', 'staff'.

A check constraint is added for DB-level validation.
No existing rows are modified — role defaults to NULL.

To assign a role in production:
    UPDATE users SET role = 'admin' WHERE email = 'staff@example.com';

To assign roles in bulk for a list of emails, see docs/role-assignment.md.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3g4h5i6"
down_revision: Union[str, None] = "c1d2e3f4g5h6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(20),
            nullable=True,
            comment="Internal staff role (admin/supervisor/staff). NULL = regular chat user.",
        ),
    )
    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_check_constraint(
        "ck_users_role_values",
        "users",
        "role IS NULL OR role IN ('admin', 'supervisor', 'staff')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role_values", "users", type_="check")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "role")
