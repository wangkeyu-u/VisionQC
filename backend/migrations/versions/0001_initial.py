"""Create VisionQC transactional, evidence, outbox, and append-only audit tables."""

from alembic import op

from app import models  # noqa: F401
from app.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


APPEND_ONLY_TABLES = (
    "audit_events",
    "state_transitions",
    "inference_results",
    "policy_decisions",
    "review_decisions",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION visionqc_reject_append_only_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        for table in APPEND_ONLY_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER {table}_append_only_update
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION visionqc_reject_append_only_mutation();
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER {table}_append_only_delete
                BEFORE DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION visionqc_reject_append_only_mutation();
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_update ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_delete ON {table}")
        op.execute("DROP FUNCTION IF EXISTS visionqc_reject_append_only_mutation()")
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=bind, checkfirst=True)
