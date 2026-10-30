"""Native fiscal reservations, quotas, durable evidence and HTTP contracts."""

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, func, update
from sqlalchemy.exc import IntegrityError
from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_fiscal_integrity import rsa_key  # noqa: F401
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.models.rider import Rider
from app.models.fiscal import (
    ElectronicInvoice,
    InvoiceResolution,
    FiscalConfiguration,
    PaymentDistributionSnapshot,
    BankReconciliationRecord,
    InvoiceStatus,
    CountryTaxRegime,
)
from app.services.invoicing_engine import (
    InvoicingEngine,
    InvoiceSubmissionError,
    DianColombiaAdapter,
)
from app.services.fiscal_integrity import invoice_evidence
from app.api.v1 import fiscal


@pytest.fixture
async def fiscal_db(pg_wallets, monkeypatch, rsa_key):
    sessions, _, _ = pg_wallets
    monkeypatch.setattr(settings, "ENABLE_ELECTRONIC_INVOICING", True)
    monkeypatch.setattr(settings, "FISCAL_SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "APP_ENV", "testing")
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    monkeypatch.setattr(settings, "INVOICE_DAILY_LIMIT", 500)
    monkeypatch.setattr(settings, "FISCAL_DEFAULT_COUNTRY", "CO")
    async with sessions() as db:
        await db.execute(
            text(
                "CREATE TABLE orders (id UUID PRIMARY KEY, status VARCHAR(30) DEFAULT 'ENTREGADO')"
            )
        )
        await db.execute(text("CREATE TABLE zones (id UUID PRIMARY KEY)"))
        conn = await db.connection()
        await conn.run_sync(
            lambda c: Rider.__table__.c.status.type.create(c, checkfirst=True)
        )
        await db.execute(
            text(
                "ALTER TABLE riders ADD COLUMN status riderstatus NOT NULL DEFAULT 'ACTIVO'"
            )
        )
        for model in [
            InvoiceResolution,
            ElectronicInvoice,
            FiscalConfiguration,
            PaymentDistributionSnapshot,
            BankReconciliationRecord,
        ]:
            for column in model.__table__.columns:
                if hasattr(column.type, "create"):
                    await conn.run_sync(
                        lambda c, t=column.type: t.create(c, checkfirst=True)
                    )
            await conn.run_sync(model.__table__.create)
        uid = await db.scalar(select(User.id).limit(1))
        user = await db.get(User, uid)
        user.role = UserRole.GERENTE
        oid = uuid4()
        await db.execute(text("INSERT INTO orders(id) VALUES(:id)"), {"id": oid})
        resolutions = []
        for country, start, preview in [
            (CountryTaxRegime.COLOMBIA, 100, True),
            (CountryTaxRegime.MEXICO, 1000, True),
            (CountryTaxRegime.COLOMBIA, 200, False),
        ]:
            row = InvoiceResolution(
                prefix=("SBX" if preview else "REAL") + country.value,
                start_range=start,
                end_range=start + 20,
                current_counter=0,
                valid_from=date.today() - timedelta(days=1),
                valid_until=date.today() + timedelta(days=10),
                is_active=True,
                is_sandbox=preview,
                country_code=country,
                private_key_path=str(rsa_key[0]),
            )
            db.add(row)
            resolutions.append(row)
        await db.commit()
        ids = [r.id for r in resolutions]
    return sessions, uid, oid, ids


async def create(sessions, oid, **options):
    async with sessions() as db:
        return await InvoicingEngine(db).create_electronic_invoice(
            oid,
            {"name": "Test customer"},
            [{"name": "Delivery", "unit_price_cents": 116001, "quantity": 1}],
            preview=options.pop("preview", True),
            **options,
        )


@pytest.mark.asyncio
async def test_cancelled_order_cannot_reserve_fiscal_number_or_create_evidence(
    fiscal_db,
):
    from app.core.exceptions import AppException

    sessions, _, oid, _ = fiscal_db
    async with sessions() as db:
        await db.execute(
            text("UPDATE orders SET status='CANCELADO' WHERE id=:id"), {"id": oid}
        )
        await db.commit()
        counters = list(
            (
                await db.scalars(
                    select(InvoiceResolution.current_counter).order_by(
                        InvoiceResolution.id
                    )
                )
            ).all()
        )
    with pytest.raises(AppException) as error:
        await create(sessions, oid)
    assert error.value.status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ElectronicInvoice)) == 0
        assert (
            list(
                (
                    await db.scalars(
                        select(InvoiceResolution.current_counter).order_by(
                            InvoiceResolution.id
                        )
                    )
                ).all()
            )
            == counters
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "country,currency,start",
    [(CountryTaxRegime.COLOMBIA, "COP", 100), (CountryTaxRegime.MEXICO, "MXN", 1000)],
)
async def test_preview_is_pending_and_never_gets_official_identifiers(
    fiscal_db, country, currency, start
):
    sessions, _, oid, _ = fiscal_db
    invoice = await create(sessions, oid, country=country)
    assert (
        invoice.status is InvoiceStatus.PENDIENTE
        and invoice.execution_mode == "sandbox"
    )
    assert invoice.sequence_number == start and invoice.resolution_id is not None
    assert invoice.unique_identifier is invoice.pdf_url is invoice.qr_code_url is None
    assert invoice.currency_code == currency and invoice.exchange_rate == Decimal(
        "1.0000"
    )
    assert (
        invoice.signed_xml_content
        and not invoice_evidence(invoice)["is_officially_accepted"]
    )
    assert (
        invoice.grand_total_cents
        == invoice.subtotal_cents
        + invoice.tax_total_cents
        - invoice.retention_total_cents
    )
    if country is CountryTaxRegime.MEXICO:
        assert invoice.grand_total_cents == 116001


