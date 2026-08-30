"""add generic four-layer tenant configuration and domain extension fields"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_platform_configuration"
down_revision: str | None = "0008_quality_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column(table: str, name: str, column: sa.Column[object]) -> None:
    if name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "tenant_configuration_versions" not in tables:
        op.create_table(
            "tenant_configuration_versions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("schema_version", sa.String(64), nullable=False),
            sa.Column("version", sa.String(128), nullable=False),
            sa.Column("config_hash", sa.String(64), nullable=False),
            sa.Column("effective_config", sa.JSON(), nullable=False),
            sa.Column("source_layers", sa.JSON(), nullable=False),
            sa.Column("validation_status", sa.String(32), nullable=False, server_default="VALID"),
            sa.Column(
                "audit_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
            ),
            sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("parent_version", sa.String(128)),
            sa.Column("activated_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "tenant_id", "version", name="uq_tenant_configuration_tenant_version"
            ),
        )
        op.create_index(
            "ix_tenant_configuration_versions_tenant_id",
            "tenant_configuration_versions",
            ["tenant_id"],
        )
        op.create_index(
            "ix_tenant_configuration_tenant_status",
            "tenant_configuration_versions",
            ["tenant_id", "status"],
        )
    if "workpieces" not in tables:
        op.create_table(
            "workpieces",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("workpiece_id", sa.String(128), nullable=False),
            sa.Column("product_code", sa.String(128), nullable=False),
            sa.Column("product_revision", sa.String(64)),
            sa.Column("batch_no", sa.String(128)),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("tenant_id", "workpiece_id", name="uq_workpiece_identity"),
        )
        op.create_index("ix_workpieces_tenant_id", "workpieces", ["tenant_id"])

    _add_column("inspections", "workpiece_id", sa.Column("workpiece_id", sa.String(128)))
    _add_column(
        "quality_incidents",
        "metadata",
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    _add_column(
        "deployment_packs",
        "configuration_version",
        sa.Column("configuration_version", sa.String(128)),
    )
    _add_column(
        "deployment_packs",
        "configuration_schema_version",
        sa.Column("configuration_schema_version", sa.String(64)),
    )
    _add_column(
        "deployment_packs",
        "configuration_hash",
        sa.Column("configuration_hash", sa.String(64)),
    )
    _add_column(
        "deployment_packs",
        "configuration_snapshot",
        sa.Column(
            "configuration_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
    )
    _add_column(
        "deployment_packs",
        "configuration_layers",
        sa.Column(
            "configuration_layers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
    )
    _add_column(
        "deployment_packs",
        "configuration_sources",
        sa.Column(
            "configuration_sources", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
    )
    _add_column(
        "deployment_packs",
        "configuration_validation_status",
        sa.Column(
            "configuration_validation_status",
            sa.String(32),
            nullable=False,
            server_default="VALID",
        ),
    )
    _add_column(
        "deployment_packs",
        "configuration_audit",
        sa.Column("configuration_audit", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "tenant_configuration_versions" in sa.inspect(bind).get_table_names():
        op.drop_index(
            "ix_tenant_configuration_tenant_status",
            table_name="tenant_configuration_versions",
        )
        op.drop_index(
            "ix_tenant_configuration_versions_tenant_id",
            table_name="tenant_configuration_versions",
        )
        op.drop_table("tenant_configuration_versions")
    if "workpieces" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_workpieces_tenant_id", table_name="workpieces")
        op.drop_table("workpieces")
    # SQLite cannot drop columns without a batch operation.  Leaving additive
    # columns in place is safer for a rollback of the application code and is
    # consistent with the older compatibility migrations.
