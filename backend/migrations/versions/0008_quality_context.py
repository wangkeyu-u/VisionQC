"""persist generic paint-quality context and image abstain flags"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_quality_context"
down_revision: str | None = "0007_dataset_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("inspections")}
    if "context_metadata" not in columns:
        op.add_column(
            "inspections",
            sa.Column(
                "context_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    if "quality_flags" not in columns:
        op.add_column(
            "inspections",
            sa.Column("quality_flags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("inspections")}
    for name in ("quality_flags", "context_metadata"):
        if name in columns:
            op.drop_column("inspections", name)
