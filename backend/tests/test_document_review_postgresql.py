"""Real PostgreSQL races: stale versions, eligibility and administrative state."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from tests.test_document_uploads_postgresql import pg_documents  # noqa: F401
from app.api.v1 import riders as api
from app.core.document_files import document_revision
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.services.document_review import review_document, delete_reviewed_document
from app.services.document_uploads import (
    DocumentUploadBatch,
    ValidatedDocument,
    replace_document,
)


async def revision(sessions, doc_id):
    async with sessions() as db:
        return document_revision(await db.get(RiderDocument, doc_id))


async def decision(sessions, doc_id, token, target):
    async with sessions() as db:
        result = await review_document(db, doc_id, target, token, "Review reason")
        await db.commit()
        return result


async def replace(sessions, rider_id):
    async with sessions() as db:
        return await replace_document(
            db,
            rider_id,
            DocumentType.LICENCIA,
            ValidatedDocument(b"%PDF-1.4 new document", ".pdf"),
            allow_pending=True,
        )


@pytest.mark.asyncio
async def test_two_reviewers_using_same_version_cannot_overwrite_each_other(
    pg_documents,
):
    sessions, _, doc_id, _ = pg_documents
    token = await revision(sessions, doc_id)
    results = await asyncio.gather(
        *(
            decision(sessions, doc_id, token, target)
            for target in (DocumentStatus.APROBADO, DocumentStatus.RECHAZADO)
        ),
        return_exceptions=True,
    )
    successes = [result for result in results if isinstance(result, dict)]
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == len(failures) == 1 and failures[0].status_code == 409
    assert await revision(sessions, doc_id) == successes[0]["revision"]


@pytest.mark.asyncio
async def test_replacement_finishing_first_invalidates_waiting_review(
    pg_documents, monkeypatch
):
    sessions, riders, doc_id, root = pg_documents
    token = await revision(sessions, doc_id)
    stored = asyncio.Event()
    release = asyncio.Event()
    original = DocumentUploadBatch.store

    async def paused_store(batch, *args):
        stored.set()
        await release.wait()
        return await original(batch, *args)

    monkeypatch.setattr(DocumentUploadBatch, "store", paused_store)
    writing = asyncio.create_task(replace(sessions, riders[0]))
    await stored.wait()
    reviewing = asyncio.create_task(
        decision(sessions, doc_id, token, DocumentStatus.APROBADO)
    )
    await asyncio.sleep(0.03)
    assert not reviewing.done()
    release.set()
    saved = await writing
    with pytest.raises(HTTPException) as error:
        await reviewing
    assert error.value.status_code == 409
    async with sessions() as db:
        assert (
            await db.scalar(
                select(RiderDocument.status).where(RiderDocument.id == doc_id)
            )
            == DocumentStatus.PENDIENTE
        )
    assert saved["revision"] != token and len(list(root.rglob("*.pdf"))) == 2


@pytest.mark.asyncio
async def test_review_finishing_first_prevents_replacing_approved_file(pg_documents):
    sessions, riders, doc_id, root = pg_documents
    token = await revision(sessions, doc_id)
    async with sessions() as db:
        await review_document(db, doc_id, DocumentStatus.APROBADO, token)
        writing = asyncio.create_task(replace(sessions, riders[0]))
        await asyncio.sleep(0.03)
        assert not writing.done()
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await writing
    assert error.value.status_code == 400 and len(list(root.rglob("*.pdf"))) == 1


@pytest.mark.asyncio
async def test_stale_delete_cannot_remove_replacement(pg_documents):
    sessions, riders, doc_id, _ = pg_documents
    old = await revision(sessions, doc_id)
    saved = await replace(sessions, riders[0])
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await delete_reviewed_document(db, doc_id, old)
        assert error.value.status_code == 409
        await db.rollback()
    assert await revision(sessions, doc_id) == saved["revision"]


async def complete_set(
    sessions,
    rider_id,
    doc_id,
    root,
    *,
    status=RiderStatus.ACTIVO,
    license_approved=True,
):
    async with sessions() as db:
        for kind in DocumentType:
            if kind == DocumentType.LICENCIA:
                continue
            path = root / str(rider_id) / f"{kind.value.lower()}.pdf"
            path.write_bytes(b"%PDF-1.4 required file")
            db.add(
                RiderDocument(
                    rider_id=rider_id,
                    type=kind,
                    status=DocumentStatus.APROBADO,
                    file_url=f"/uploads/documents/{rider_id}/{path.name}",
                )
            )
        await db.execute(
            update(RiderDocument)
            .where(RiderDocument.id == doc_id)
            .values(
                status=(
                    DocumentStatus.APROBADO
                    if license_approved
                    else DocumentStatus.RECHAZADO
                ),
                updated_at=datetime.utcnow(),
            )
        )
        await db.execute(
            update(Rider)
            .where(Rider.id == rider_id)
            .values(status=status, is_online=True)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_delete_and_manual_activation_cannot_leave_rider_enabled_without_file(
    pg_documents,
):
    sessions, riders, doc_id, root = pg_documents
    await complete_set(sessions, riders[0], doc_id, root)
    token = await revision(sessions, doc_id)

    async def delete():
        async with sessions() as db:
            await delete_reviewed_document(db, doc_id, token)
            await db.commit()

    async def activate():
        async with sessions() as db:
            return await api.approve_rider(
                str(riders[0]), body=None, db=db, current_user=SimpleNamespace()
            )

    results = await asyncio.gather(delete(), activate(), return_exceptions=True)
    assert results[0] is None
    assert (
        isinstance(results[1], dict)
        or isinstance(results[1], HTTPException)
        and results[1].status_code == 400
    )
    async with sessions() as db:
        assert (
            await db.execute(
                select(Rider.status, Rider.is_online).where(Rider.id == riders[0])
            )
        ).one() == (RiderStatus.PENDIENTE, False)


@pytest.mark.asyncio
async def test_suspension_wins_against_automatic_document_activation(pg_documents):
    sessions, riders, doc_id, root = pg_documents
    await complete_set(
        sessions,
        riders[0],
        doc_id,
        root,
        status=RiderStatus.PENDIENTE,
        license_approved=False,
    )
    token = await revision(sessions, doc_id)

    async def suspend():
        async with sessions() as db:
            return await api.reject_rider(
                str(riders[0]),
                body=api.RejectRider(reason="Administrative suspension"),
                db=db,
                current_user=SimpleNamespace(),
            )

    results = await asyncio.gather(
        decision(sessions, doc_id, token, DocumentStatus.APROBADO),
        suspend(),
        return_exceptions=True,
    )
    assert all(isinstance(result, dict) for result in results), results
    async with sessions() as db:
        assert (
            await db.execute(
                select(Rider.status, Rider.is_online).where(Rider.id == riders[0])
            )
        ).one() == (RiderStatus.SUSPENDIDO, False)
