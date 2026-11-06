"""Add tenant_sequences table for concurrency-safe BEO number allocation.

Revision ID: 0003_tenant_sequences
Revises: 0002_room_types_fields
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa
from app.database.migrations import ensure_tenant_sequences_table

revision = "0003_tenant_sequences"
down_revision = "0002_room_types_fields"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    ensure_tenant_sequences_table(bind.engine)

def downgrade():
    pass

