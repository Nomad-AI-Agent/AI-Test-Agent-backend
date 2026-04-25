"""Initial migration: users, test_runs, tokens, and audit logs

Revision ID: e86134db5b19
Revises: 
Create Date: 2026-04-25 23:32:50.791900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e86134db5b19'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:   
    # Create users table
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('full_name', sa.String(length=255), nullable=True),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('email_verified', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_created_at'), 'users', ['created_at'], unique=False)
    op.create_index(op.f('ix_users_deleted_at'), 'users', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_is_active'), 'users', ['is_active'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    
    # Create refresh_tokens table
    op.create_table('refresh_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token', sa.String(length=500), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_tokens_expires_at'), 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_revoked'), 'refresh_tokens', ['revoked'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_token'), 'refresh_tokens', ['token'], unique=True)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    
    # Create api_tokens table
    op.create_table('api_tokens',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('token_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_tokens_deleted_at'), 'api_tokens', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_api_tokens_expires_at'), 'api_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_api_tokens_is_active'), 'api_tokens', ['is_active'], unique=False)
    op.create_index(op.f('ix_api_tokens_token_hash'), 'api_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_api_tokens_user_id'), 'api_tokens', ['user_id'], unique=False)
    
    # Create new test_runs table with UUID support
    op.create_table('test_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('story', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('steps_json', sa.Text(), nullable=False, server_default='[]'),
    sa.Column('results_json', sa.Text(), nullable=False, server_default='[]'),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('total_duration_ms', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('overall_status', sa.String(length=50), nullable=False, server_default='pending'),
    sa.Column('goal_achieved', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_test_runs_status', 'test_runs', ['overall_status'], unique=False)
    op.create_index('idx_test_runs_user_created', 'test_runs', ['user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_test_runs_created_at'), 'test_runs', ['created_at'], unique=False)
    op.create_index(op.f('ix_test_runs_deleted_at'), 'test_runs', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_test_runs_overall_status'), 'test_runs', ['overall_status'], unique=False)
    op.create_index(op.f('ix_test_runs_user_id'), 'test_runs', ['user_id'], unique=False)
    
    # Create audit_logs table
    op.create_table('audit_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.Enum('USER_LOGIN', 'USER_LOGOUT', 'USER_CREATED', 'USER_UPDATED', 'USER_DELETED', 'TEST_RUN_CREATED', 'TEST_RUN_UPDATED', 'TEST_RUN_DELETED', 'API_TOKEN_CREATED', 'API_TOKEN_REVOKED', 'PASSWORD_CHANGED', 'EMAIL_VERIFIED', name='auditlogaction'), nullable=False),
    sa.Column('resource_type', sa.String(length=100), nullable=False),
    sa.Column('resource_id', sa.String(length=100), nullable=True),
    sa.Column('test_run_id', sa.UUID(), nullable=True),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['test_run_id'], ['test_runs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_audit_logs_created', 'audit_logs', ['created_at'], unique=False)
    op.create_index('idx_audit_logs_user_action', 'audit_logs', ['user_id', 'action'], unique=False)
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_test_run_id'), 'audit_logs', ['test_run_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop all new tables
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_test_run_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_index('idx_audit_logs_user_action', table_name='audit_logs')
    op.drop_index('idx_audit_logs_created', table_name='audit_logs')
    op.drop_table('audit_logs')
    
    op.drop_index(op.f('ix_test_runs_user_id'), table_name='test_runs')
    op.drop_index(op.f('ix_test_runs_overall_status'), table_name='test_runs')
    op.drop_index(op.f('ix_test_runs_deleted_at'), table_name='test_runs')
    op.drop_index(op.f('ix_test_runs_created_at'), table_name='test_runs')
    op.drop_index('idx_test_runs_user_created', table_name='test_runs')
    op.drop_index('idx_test_runs_status', table_name='test_runs')
    op.drop_table('test_runs')
    
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_token'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_revoked'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_expires_at'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    
    op.drop_index(op.f('ix_api_tokens_user_id'), table_name='api_tokens')
    op.drop_index(op.f('ix_api_tokens_token_hash'), table_name='api_tokens')
    op.drop_index(op.f('ix_api_tokens_is_active'), table_name='api_tokens')
    op.drop_index(op.f('ix_api_tokens_expires_at'), table_name='api_tokens')
    op.drop_index(op.f('ix_api_tokens_deleted_at'), table_name='api_tokens')
    op.drop_table('api_tokens')
    
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_is_active'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_deleted_at'), table_name='users')
    op.drop_index(op.f('ix_users_created_at'), table_name='users')
    op.drop_table('users')
