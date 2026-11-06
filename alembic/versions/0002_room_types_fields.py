"""Add extended fields to room_types table.

Revision ID: 0002_room_types_fields
Revises: 0001_initial
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa
from app.database.migrations import ensure_room_type_columns

revision = "0002_room_types_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    ensure_room_type_columns(bind.engine)

def downgrade():
    pass
