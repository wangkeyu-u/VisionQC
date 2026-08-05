"""add the canonical Deployment Pack manifest"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_deployment_manifest"
down_revision: str | None = "0002_inspection_product_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_manifest() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == "manifest" for column in inspector.get_columns("deployment_packs"))


def upgrade() -> None:
    # 0001 creates tables from the live metadata, so a brand-new database may
    # already have the column.  The guard also keeps upgrades safe for the
    # pre-manifest schema that existed in the first release.
    if not _has_manifest():
        op.add_column(
            "deployment_packs",
            sa.Column("manifest", sa.JSON(), nullable=True, server_default=sa.text("'{}'")),
        )
    op.execute(
        sa.text("UPDATE deployment_packs SET manifest = '{}' WHERE manifest IS NULL")
    )
    op.alter_column("deployment_packs", "manifest", nullable=False)


def downgrade() -> None:
    if _has_manifest():
        op.drop_column("deployment_packs", "manifest")
