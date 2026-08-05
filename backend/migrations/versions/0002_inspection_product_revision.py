"""add inspection product revision

Revision ID: 0002_inspection_product_revision
Revises: 0001_initial
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_inspection_product_revision"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("inspections")}
    if "product_revision" not in columns:
        op.add_column("inspections", sa.Column("product_revision", sa.String(length=64)))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("inspections")}
    if "product_revision" in columns:
        op.drop_column("inspections", "product_revision")
