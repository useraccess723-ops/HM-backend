"""Add tenant_integrations, integration_logs, and integration_idempotency_records tables.

Revision ID: 0004_ai_receptionist_integration
Revises: 0003_tenant_sequences
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_ai_receptionist_integration"
down_revision = "0003_tenant_sequences"
branch_labels = None
depends_on = None

def upgrade():
    # 1. tenant_integrations
    op.create_table(
        "tenant_integrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("integration_type", sa.String(50), nullable=False, server_default="ai_receptionist", index=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="disconnected"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=True, index=True),
        sa.Column("key_prefix", sa.String(16), nullable=True),
        sa.Column("key_last4", sa.String(8), nullable=True),
        sa.Column("webhook_url", sa.String(500), nullable=True),
        sa.Column("webhook_token", sa.String(64), nullable=True),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("scopes", sa.String(255), nullable=False, server_default="knowledge:read,rooms:read,reservations:read,reservations:create,escalations:create"),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "integration_type", name="uq_tenant_integration_type")
    )
    op.create_index("ix_tenant_integrations_tenant_type", "tenant_integrations", ["tenant_id", "integration_type"])

    # 2. integration_logs
    op.create_table(
        "integration_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("integration_id", sa.Integer(), sa.ForeignKey("tenant_integrations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("direction", sa.String(10), nullable=False, server_default="inbound"),
        sa.Column("event_type", sa.String(80), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("payload_summary", sa.String(255), nullable=True),
        sa.Column("request_sanitized", sa.Text(), nullable=True),
        sa.Column("response_sanitized", sa.Text(), nullable=True),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True)
    )
    op.create_index("ix_integration_logs_tenant_created", "integration_logs", ["tenant_id", "created_at"])

    # 3. integration_idempotency_records
    op.create_table(
        "integration_idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("integration_id", sa.Integer(), sa.ForeignKey("tenant_integrations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, index=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PROCESSING"),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("reservation_id", sa.Integer(), sa.ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "integration_id", "idempotency_key", name="uq_tenant_int_idempotency")
    )
    op.create_index("ix_idempotency_lookup", "integration_idempotency_records", ["tenant_id", "integration_id", "idempotency_key"])

def downgrade():
    op.drop_table("integration_idempotency_records")
    op.drop_table("integration_logs")
    op.drop_table("tenant_integrations")