@pytest.mark.asyncio
async def test_concurrent_allocations_start_at_range_and_never_repeat(fiscal_db):
    sessions, _, oid, ids = fiscal_db

    async def allocate():
        async with sessions() as db:
            stale = await db.get(InvoiceResolution, ids[0])
            value = await InvoicingEngine(db)._next_sequence(stale)
            await db.commit()
            return value

    values = await asyncio.gather(*(allocate() for _ in range(8)))
    assert sorted(values) == list(range(100, 108))


@pytest.mark.asyncio
async def test_quota_is_serialized_with_reservation(fiscal_db, monkeypatch):
    sessions, _, oid, _ = fiscal_db
    monkeypatch.setattr(settings, "INVOICE_DAILY_LIMIT", 2)
    results = await asyncio.gather(
        *(create(sessions, oid) for _ in range(4)), return_exceptions=True
    )
    assert sum(isinstance(r, ElectronicInvoice) for r in results) == 2
    assert sum(isinstance(r, InvoiceSubmissionError) for r in results) == 2
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ElectronicInvoice)) == 2
        seq = list(
            (
                await db.scalars(
                    select(ElectronicInvoice.sequence_number).order_by(
                        ElectronicInvoice.sequence_number
                    )
                )
            ).all()
        )
        assert seq == [100, 101]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["exhausted", "inactive", "expired", "deleted"])
async def test_allocation_rechecks_current_database_row(fiscal_db, change):
    sessions, _, _, ids = fiscal_db
    async with sessions() as reader:
        stale = await reader.get(InvoiceResolution, ids[0])
        async with sessions() as writer:
            row = await writer.get(InvoiceResolution, ids[0])
            if change == "exhausted":
                row.current_counter = row.end_range
            elif change == "inactive":
                row.is_active = False
            elif change == "expired":
                row.valid_until = date.today() - timedelta(days=1)
            else:
                await writer.delete(row)
            await writer.commit()
        with pytest.raises(InvoiceSubmissionError):
            await InvoicingEngine(reader)._next_sequence(stale)


