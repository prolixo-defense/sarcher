"""add_phase4_tables

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-02-24 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a1b2c3"
down_revision: Union[str, None] = "c3d4e5f6a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- campaigns ----------------------------------------------------------
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("target_filters", sa.Text(), nullable=True),
        sa.Column("settings", sa.Text(), nullable=True),
        sa.Column("stats", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])

    # ---- sequence_steps -----------------------------------------------------
    op.create_table(
        "sequence_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("template_id", sa.String(length=255), nullable=True),
        sa.Column("delay_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("condition", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sequence_steps_campaign_id", "sequence_steps", ["campaign_id"])

    # ---- messages -----------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=True),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("sentiment", sa.String(length=100), nullable=True),
        sa.Column("objection_type", sa.String(length=100), nullable=True),
        sa.Column("draft_response", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_lead_id", "messages", ["lead_id"])
    op.create_index("ix_messages_campaign_id", "messages", ["campaign_id"])
    op.create_index("ix_messages_status", "messages", ["status"])

    # ---- suppression_list ---------------------------------------------------
    op.create_table(
        "suppression_list",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_suppression_list_email", "suppression_list", ["email"])

    # ---- compliance_requests ------------------------------------------------
    op.create_table(
        "compliance_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_type", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compliance_requests_email", "compliance_requests", ["email"])


def downgrade() -> None:
    op.drop_index("ix_compliance_requests_email", table_name="compliance_requests")
    op.drop_table("compliance_requests")
    op.drop_index("ix_suppression_list_email", table_name="suppression_list")
    op.drop_table("suppression_list")
    op.drop_index("ix_messages_status", table_name="messages")
    op.drop_index("ix_messages_campaign_id", table_name="messages")
    op.drop_index("ix_messages_lead_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_sequence_steps_campaign_id", table_name="sequence_steps")
    op.drop_table("sequence_steps")
    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_table("campaigns")
