"""add_credit_usage_table

Revision ID: c3d4e5f6a1b2
Revises: 35e2930a2054
Create Date: 2026-02-24 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a1b2"
down_revision: Union[str, None] = "35e2930a2054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credit_usage",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("credits_used", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=True),
        sa.Column("endpoint", sa.String(length=100), nullable=True),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_credit_usage_provider_month",
        "credit_usage",
        ["provider", "month"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_credit_usage_provider_month", table_name="credit_usage")
    op.drop_table("credit_usage")