async def insert_invoice(db, oid, **extra):
    values = dict(
        order_id=oid,
        resolution_number=100,
        sequence_number=100,
        issue_date=date.today(),
        issue_time=datetime.min.time(),
        provider_type=CountryTaxRegime.COLOMBIA,
        currency_code="COP",
        exchange_rate=Decimal("1"),
        subtotal_cents=100,
        tax_total_cents=0,
        retention_total_cents=0,
        grand_total_cents=100,
        status=InvoiceStatus.ACEPTADA,
    )
    values.update(extra)
    row = ElectronicInvoice(**values)
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_legacy_history_prevents_reuse_after_old_counter_off_by_one(fiscal_db):
    sessions, _, oid, ids = fiscal_db
    async with sessions() as db:
        await insert_invoice(db, oid, sequence_number=101)
        row = await db.get(InvoiceResolution, ids[0])
        row.current_counter = 100
        await db.commit()
    invoice = await create(sessions, oid)
    assert invoice.sequence_number == 102


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_number_and_reservation(fiscal_db, monkeypatch):
    sessions, _, oid, ids = fiscal_db
    async with sessions() as db:

        async def fail():
            raise RuntimeError("injected reservation failure")

        monkeypatch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError):
            await InvoicingEngine(db).create_electronic_invoice(
                oid, {}, [{"unit_price_cents": 100, "quantity": 1}], preview=True
            )
        await db.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ElectronicInvoice)) == 0
        assert (
            await db.scalar(
                select(InvoiceResolution.current_counter).where(
                    InvoiceResolution.id == ids[0]
                )
            )
            == 0
        )


class TestAcknowledgedProvider(DianColombiaAdapter):
    __test__ = False

    def supports_real_submission(self):
        return True

    async def submit_to_authority(self, document, signature):
        assert signature and document
        return {
            "accepted": True,
            "unique_identifier": "OFFLINE-TEST-ACCEPTANCE",
            "pdf_url": "https://example.test/document.pdf",
        }


@pytest.mark.asyncio
async def test_only_explicit_verifiable_acknowledgment_records_real_acceptance(
    fiscal_db, monkeypatch
):
    from app.services import invoicing_engine as module

    sessions, _, oid, ids = fiscal_db
    monkeypatch.setitem(
        module.PROVIDERS, CountryTaxRegime.COLOMBIA, TestAcknowledgedProvider
    )
    invoice = await create(sessions, oid, preview=False)
    assert invoice.status is InvoiceStatus.ACEPTADA and invoice.execution_mode == "real"
    assert invoice.resolution_id == ids[2] and invoice.sequence_number == 200
    assert invoice_evidence(invoice)["is_officially_accepted"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"accepted": False, "unique_identifier": "ID"},
        {"accepted": True, "unique_identifier": ""},
        {"accepted": True, "unique_identifier": "sandbox:fake"},
        {"accepted": True, "unique_identifier": "bad id"},
        {"accepted": True, "unique_identifier": "ID", "pdf_url": "javascript:alert(1)"},
        {
            "accepted": True,
            "unique_identifier": "ID",
            "pdf_url": "https://user:secret@example.test/file",
        },
    ],
)
async def test_unverified_response_never_becomes_accepted(fiscal_db, monkeypatch, bad):
    from app.services import invoicing_engine as module

    sessions, _, oid, _ = fiscal_db

    class Provider(TestAcknowledgedProvider):
        async def submit_to_authority(self, *args):
            return bad

    monkeypatch.setitem(module.PROVIDERS, CountryTaxRegime.COLOMBIA, Provider)
    invoice = await create(sessions, oid, preview=False)
    assert invoice.status is InvoiceStatus.RECHAZADA
    assert (
        invoice.unique_identifier is None
        and invoice.error_message == "No se obtuvo aceptación fiscal verificable"
    )
    assert "secret" not in invoice.error_message


@pytest.mark.asyncio
async def test_provider_failure_has_durable_reservation_but_no_sensitive_error(
    fiscal_db, monkeypatch, caplog
):
    from app.services import invoicing_engine as module

    sessions, _, oid, _ = fiscal_db

    class Provider(TestAcknowledgedProvider):
        async def submit_to_authority(self, *args):
            async with sessions() as inspect:
                assert (
                    await inspect.scalar(
                        select(func.count()).select_from(ElectronicInvoice)
                    )
                    == 1
                )
            raise RuntimeError("private-provider-api-key")

    monkeypatch.setitem(module.PROVIDERS, CountryTaxRegime.COLOMBIA, Provider)
    invoice = await create(sessions, oid, preview=False)
    assert (
        invoice.status is InvoiceStatus.RECHAZADA
        and "private-provider-api-key" not in caplog.text
    )
    assert "private-provider-api-key" not in invoice.error_message


@pytest.fixture
async def fiscal_http(fiscal_db):
    sessions, uid, oid, ids = fiscal_db
    app = FastAPI()
    app.include_router(fiscal.router, prefix="/api/v1")

    async def database():
        async with sessions() as db:
            try:
                yield db
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = database
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer " + create_access_token(uid)},
    ) as client:
        yield client, oid, sessions, ids


