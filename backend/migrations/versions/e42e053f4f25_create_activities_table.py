"""create activities table

Revision ID: e42e053f4f25
Revises: 
Create Date: 2026-11-08 14:58:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e42e053f4f25"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("origin_block", sa.String(), nullable=True),
        sa.Column("categories", sa.String(), nullable=True),
        sa.Column("duration_estimated_min", sa.Integer(), nullable=False),
        sa.Column("duration_estimated_max", sa.Integer(), nullable=False),
        sa.Column("source_duration", sa.String(), nullable=True),
        sa.Column("observation_annotation", sa.String(), nullable=True),
        sa.CheckConstraint("lat >= -90 AND lat <= 90", name="chk_lat_range"),
        sa.CheckConstraint("lon >= -180 AND lon <= 180", name="chk_lon_range"),
        sa.CheckConstraint(
            "duration_estimated_min > 0", name="chk_duration_min_positive"
        ),
        sa.CheckConstraint(
            "duration_estimated_min <= duration_estimated_max",
            name="chk_duration_min_lte_max",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("activities")