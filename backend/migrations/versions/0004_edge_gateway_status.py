"""add tenant-scoped edge gateway heartbeat status"""

from collections.abc import Sequence

from alembic import op

from app import models  # noqa: F401
from app.database import Base

revision: str = "0004_edge_gateway_status"
down_revision: str | None = "0003_deployment_manifest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The first migration creates tables from live metadata for fresh SQLite
    # demo databases.  create_all is therefore idempotent for both fresh and
    # upgraded installations and adds only the new gateway table when needed.
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    models.EdgeGateway.__table__.drop(bind=bind, checkfirst=True)
