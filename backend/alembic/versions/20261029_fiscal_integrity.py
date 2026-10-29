"""Separate fiscal previews, legacy evidence and persisted resolution identity."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261029_fiscal_integrity"
down_revision = "20261028_auth_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoice_resolutions",
        sa.Column(
            "is_sandbox", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "electronic_invoices",
        sa.Column("resolution_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "electronic_invoices",
        sa.Column(
            "execution_mode",
            sa.String(20),
            nullable=False,
            server_default="legacy_unverified",
        ),
    )
    op.create_foreign_key(
        "fk_invoice_resolution_identity",
        "electronic_invoices",
        "invoice_resolutions",
        ["resolution_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_invoice_execution_mode",
        "electronic_invoices",
        "execution_mode IN ('legacy_unverified','sandbox','real')",
    )
    op.create_index(
        "idx_invoice_resolution_date",
        "electronic_invoices",
        ["resolution_id", "issue_date"],
    )
    # Known local stubs are evidence of simulation. Do not alter historical status,
    # identifiers, legal totals or guess a resolution association.
    op.execute(
        sa.text(
            "UPDATE electronic_invoices SET execution_mode = 'sandbox' WHERE pdf_url LIKE 'stub://%'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "LOCK TABLE invoice_resolutions, electronic_invoices IN ACCESS EXCLUSIVE MODE"
        )
    )
    used = bind.execute(
        sa.text(
            "SELECT 1 FROM electronic_invoices WHERE resolution_id IS NOT NULL OR execution_mode <> 'legacy_unverified' LIMIT 1"
        )
    ).first()
    sandbox = bind.execute(
        sa.text("SELECT 1 FROM invoice_resolutions WHERE is_sandbox LIMIT 1")
    ).first()
    if used or sandbox:
        raise RuntimeError(
            "Cannot discard fiscal execution evidence; an explicit audited rollback is required"
        )
    op.drop_index("idx_invoice_resolution_date", table_name="electronic_invoices")
    op.drop_constraint(
        "ck_invoice_execution_mode", "electronic_invoices", type_="check"
    )
    op.drop_constraint(
        "fk_invoice_resolution_identity", "electronic_invoices", type_="foreignkey"
    )
    op.drop_column("electronic_invoices", "execution_mode")
    op.drop_column("electronic_invoices", "resolution_id")
    op.drop_column("invoice_resolutions", "is_sandbox")
