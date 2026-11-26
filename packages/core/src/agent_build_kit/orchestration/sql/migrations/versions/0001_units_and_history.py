"""The units and unit_history tables.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "units",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("body", sa.JSON, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "unit_history",
        sa.Column("unit_id", sa.String, sa.ForeignKey("units.id"), primary_key=True),
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("entry", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("unit_history")
    op.drop_table("units")
