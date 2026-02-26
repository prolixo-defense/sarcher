"""add_scaled_discovery_fields

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-02-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a1b2c3d4"
down_revision: Union[str, None] = "d4e5f6a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to organizations table for scaled discovery
    op.add_column("organizations", sa.Column("cage_code", sa.String(length=10), nullable=True))
    op.add_column("organizations", sa.Column("uei", sa.String(length=12), nullable=True))
    op.add_column("organizations", sa.Column("naics_codes", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("size_band", sa.String(length=20), nullable=True))
    op.add_column("organizations", sa.Column("segment", sa.String(length=50), nullable=True))

    op.create_index("ix_organizations_cage_code", "organizations", ["cage_code"])
    op.create_index("ix_organizations_uei", "organizations", ["uei"])
    op.create_index("ix_organizations_segment", "organizations", ["segment"])


def downgrade() -> None:
    op.drop_index("ix_organizations_segment", table_name="organizations")
    op.drop_index("ix_organizations_uei", table_name="organizations")
    op.drop_index("ix_organizations_cage_code", table_name="organizations")

    op.drop_column("organizations", "segment")
    op.drop_column("organizations", "size_band")
    op.drop_column("organizations", "naics_codes")
    op.drop_column("organizations", "uei")
    op.drop_column("organizations", "cage_code")
