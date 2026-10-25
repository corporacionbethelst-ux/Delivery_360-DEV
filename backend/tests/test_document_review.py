"""Review snapshots, readable required documents, availability and no bypasses."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select, update

from tests.test_document_uploads import (
    submissions,
    documents,
    post_document,
)  # noqa: F401
from app.core.document_files import document_revision
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.rider import Rider, RiderStatus
from app.models.user import UserRole


@pytest.fixture
async def review_context(submissions):
    client, db, ctx = submissions
    ctx["current"][0].role = UserRole.GERENTE
    return client, db, ctx


async def metadata(client, ctx):
    response = await client.get(f"/api/v1/riders/{ctx['rider_id']}/documents")
    assert response.status_code == 200, response.text
    return next(row for row in response.json() if row["id"] == str(ctx["doc_id"]))


async def review(client, ctx, revision, target="APROBADO", reason=None):
    body = {"status": target, "expected_revision": revision}
    if reason is not None:
        body["rejection_reason"] = reason
    return await client.patch(
        f"/api/v1/riders/documents/{ctx['doc_id']}/status", json=body
    )


async def ready_set(db, ctx, *, rider_status=RiderStatus.PENDIENTE, online=False):
    for kind in DocumentType:
        if kind == DocumentType.LICENCIA:
            continue
        path = ctx["old_file"].parent / f"{kind.value.lower()}.pdf"
        path.write_bytes(b"%PDF-1.4 existing document")
        db.add(
            RiderDocument(
                rider_id=ctx["rider_id"],
                type=kind,
                status=DocumentStatus.APROBADO,
                file_url=f"/uploads/documents/{ctx['rider_id']}/{path.name}",
            )
        )
    await db.execute(
        update(Rider)
        .where(Rider.id == ctx["rider_id"])
        .values(status=rider_status, is_online=online)
    )
    await db.commit()


async def state(db, ctx):
    return (
        await db.execute(
            select(Rider.status, Rider.is_online).where(Rider.id == ctx["rider_id"])
        )
    ).one()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revision,code", [(None, 409), ("0" * 64, 409), ("invalid", 422)]
)
@pytest.mark.parametrize("target", ["APROBADO", "RECHAZADO"])
async def test_missing_or_wrong_review_snapshot_never_mutates_document(
    review_context, revision, code, target
):
    client, db, ctx = review_context
    before = await state(db, ctx)
    response = await review(client, ctx, revision, target, "Revisión")
    assert response.status_code == code
    assert (
        await db.scalar(
            select(RiderDocument.status).where(RiderDocument.id == ctx["doc_id"])
        )
        == DocumentStatus.RECHAZADO
    )
    assert await state(db, ctx) == before


@pytest.mark.asyncio
async def test_replacement_invalidates_review_delete_and_conditional_download(
    review_context,
):
    client, db, ctx = review_context
    old = await metadata(client, ctx)
    replaced = await post_document(client, ctx, admin=True)
    assert replaced.status_code == 200, replaced.text
    current = (await metadata(client, ctx))["revision"]
    assert current == replaced.json()["revision"] != old["revision"]
    assert (await review(client, ctx, old["revision"])).status_code == 409
    url = f"/api/v1/riders/documents/{ctx['doc_id']}"
    assert (
        await client.delete(url, headers={"If-Match": f'"{old["revision"]}"'})
    ).status_code == 409
    response = await client.get(
        url + "/download", headers={"If-Match": f'"{old["revision"]}"'}
    )
    assert response.status_code == 409 and b"%PDF" not in response.content
    current_download = await client.get(
        url + "/download", headers={"If-Match": f'"{current}"'}
    )
    assert current_download.status_code == 200
    assert current_download.headers["etag"] == f'"{current}"'
    assert (
        await db.scalar(
            select(RiderDocument.id).where(RiderDocument.id == ctx["doc_id"])
        )
        == ctx["doc_id"]
    )


@pytest.mark.asyncio
async def test_review_changes_revision_and_rejects_another_stale_review(review_context):
    client, _, ctx = review_context
    old = (await metadata(client, ctx))["revision"]
    first = await review(client, ctx, old)
    assert first.status_code == 200, first.text
    new = first.json()["revision"]
    assert new != old and new == (await metadata(client, ctx))["revision"]
    assert (
        await review(client, ctx, old, "RECHAZADO", "old decision")
    ).status_code == 409
    rejected = await review(client, ctx, new, "RECHAZADO", "   Archivo ilegible   ")
    assert rejected.status_code == 200
    assert (await metadata(client, ctx))["rejection_reason"] == "Archivo ilegible"


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["none", "missing", "empty", "remote", "symlink"])
async def test_approval_requires_available_file_but_rejection_remains_possible(
    review_context, problem, tmp_path
):
    client, db, ctx = review_context
    reference = ctx["old_reference"]
    if problem == "none":
        reference = None
    elif problem == "missing":
        ctx["old_file"].unlink()
    elif problem == "empty":
        ctx["old_file"].write_bytes(b"")
    elif problem == "remote":
        reference = "https://example.test/document.pdf"
    else:
        outside = tmp_path / "outside.pdf"
        outside.write_bytes(b"secret")
        ctx["old_file"].unlink()
        ctx["old_file"].symlink_to(outside)
    await db.execute(
        update(RiderDocument)
        .where(RiderDocument.id == ctx["doc_id"])
        .values(file_url=reference, updated_at=datetime.utcnow())
    )
    await db.commit()
    revision = (await metadata(client, ctx))["revision"]
    assert (await review(client, ctx, revision)).status_code == 409
    assert (
        await review(client, ctx, revision, "RECHAZADO", "Archivo no disponible")
    ).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial,expected",
    [
        (RiderStatus.PENDIENTE, RiderStatus.ACTIVO),
        (RiderStatus.SUSPENDIDO, RiderStatus.SUSPENDIDO),
        (RiderStatus.INACTIVO, RiderStatus.INACTIVO),
        (RiderStatus.ACTIVO, RiderStatus.ACTIVO),
        (RiderStatus.OCUPADO, RiderStatus.OCUPADO),
        (None, None),
    ],
)
async def test_complete_approval_only_auto_activates_pending_accounts(
    review_context, initial, expected
):
    client, db, ctx = review_context
    await ready_set(db, ctx, rider_status=initial, online=True)
    revision = (await metadata(client, ctx))["revision"]
    response = await review(client, ctx, revision)
    assert response.status_code == 200, response.text
    status, online = await state(db, ctx)
    assert status == expected
    assert online is (initial in (RiderStatus.ACTIVO, RiderStatus.OCUPADO))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial,expected",
    [
        (RiderStatus.ACTIVO, RiderStatus.PENDIENTE),
        (RiderStatus.OCUPADO, RiderStatus.PENDIENTE),
        (RiderStatus.SUSPENDIDO, RiderStatus.SUSPENDIDO),
        (RiderStatus.INACTIVO, RiderStatus.INACTIVO),
    ],
)
async def test_delete_restricts_operational_state_and_preserves_suspensions(
    review_context, initial, expected
):
    client, db, ctx = review_context
    await ready_set(db, ctx, rider_status=initial, online=True)
    await db.execute(
        update(RiderDocument)
        .where(RiderDocument.id == ctx["doc_id"])
        .values(status=DocumentStatus.APROBADO, updated_at=datetime.utcnow())
    )
    await db.commit()
    revision = (await metadata(client, ctx))["revision"]
    response = await client.delete(
        f"/api/v1/riders/documents/{ctx['doc_id']}",
        headers={"If-Match": f'"{revision}"'},
    )
    assert response.status_code == 200, response.text
    assert await state(db, ctx) == (expected, False)
    assert ctx["old_file"].exists()


@pytest.mark.asyncio
async def test_delete_without_revision_has_no_side_effects(review_context):
    client, db, ctx = review_context
    before = await state(db, ctx)
    response = await client.delete(f"/api/v1/riders/documents/{ctx['doc_id']}")
    assert response.status_code == 409
    assert await state(db, ctx) == before
    assert (
        await db.scalar(
            select(RiderDocument.id).where(RiderDocument.id == ctx["doc_id"])
        )
        is not None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["approve", "status", "online", "heartbeat"])
async def test_activation_routes_cannot_bypass_missing_required_file(
    review_context, path
):
    client, db, ctx = review_context
    await ready_set(db, ctx, rider_status=RiderStatus.ACTIVO, online=True)
    await db.execute(
        update(RiderDocument)
        .where(RiderDocument.id == ctx["doc_id"])
        .values(
            status=DocumentStatus.APROBADO, file_url=None, updated_at=datetime.utcnow()
        )
    )
    await db.commit()
    url = f"/api/v1/riders/{ctx['rider_id']}/{path}"
    kwargs = (
        {"json": {"status": "ACTIVO"}}
        if path == "status"
        else (
            {"params": {"online": True}}
            if path == "online"
            else {"json": {"lat": 10, "lng": -66}} if path == "heartbeat" else {}
        )
    )
    response = await client.patch(url, **kwargs)
    assert response.status_code in (400, 403, 409), response.text
    assert await state(db, ctx) == (RiderStatus.PENDIENTE, False)


@pytest.mark.asyncio
async def test_duplicates_cannot_be_approved_or_used_for_activation(review_context):
    client, db, ctx = review_context
    await ready_set(db, ctx)
    db.add(
        RiderDocument(
            rider_id=ctx["rider_id"],
            type=DocumentType.LICENCIA,
            status=DocumentStatus.APROBADO,
            file_url=ctx["old_reference"],
        )
    )
    await db.commit()
    assert (
        await review(client, ctx, (await metadata(client, ctx))["revision"])
    ).status_code == 409
    assert (
        await client.patch(f"/api/v1/riders/{ctx['rider_id']}/approve")
    ).status_code == 400


@pytest.mark.asyncio
async def test_manual_activation_is_explicit_and_still_checks_complete_documents(
    review_context,
):
    client, db, ctx = review_context
    await ready_set(db, ctx, rider_status=RiderStatus.SUSPENDIDO, online=False)
    await db.execute(
        update(RiderDocument)
        .where(RiderDocument.id == ctx["doc_id"])
        .values(status=DocumentStatus.APROBADO, updated_at=datetime.utcnow())
    )
    await db.commit()
    response = await client.patch(f"/api/v1/riders/{ctx['rider_id']}/approve")
    assert response.status_code == 200, response.text
    assert await state(db, ctx) == (RiderStatus.ACTIVO, False)


@pytest.mark.asyncio
async def test_metadata_refreshes_preloaded_review_fields_in_same_session(
    review_context,
):
    client, db, ctx = review_context
    row = await db.get(RiderDocument, ctx["doc_id"])
    old = document_revision(row)
    await db.execute(
        update(RiderDocument)
        .where(RiderDocument.id == row.id)
        .values(rejection_reason="Changed in SQL", updated_at=row.updated_at)
    )
    await db.commit()
    response = await metadata(client, ctx)
    await db.refresh(row)
    assert response["revision"] == document_revision(row) != old


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.OPERADOR, UserRole.REPARTIDOR, UserRole.CLIENTE, UserRole.AUDITOR]
)
async def test_revision_never_grants_mutation_permission(review_context, role):
    client, db, ctx = review_context
    revision = (await metadata(client, ctx))["revision"]
    ctx["current"][0].role = role
    assert (await review(client, ctx, revision)).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/riders/documents/{ctx['doc_id']}", headers={"If-Match": revision}
        )
    ).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["DELETE", "GET"])
async def test_cors_allows_version_precondition_header(method):
    from app.main import app
    from app.core.config import settings
    from httpx import ASGITransport, AsyncClient

    if not settings.cors_origins:
        pytest.skip("No configured CORS origin")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        response = await client.options(
            "/api/v1/riders/documents/id/download",
            headers={
                "origin": settings.cors_origins[0],
                "access-control-request-method": method,
                "access-control-request-headers": "authorization,if-match",
            },
        )
    assert (
        response.status_code == 200
        and "if-match" in response.headers["access-control-allow-headers"].lower()
    )
