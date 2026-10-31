"""Real HTTP/SQL rollback, credential epochs and guarded rider lifecycle."""

from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update, func
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_delivery_financial_postgresql import payment_db  # noqa: F401
from tests.test_order_cancellation_postgresql import cancel_db  # noqa: F401
from tests.test_sla_monitor_postgresql import sla_db  # noqa: F401
from app.core.security import create_access_token, decode_token
from app.core.exceptions import AppException
from app.models.user import User, UserRole
from app.models.rider import Rider, RiderStatus
from app.models.route import Route, RouteStatus
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.order import Order, OrderStatus
from app.models.delivery import Delivery, DeliveryStatus
from app.models.notification import Notification
from app.models.audit_log import AuditLog
from app.schemas.rider import RiderCreate, RiderApprovalRequest
from app.schemas.user import UserCreate, UserUpdate
from app.schemas.auth import LoginRequest
from app.services.notification_hooks import record_legacy_notice
from app.services.notification_service import NotificationService
from app.services.user_service import UserService
from app.services.rider_service import RiderService
from app.services.auth_service import AuthService
from app.crud.rider import rider as rider_crud


@pytest.fixture
async def runtime_db(sla_db, tmp_path, monkeypatch):
    client, sessions, ids = sla_db
    monkeypatch.chdir(tmp_path)
    async with sessions() as db:
        conn = await db.connection()
        await conn.run_sync(RiderDocument.__table__.create)
        for uid in (ids["staff"], ids["owner"]):
            await db.execute(
                update(User)
                .where(User.id == uid)
                .values(email=f"runtime-{uid}@example.com")
            )
        for kind in DocumentType:
            folder = tmp_path / "uploads/documents" / str(ids["rider"])
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (kind.value + ".pdf")
            path.write_bytes(b"%PDF verified test evidence")
            db.add(
                RiderDocument(
                    rider_id=ids["rider"],
                    type=kind,
                    status=DocumentStatus.APROBADO,
                    file_url=f"/uploads/documents/{ids['rider']}/{path.name}",
                )
            )
        await db.execute(
            update(Order).values(status=OrderStatus.PENDIENTE, assigned_rider_id=None)
        )
        await db.execute(update(Delivery).values(status=DeliveryStatus.INICIADA))
        await db.execute(update(Route).values(status=RouteStatus.PLANIFICADA))
        await db.commit()
    return client, sessions, ids


def assign(client, ids):
    return client.patch(
        f"/api/v1/orders/{ids['order']}/assign",
        json={"rider_id": str(ids["rider"])},
        headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["inactive_recipient", "flush", "commit"])
async def test_notice_failure_cannot_expire_committed_assignment_or_hide_its_audit(
    runtime_db, monkeypatch, failure
):
    client, sessions, ids = runtime_db
    if failure == "inactive_recipient":
        original_create = NotificationService.create_notification

        async def deactivated_after_assignment(service, *args, **kwargs):
            # Assignment now rejects pre-existing inactive owners. This fault
            # occurs after the assignment commit, inside the separate notice unit.
            await service.db.execute(
                update(User).where(User.id == ids["owner"]).values(is_active=False)
            )
            await service.db.commit()
            return await original_create(service, *args, **kwargs)

        monkeypatch.setattr(
            NotificationService, "create_notification", deactivated_after_assignment
        )
    else:
        original_create = NotificationService.create_notification

        async def marked(service, *args, **kwargs):
            service.db.info["notice_fault"] = True
            return await original_create(service, *args, **kwargs)

        monkeypatch.setattr(NotificationService, "create_notification", marked)
        original = getattr(AsyncSession, failure)

        async def broken(db, *args, **kwargs):
            if db.info.get("notice_fault"):
                raise RuntimeError("injected notice failure")
            return await original(db, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, failure, broken)
    response = assign(client, ids)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ASIGNADO"
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        assert (
            order.status == OrderStatus.ASIGNADO
            and order.assigned_rider_id == ids["rider"]
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.resource_type == "ORDER",
                    AuditLog.resource_id == str(ids["order"]),
                )
            )
            == 1
        )
        assert await db.scalar(select(func.count()).select_from(Notification)) == 0


