"""Initial schema: users, conversations, messages with soft delete

Revision ID: 8e2be79a3ff3
Revises: 
Create Date: 2026-02-02 21:17:02.676377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '8e2be79a3ff3'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create initial database schema with users, conversations, and messages tables.
    Includes proper indexes, foreign keys, and soft delete support.
    """
    # Create PostgreSQL ENUM type for message roles
    message_role_enum = postgresql.ENUM(
        "user",
        "assistant",
        "system",
        name="message_role",
        create_type=False,
    )
    message_role_enum.create(op.get_bind(), checkfirst=True)
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('last_active_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='users_pkey')
    )
    
    # Create index on users
    op.create_index('ix_users_created_at', 'users', ['created_at'], unique=False)
    
    # Create conversations table
    op.create_table(
        'conversations',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('is_archived', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='conversations_user_id_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='conversations_pkey')
    )
    
    # Create indexes on conversations
    op.create_index('ix_conversations_created_at', 'conversations', ['created_at'], unique=False)
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'], unique=False)
    op.create_index('ix_conversations_is_archived', 'conversations', ['is_archived'], unique=False)
    op.create_index('ix_conversations_user_archived', 'conversations', ['user_id', 'is_archived'], unique=False)
    
    # Create messages table
    op.create_table(
        'messages',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=False),
        sa.Column('role', message_role_enum, nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name='messages_conversation_id_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='messages_pkey')
    )
    
    # Create indexes on messages
    op.create_index('ix_messages_created_at', 'messages', ['created_at'], unique=False)
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'], unique=False)
    op.create_index('ix_messages_role', 'messages', ['role'], unique=False)
    op.create_index('ix_messages_deleted_at', 'messages', ['deleted_at'], unique=False)
    op.create_index('ix_messages_conversation_created', 'messages', ['conversation_id', 'created_at'], unique=False)


def downgrade() -> None:
    """
    Reverse the migration by dropping all tables and enum types.
    """
    # Drop indexes first (PostgreSQL automatically drops indexes when tables are dropped, but being explicit)
    op.drop_index('ix_messages_conversation_created', table_name='messages')
    op.drop_index('ix_messages_deleted_at', table_name='messages')
    op.drop_index('ix_messages_role', table_name='messages')
    op.drop_index('ix_messages_conversation_id', table_name='messages')
    op.drop_index('ix_messages_created_at', table_name='messages')
    
    op.drop_index('ix_conversations_user_archived', table_name='conversations')
    op.drop_index('ix_conversations_is_archived', table_name='conversations')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_index('ix_conversations_created_at', table_name='conversations')
    
    op.drop_index('ix_users_created_at', table_name='users')
    
    # Drop tables in correct order (children first to respect foreign keys)
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('users')
    
    # Drop ENUM type
    message_role_enum = postgresql.ENUM(
        "user",
        "assistant",
        "system",
        name="message_role",
        create_type=False,
    )
    message_role_enum.drop(op.get_bind(), checkfirst=True)
