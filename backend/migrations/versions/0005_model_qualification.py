"""add tenant/product scoped model qualification lifecycle"""

from collections.abc import Sequence

from alembic import op

from app import models  # noqa: F401
from app.database import Base

revision: str = "0005_model_qualification"
down_revision: str | None = "0004_edge_gateway_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    models.ModelQualification.__table__.drop(bind=op.get_bind(), checkfirst=True)