@pytest.mark.asyncio
async def test_assignment_and_audit_roll_back_together_before_postcommit_notice(
    runtime_db, monkeypatch
):
    client, sessions, ids = runtime_db
    original = AsyncSession.commit

    async def broken(db):
        if db.info.get("workflow_request") and any(
            isinstance(row, AuditLog) for row in db.new
        ):
            raise RuntimeError("injected assignment audit failure")
        return await original(db)

    monkeypatch.setattr(AsyncSession, "commit", broken)
    response = assign(client, ids)
    assert response.status_code == 500
    async with sessions() as db:
        order = await db.get(Order, ids["order"])
        assert order.status == OrderStatus.PENDIENTE and order.assigned_rider_id is None
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert await db.scalar(select(func.count()).select_from(Notification)) == 0


@pytest.mark.asyncio
async def test_legacy_notice_cannot_commit_or_rollback_an_active_callers_unit(
    runtime_db,
):
    _, sessions, ids = runtime_db
    async with sessions() as db:
        user = await db.get(User, ids["staff"])
        before = user.first_name
        user.first_name = "Uncommitted change"
        assert (
            await record_legacy_notice(
                db,
                user_id=ids["owner"],
                notification_type="SISTEMA",
                title="Aviso",
                message="Mensaje",
            )
            is False
        )
        assert user.first_name == "Uncommitted change" and db.in_transaction()
        async with sessions() as observer:
            assert (await observer.get(User, ids["staff"])).first_name == before
        await db.rollback()


@pytest.mark.asyncio
async def test_legacy_notice_refuses_connection_bound_sessions_without_touching_owner(
    runtime_db,
):
    _, sessions, ids = runtime_db
    engine = sessions.kw["bind"]
    async with engine.begin() as connection:
        async with AsyncSession(bind=connection, expire_on_commit=False) as db:
            assert (
                await record_legacy_notice(
                    db,
                    user_id=ids["owner"],
                    notification_type="SISTEMA",
                    title="Aviso",
                    message="Mensaje",
                )
                is False
            )
            assert connection.in_transaction()


@pytest.mark.asyncio
async def test_user_adapter_persists_physical_names_and_keeps_inactive_email_claim(
    runtime_db,
):
    _, sessions, _ = runtime_db
    payload = UserCreate(
        email="Adapter@example.com",
        first_name="Ana",
        last_name="Pérez",
        password="Valid-test-password",
        role="OPERADOR",
        is_active=False,
    )
    async with sessions() as db:
        user = await UserService().create_user(db, payload, 1)
        uid = user.id
        assert (
            user.first_name == "Ana"
            and user.last_name == "Pérez"
            and not user.is_active
        )
        assert "full_name" not in user.__dict__ and "is_deleted" not in user.__dict__
    async with sessions() as db:
        found = await UserService().get_user_by_email(db, " ADAPTER@EXAMPLE.COM ")
        assert found.id == uid
        with pytest.raises(HTTPException) as error:
            await UserService().create_user(db, payload, 1)
        assert error.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [{"password": "New-password-valid"}, {"role": "CLIENTE"}, {"is_active": False}],
)
async def test_user_security_edits_revoke_tokens_in_the_same_transaction(
    runtime_db, change
):
    _, sessions, ids = runtime_db
    old = create_access_token(ids["owner"])
    async with sessions() as db:
        user = await UserService().update_user(
            db, ids["owner"], UserUpdate(**change), 1
        )
        assert user.token_version == 1
        assert decode_token(old)["ver"] != user.token_version
        assert "password" not in user.__dict__


@pytest.mark.asyncio
async def test_reversible_deactivation_does_not_resurrect_old_epochs(runtime_db):
    _, sessions, ids = runtime_db
    async with sessions() as db:
        await UserService().delete_user(db, ids["owner"], 1)
        user = await db.get(User, ids["owner"])
        assert user.is_active is False and user.token_version == 1
        user = await UserService().activate_user(db, ids["owner"], 1)
        assert user.is_active is True and user.token_version == 2
        assert await db.get(Rider, ids["rider"]) is not None


@pytest.mark.asyncio
async def test_role_change_rolls_back_when_credential_revocation_fails(
    runtime_db, monkeypatch
):
    _, sessions, ids = runtime_db

    async def broken(*args, **kwargs):
        raise RuntimeError("revocation failed")

    monkeypatch.setattr("app.services.user_service.revoke_user_tokens", broken)
    async with sessions() as db:
        with pytest.raises(RuntimeError):
            await UserService().update_user(
                db, ids["owner"], UserUpdate(role="CLIENTE"), 1
            )
    async with sessions() as db:
        user = await db.get(User, ids["owner"])
        assert user.role == UserRole.REPARTIDOR and user.token_version == 0