def body(oid, **options):
    value = {
        "order_id": str(oid),
        "customer_name": "Test customer",
        "items": [{"name": "Delivery", "unit_price_cents": 116001, "quantity": 1}],
        "country": "MX",
        "preview": True,
    }
    value.update(options)
    return value


@pytest.mark.asyncio
async def test_http_preview_and_status_are_explicit_local_evidence(fiscal_http):
    client, oid, _, _ = fiscal_http
    response = await client.post("/api/v1/fiscal/invoices", json=body(oid))
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "PENDIENTE" and data["execution_mode"] == "sandbox"
    assert data["is_simulation"] and not data["is_officially_accepted"]
    status = await client.get(f"/api/v1/fiscal/invoices/{data['id']}/status")
    assert status.json()["status_source"] == "local_snapshot"
    assert status.json()["unique_identifier"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("country,status", [("ZZ", 400), ("CL", 422), ("PE", 422)])
async def test_invalid_or_unsupported_country_does_not_allocate(
    fiscal_http, country, status
):
    client, oid, sessions, _ = fiscal_http
    response = await client.post(
        "/api/v1/fiscal/invoices", json=body(oid, country=country)
    )
    assert response.status_code == status, response.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ElectronicInvoice)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "option,value,status",
    [
        ("ENABLE_ELECTRONIC_INVOICING", False, 423),
        ("FISCAL_SANDBOX_ENABLED", False, 422),
        ("APP_ENV", "production", 422),
        ("ENVIRONMENT", "production", 422),
    ],
)
async def test_http_guards_before_reserving(
    fiscal_http, monkeypatch, option, value, status
):
    client, oid, sessions, _ = fiscal_http
    monkeypatch.setattr(settings, option, value)
    response = await client.post("/api/v1/fiscal/invoices", json=body(oid))
    assert response.status_code == status, response.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ElectronicInvoice)) == 0


@pytest.mark.asyncio
async def test_real_mode_without_accredited_transport_is_disabled(fiscal_http):
    client, oid, sessions, _ = fiscal_http
    response = await client.post(
        "/api/v1/fiscal/invoices", json=body(oid, preview=False, country="CO")
    )
    assert response.status_code == 422 and "no homologada" in response.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ElectronicInvoice)) == 0


@pytest.mark.asyncio
async def test_cancellation_does_not_change_local_status_without_authority(fiscal_http):
    client, oid, sessions, _ = fiscal_http
    async with sessions() as db:
        inv = await insert_invoice(db, oid, execution_mode="real")
        await db.commit()
        iid = inv.id
    result = await client.post(
        f"/api/v1/fiscal/invoices/{iid}/cancel", json={"reason": "Valid reason"}
    )
    assert result.status_code == 422, result.text
    async with sessions() as db:
        assert (await db.get(ElectronicInvoice, iid)).status is InvoiceStatus.ACEPTADA


@pytest.mark.asyncio
async def test_legacy_simulation_cannot_issue_official_credit_note(fiscal_http):
    client, oid, sessions, _ = fiscal_http
    async with sessions() as db:
        inv = await insert_invoice(db, oid, pdf_url="stub://historical.pdf")
        await db.commit()
        iid = inv.id
    status = (await client.get(f"/api/v1/fiscal/invoices/{iid}/status")).json()
    assert (
        status["status"] == "ACEPTADA"
        and status["is_simulation"]
        and not status["is_officially_accepted"]
    )
    result = await client.post(
        f"/api/v1/fiscal/invoices/{iid}/credit-note",
        json={"reason": "Valid reason", "amount_cents": 100},
    )
    assert result.status_code == 400


@pytest.mark.asyncio
async def test_daily_limit_is_per_resolution_instead_of_global(fiscal_db, monkeypatch):
    sessions, _, oid, _ = fiscal_db
    monkeypatch.setattr(settings, "INVOICE_DAILY_LIMIT", 1)
    co = await create(sessions, oid, country=CountryTaxRegime.COLOMBIA)
    mx = await create(sessions, oid, country=CountryTaxRegime.MEXICO)
    assert co.resolution_id != mx.resolution_id
    with pytest.raises(InvoiceSubmissionError):
        await create(sessions, oid, country=CountryTaxRegime.COLOMBIA)


