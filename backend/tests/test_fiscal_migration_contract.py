"""Preserve legacy fiscal columns and exercise the new migration on old rows."""

import importlib.util, json
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, update, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from tests.test_fiscal_integrity_postgresql import (
    fiscal_db,
    insert_invoice,
)  # noqa: F401
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_fiscal_integrity import rsa_key  # noqa: F401
from tests.orm_contract import detailed_mapping_contract
from app.models.fiscal import (
    ElectronicInvoice,
    InvoiceResolution,
    PaymentDistributionSnapshot,
    FiscalConfiguration,
    BankReconciliationRecord,
)

MODELS = [
    ElectronicInvoice,
    InvoiceResolution,
    PaymentDistributionSnapshot,
    FiscalConfiguration,
    BankReconciliationRecord,
]


def test_original_fiscal_columns_and_unchanged_tables_keep_their_contract():
    before = json.loads(
        (Path(__file__).parent / "fixtures/orm_fiscal_baseline.json").read_text()
    )
    current = detailed_mapping_contract(tuple(m.__tablename__ for m in MODELS))
    for model in MODELS:
        name = model.__tablename__
        table = model.__table__
        old = before[name]
        for colname, expected in old["columns"].items():
            c = table.c[colname]
            actual = {
                "sql_type": str(c.type.compile(dialect=postgresql.dialect())),
                "nullable": c.nullable,
                "primary_key": c.primary_key,
                "server_default": (
                    str(c.server_default.arg) if c.server_default else None
                ),
                "enum_create_type": getattr(c.type, "create_type", None),
            }
            assert actual == expected, (name, colname)
            assert current[name]["defaults"][colname] == old["defaults"][colname]
        assert current[name]["enums"] == old["enums"]
        assert current[name]["enum_options"] == old["enum_options"]
        assert [
            fk
            for fk in current[name]["foreign_keys"]
            if fk["column"] != "resolution_id"
        ] == old["foreign_keys"]
        assert all(index in current[name]["indexes"] for index in old["indexes"])
        if name not in ["electronic_invoices", "invoice_resolutions"]:
            assert current[name] == {k: v for k, v in old.items() if k != "columns"}
    assert "execution_mode" not in before["electronic_invoices"]["columns"]
    assert "is_sandbox" not in before["invoice_resolutions"]["columns"]


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261029_fiscal_integrity.py"
    spec = importlib.util.spec_from_file_location("fiscal_integrity_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_upgrade_marks_known_stubs_without_guessing_historical_acceptance_or_resolution(
    fiscal_db,
):
    sessions, _, oid, _ = fiscal_db
    async with sessions() as db:
        await db.execute(update(InvoiceResolution).values(is_sandbox=False))
        stub = await insert_invoice(
            db, oid, sequence_number=1, pdf_url="stub://historical.pdf"
        )
        unknown = await insert_invoice(
            db, oid, sequence_number=2, pdf_url="https://example.test/legacy.pdf"
        )
        sid, uid = stub.id, unknown.id
        await db.commit()
        conn = await db.connection()

        def upgrade(connection):
            m = migration()
            m.op = Operations(MigrationContext.configure(connection))
            m.downgrade()
            m.upgrade()

        await conn.run_sync(upgrade)
        await db.commit()
    async with sessions() as db:
        stub, unknown = await db.get(ElectronicInvoice, sid), await db.get(
            ElectronicInvoice, uid
        )
        assert (
            stub.execution_mode == "sandbox"
            and unknown.execution_mode == "legacy_unverified"
        )
        assert stub.status.value == unknown.status.value == "ACEPTADA"
        assert stub.resolution_id is unknown.resolution_id is None
        assert stub.grand_total_cents == unknown.grand_total_cents == 100
        assert not any((await db.scalars(select(InvoiceResolution.is_sandbox))).all())


@pytest.mark.asyncio
async def test_downgrade_refuses_to_discard_execution_evidence(fiscal_db):
    sessions, _, oid, ids = fiscal_db
    async with sessions() as db:
        await db.execute(update(InvoiceResolution).values(is_sandbox=False))
        await insert_invoice(db, oid, resolution_id=ids[0], execution_mode="sandbox")
        await db.commit()
        conn = await db.connection()

        def downgrade(connection):
            m = migration()
            m.op = Operations(MigrationContext.configure(connection))
            with pytest.raises(
                RuntimeError, match="Cannot discard fiscal execution evidence"
            ):
                m.downgrade()

        await conn.run_sync(downgrade)
    async with sessions() as db:
        assert await db.scalar(select(ElectronicInvoice.execution_mode)) == "sandbox"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "accepted", "stub", ""])
async def test_database_rejects_missing_or_unknown_execution_mode(fiscal_db, mode):
    sessions, _, oid, _ = fiscal_db
    async with sessions() as db:
        inv = await insert_invoice(db, oid)
        await db.commit()
        iid = inv.id
        with pytest.raises(IntegrityError):
            await db.execute(
                text(
                    "UPDATE electronic_invoices SET execution_mode=:mode WHERE id=:id"
                ),
                {"mode": mode, "id": iid},
            )
        await db.rollback()


@pytest.mark.asyncio
async def test_resolution_reference_cannot_point_to_another_or_deleted_record(
    fiscal_db,
):
    from uuid import uuid4

    sessions, _, oid, _ = fiscal_db
    async with sessions() as db:
        with pytest.raises(IntegrityError):
            await insert_invoice(db, oid, resolution_id=uuid4())
        await db.rollback()