@pytest.mark.asyncio
async def test_auth_facade_mints_canonical_epochs_and_rejects_revoked_refresh(
    runtime_db,
):
    _, sessions, ids = runtime_db
    facade = AuthService()
    async with sessions() as db:
        await db.execute(
            update(User)
            .where(User.id == ids["staff"])
            .values(hashed_password=facade.get_password_hash("Valid-test-password"))
        )
        await db.commit()
        email = (await db.get(User, ids["staff"])).email
        access, refresh, user = await facade.login(
            db, LoginRequest(email=email, password="Valid-test-password")
        )
        assert (
            decode_token(access)["type"] == "access"
            and decode_token(refresh)["type"] == "refresh"
        )
        assert (
            decode_token(access)["ver"]
            == decode_token(refresh)["ver"]
            == user.token_version
        )
        assert facade.decode_token(access).user_id == str(ids["staff"])
        next_access, _ = await facade.refresh_tokens(db, refresh)
        assert decode_token(next_access)["ver"] == 0
        await UserService().deactivate_user(db, ids["staff"], 1)
        with pytest.raises(HTTPException) as error:
            await facade.refresh_tokens(db, refresh)
        assert error.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,active,expected",
    [
        (None, True, 401),
        (UserRole.SUPERADMIN, False, 401),
        (UserRole.REPARTIDOR, True, 403),
    ],
)
async def test_auth_facade_uses_live_account_and_rider_eligibility(
    runtime_db, role, active, expected
):
    _, sessions, ids = runtime_db
    facade = AuthService()
    async with sessions() as db:
        uid = ids["owner"]
        await db.execute(
            update(User)
            .where(User.id == uid)
            .values(
                role=role,
                is_active=active,
                hashed_password=facade.get_password_hash("Valid-test-password"),
            )
        )
        await db.execute(update(Rider).values(status=RiderStatus.PENDIENTE))
        await db.commit()
        email = (await db.get(User, uid)).email
        with pytest.raises(HTTPException) as error:
            await facade.login(
                db, LoginRequest(email=email, password="Valid-test-password")
            )
        assert error.value.status_code == expected


