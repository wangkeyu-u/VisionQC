"""bind qualification records to immutable dataset source identities"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_dataset_binding"
down_revision: str | None = "0006_dataset_registrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("model_qualifications")}
    for name in ("dataset_registration_id", "dataset_source_type", "dataset_fingerprint"):
        if name not in columns:
            op.add_column("model_qualifications", sa.Column(name, sa.String(64), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("model_qualifications")}
    for name in ("dataset_fingerprint", "dataset_source_type", "dataset_registration_id"):
        if name in columns:
            op.drop_column("model_qualifications", name)