@pytest.mark.asyncio
async def test_legacy_records_count_conservatively_against_matching_range(
    fiscal_db, monkeypatch
):
    sessions, _, oid, _ = fiscal_db
    monkeypatch.setattr(settings, "INVOICE_DAILY_LIMIT", 1)
    async with sessions() as db:
        await insert_invoice(db, oid)
        await db.commit()
    with pytest.raises(InvoiceSubmissionError):
        await create(sessions, oid, country=CountryTaxRegime.COLOMBIA)


@pytest.mark.asyncio
async def test_existing_sandbox_resolution_is_required_to_avoid_using_real_ranges(
    fiscal_db,
):
    sessions, _, oid, _ = fiscal_db
    async with sessions() as db:
        await db.execute(
            update(InvoiceResolution)
            .where(InvoiceResolution.is_sandbox.is_(True))
            .values(is_active=False)
        )
        await db.commit()
    with pytest.raises(InvoiceSubmissionError):
        await create(sessions, oid)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ElectronicInvoice)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.AUDITOR, UserRole.OPERADOR, UserRole.REPARTIDOR, UserRole.CLIENTE]
)
async def test_non_admin_roles_cannot_create_preview(fiscal_http, fiscal_db, role):
    client, oid, sessions, _ = fiscal_http
    _, uid, _, _ = fiscal_db
    async with sessions() as db:
        user = await db.get(User, uid)
        user.role = role
        await db.commit()
    result = await client.post("/api/v1/fiscal/invoices", json=body(oid))
    assert result.status_code == 403, result.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item",
    [
        {"unit_price_cents": True},
        {"unit_price_cents": 1.5},
        {"unit_price_cents": -1},
        {"unit_price_cents": 1, "quantity": True},
        {"unit_price_cents": 1, "quantity": 0},
    ],
)
async def test_http_does_not_coerce_invalid_money_or_quantity(fiscal_http, item):
    client, oid, _, _ = fiscal_http
    result = await client.post(
        "/api/v1/fiscal/invoices", json=body(oid, items=[{"name": "Delivery", **item}])
    )
    assert result.status_code == 422, result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", ["0.1900", "0.0001", "1.0000"])
async def test_decimal_rate_updates_roundtrip_without_float_artifacts(
    fiscal_http, rate
):
    client, _, sessions, _ = fiscal_http
    async with sessions() as db:
        row = FiscalConfiguration(
            country_code=CountryTaxRegime.COLOMBIA,
            tax_code="VAT",
            tax_name="VAT",
            rate=Decimal("0.19"),
        )
        db.add(row)
        await db.commit()
        rid = row.id
    result = await client.patch(f"/api/v1/fiscal/config/{rid}", json={"rate": rate})
    assert result.status_code == 200, result.text
    async with sessions() as db:
        assert (await db.get(FiscalConfiguration, rid)).rate == Decimal(rate)


@pytest.mark.asyncio
async def test_missing_order_returns_404_without_allocating(fiscal_http):
    client, _, sessions, ids = fiscal_http
    result = await client.post("/api/v1/fiscal/invoices", json=body(uuid4()))
    assert result.status_code == 404, result.text
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ElectronicInvoice)) == 0
        assert (
            await db.scalar(
                select(InvoiceResolution.current_counter).where(
                    InvoiceResolution.id == ids[1]
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_bad_configured_key_rejects_without_calling_provider(
    fiscal_db, monkeypatch, tmp_path
):
    from app.services import invoicing_engine as module

    sessions, _, oid, ids = fiscal_db
    calls = []

    class Provider(TestAcknowledgedProvider):
        async def submit_to_authority(self, *args):
            calls.append(True)
            return await super().submit_to_authority(*args)

    monkeypatch.setitem(module.PROVIDERS, CountryTaxRegime.COLOMBIA, Provider)
    async with sessions() as db:
        resolution = await db.get(InvoiceResolution, ids[2])
        resolution.private_key_path = str(tmp_path / "sensitive-private-key.pem")
        await db.commit()
    invoice = await create(sessions, oid, preview=False)
    assert invoice.status is InvoiceStatus.RECHAZADA and not calls
    assert "sensitive-private-key" not in invoice.error_message