@pytest.mark.asyncio
async def test_registration_is_pending_and_flush_is_caller_owned(runtime_db):
    _, sessions, _ = runtime_db
    async with sessions() as db:
        user = User(
            email="new-rider@example.test",
            first_name="New",
            last_name="Rider",
            hashed_password="unused",
            role=UserRole.REPARTIDOR,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        result = await RiderService(db).create_rider(
            RiderCreate(user_id=user.id, cpf="123"), user.id
        )
        rid = result.id
        assert (
            result.status == RiderStatus.PENDIENTE
            and result.approved_at is None
            and result.is_online is False
        )
        assert result.cpf == "123" and "document_number" not in result.__dict__
        async with sessions() as observer:
            assert await observer.get(Rider, rid) is None
        await db.rollback()
    async with sessions() as db:
        assert await db.get(Rider, rid) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_approval_and_rejection_use_real_states_and_atomic_audit(
    runtime_db, approved
):
    _, sessions, ids = runtime_db
    async with sessions() as db:
        await db.execute(
            update(Rider).values(status=RiderStatus.PENDIENTE, approved_at=None)
        )
        await db.commit()
        result = await RiderService(db).approve_rider(
            ids["rider"],
            RiderApprovalRequest(
                approved=approved,
                rejection_reason="Documentación requiere correcciones",
            ),
            ids["staff"],
        )
        assert result.status == (
            RiderStatus.ACTIVO if approved else RiderStatus.SUSPENDIDO
        )
        assert result.is_online is False
        assert (result.approved_at is not None) == approved
        receipt = await db.scalar(select(AuditLog))
        assert (
            receipt.user_id == ids["staff"]
            and receipt.new_values["status"] == result.status.value
        )
        assert (
            "approval_status" not in result.__dict__
            and "approved_by" not in result.__dict__
        )
        if approved:
            assert len(await rider_crud.get_multi(db, is_approved=True)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["actor", "documents", "missing_file"])
async def test_approval_cannot_skip_role_or_document_evidence(runtime_db, denial):
    _, sessions, ids = runtime_db
    async with sessions() as db:
        await db.execute(
            update(Rider).values(status=RiderStatus.PENDIENTE, approved_at=None)
        )
        if denial == "actor":
            await db.execute(
                update(User)
                .where(User.id == ids["staff"])
                .values(role=UserRole.OPERADOR)
            )
        elif denial == "documents":
            await db.execute(
                update(RiderDocument).values(status=DocumentStatus.RECHAZADO)
            )
        else:
            doc = await db.scalar(select(RiderDocument).limit(1))
            Path(doc.file_url.lstrip("/")).unlink()
        await db.commit()
        with pytest.raises((AppException, HTTPException)) as error:
            await RiderService(db).approve_rider(
                ids["rider"], RiderApprovalRequest(approved=True), ids["staff"]
            )
        assert error.value.status_code in (403, 409)
    async with sessions() as db:
        assert (await db.get(Rider, ids["rider"])).status == RiderStatus.PENDIENTE
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.asyncio
async def test_approval_rechecks_actor_after_waiting_for_the_rider(
    runtime_db, monkeypatch
):
    import app.services.rider_service as module

    _, sessions, ids = runtime_db
    async with sessions() as db:
        await db.execute(
            update(Rider).values(status=RiderStatus.PENDIENTE, approved_at=None)
        )
        await db.commit()
    entered, release = Future(), Future()
    original = module.lock_rider

    async def paused(db, rid):
        await original(db, rid)
        entered.set_result(None)
        await asyncio.wrap_future(release)

    monkeypatch.setattr(module, "lock_rider", paused)

    async def approve():
        async with sessions() as db:
            return await RiderService(db).approve_rider(
                ids["rider"], RiderApprovalRequest(), ids["staff"]
            )

    async with asyncio.timeout(15):
        pending = asyncio.create_task(approve())
        try:
            await asyncio.wait_for(asyncio.wrap_future(entered), 5)
            async with sessions() as db:
                await db.execute(
                    update(User)
                    .where(User.id == ids["staff"])
                    .values(role=UserRole.CLIENTE)
                )
                await db.commit()
        finally:
            release.set_result(None)
        with pytest.raises(AppException) as error:
            await pending
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_documents_adapter_reads_actual_rows_without_async_lazy_loading(
    runtime_db,
):
    _, sessions, ids = runtime_db
    async with sessions() as db:
        result = await rider_crud.get_documents(db, ids["rider"])
        assert result["rider_id"] == str(ids["rider"])
        assert {row["type"] for row in result["documents"]} == {
            kind.value for kind in DocumentType
        }
        assert all(row["status"] == "APROBADO" for row in result["documents"])


@pytest.mark.asyncio
async def test_auto_assignment_accepts_zero_coordinates_and_addresses_the_real_user(
    runtime_db,
):
    client, sessions, ids = runtime_db
    async with sessions() as db:
        await db.execute(
            update(Order).values(pickup_latitude=0.0, pickup_longitude=0.0)
        )
        await db.execute(
            update(Rider).values(is_online=True, last_lat=0.0, last_lng=0.0)
        )
        await db.execute(
            text("UPDATE riders SET last_location=ST_SetSRID(ST_MakePoint(0,0),4326)")
        )
        await db.commit()
    response = client.post(
        f"/api/v1/orders/{ids['order']}/assign-auto",
        headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
    )
    assert response.status_code == 200, response.text
    assert response.json()["assigned_rider"]["distance_km"] == 0
    async with sessions() as db:
        notice = await db.scalar(select(Notification))
        assert notice.user_id == ids["owner"] and notice.rider_id == ids["rider"]
        assert notice.channels == "in_app" and notice.is_sent is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "latitude,longitude", [(float("nan"), 0), (91, 0), (0, 181), (float("inf"), 0)]
)
async def test_auto_assignment_rejects_invalid_pickup_before_spatial_work(
    runtime_db, latitude, longitude
):
    client, sessions, ids = runtime_db
    async with sessions() as db:
        await db.execute(
            update(Order).values(pickup_latitude=latitude, pickup_longitude=longitude)
        )
        await db.commit()
    response = client.post(
        f"/api/v1/orders/{ids['order']}/assign-auto",
        headers={"Authorization": "Bearer " + create_access_token(ids["staff"])},
    )
    assert response.status_code == 400, response.text
    async with sessions() as db:
        assert (await db.get(Order, ids["order"])).status == OrderStatus.PENDIENTE
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0
