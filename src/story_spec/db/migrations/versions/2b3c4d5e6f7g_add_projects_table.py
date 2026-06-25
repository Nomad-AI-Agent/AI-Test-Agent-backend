"""Add projects table and project_id to test_runs

Revision ID: 2b3c4d5e6f7g
Revises: e86134db5b19
Create Date: 2026-06-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b3c4d5e6f7g'
down_revision: Union[str, Sequence[str], None] = 'e86134db5b19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create projects table
    op.create_table('projects',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_projects_created_at'), 'projects', ['created_at'], unique=False)
    op.create_index(op.f('ix_projects_deleted_at'), 'projects', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_projects_user_id'), 'projects', ['user_id'], unique=False)

    # Add project_id column to test_runs
    op.add_column('test_runs',
        sa.Column('project_id', sa.UUID(), nullable=True)
    )
    op.create_index(op.f('ix_test_runs_project_id'), 'test_runs', ['project_id'], unique=False)
    op.create_foreign_key('fk_test_runs_project_id', 'test_runs', 'projects', ['project_id'], ['id'])

    # Update audit log enum
    op.execute("ALTER TYPE auditlogaction ADD VALUE IF NOT EXISTS 'PROJECT_CREATED'")
    op.execute("ALTER TYPE auditlogaction ADD VALUE IF NOT EXISTS 'PROJECT_UPDATED'")
    op.execute("ALTER TYPE auditlogaction ADD VALUE IF NOT EXISTS 'PROJECT_DELETED'")


def downgrade() -> None:
    """Downgrade schema."""
    # Remove foreign key and column from test_runs
    op.drop_constraint('fk_test_runs_project_id', 'test_runs', type_='foreignkey')
    op.drop_index(op.f('ix_test_runs_project_id'), table_name='test_runs')
    op.drop_column('test_runs', 'project_id')

    # Drop projects table
    op.drop_index(op.f('ix_projects_user_id'), table_name='projects')
    op.drop_index(op.f('ix_projects_deleted_at'), table_name='projects')
    op.drop_index(op.f('ix_projects_created_at'), table_name='projects')
    op.drop_table('projects')
