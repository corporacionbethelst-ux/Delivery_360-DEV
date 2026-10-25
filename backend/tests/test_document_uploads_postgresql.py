"""File/SQL lifecycle and shared parent locks on a private PostgreSQL schema."""

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from tests.test_wallet_postgresql import pg_wallets  # noqa: F401
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.services.document_uploads import (
    DocumentUploadBatch,
    ValidatedDocument,
    replace_document,
    lock_document,
)
from app.core.document_files import resolve_document_file

PDF = b"%PDF-1.4 test document"


@pytest.fixture
async def pg_documents(pg_wallets, tmp_path, monkeypatch):
    sessions, _, riders = pg_wallets
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "uploads/documents"
    folder = root / str(riders[0])
    folder.mkdir(parents=True)
    (folder / "old.pdf").write_bytes(PDF)
    async with sessions() as db:
        connection = await db.connection()
        await connection.run_sync(RiderDocument.__table__.create)
        doc = RiderDocument(
            rider_id=riders[0],
            type=DocumentType.LICENCIA,
            status=DocumentStatus.RECHAZADO,
            file_url=f"/uploads/documents/{riders[0]}/old.pdf",
        )
        db.add(doc)
        await db.commit()
        doc_id = doc.id
    yield sessions, riders, doc_id, root


async def submit(sessions, rider_id):
    async with sessions() as db:
        return await replace_document(
            db,
            rider_id,
            DocumentType.LICENCIA,
            ValidatedDocument(PDF, ".pdf"),
            allow_pending=False,
        )


@pytest.mark.asyncio
async def test_concurrent_owner_uploads_create_only_one_pending_replacement(
    pg_documents,
):
    sessions, riders, doc_id, root = pg_documents
    results = await asyncio.gather(
        submit(sessions, riders[0]), submit(sessions, riders[0]), return_exceptions=True
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(failures) == 1 and failures[0].status_code == 400
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(RiderDocument)) == 1
        assert (
            await db.scalar(
                select(RiderDocument.status).where(RiderDocument.id == doc_id)
            )
            == DocumentStatus.PENDIENTE
        )
    assert len(list(root.rglob("*.pdf"))) == 2  # original retained + one new file


@pytest.mark.asyncio
async def test_different_riders_can_submit_documents(pg_documents):
    sessions, riders, _, root = pg_documents
    results = await asyncio.gather(*(submit(sessions, rider_id) for rider_id in riders))
    assert len({result["id"] for result in results}) == 2
    assert len(list(root.rglob("*.pdf"))) == 3


@pytest.mark.asyncio
async def test_real_constraint_failure_before_commit_removes_new_file(pg_documents):
    sessions, riders, doc_id, root = pg_documents
    async with sessions() as db:
        # Fail a real NOT NULL constraint during final flush after writing the file.
        db.add(RiderDocument(type=DocumentType.SEGURO, status=DocumentStatus.PENDIENTE))
        with pytest.raises(HTTPException) as error:
            await replace_document(
                db,
                riders[0],
                DocumentType.LICENCIA,
                ValidatedDocument(PDF, ".pdf"),
                allow_pending=False,
            )
        assert error.value.status_code == 503
    async with sessions() as db:
        assert (
            await db.scalar(
                select(RiderDocument.status).where(RiderDocument.id == doc_id)
            )
            == DocumentStatus.RECHAZADO
        )
        assert await db.scalar(select(func.count()).select_from(RiderDocument)) == 1
    assert len(list(root.rglob("*.pdf"))) == 1


@pytest.mark.asyncio
async def test_lost_commit_ack_keeps_the_committed_file(pg_documents):
    sessions, riders, doc_id, root = pg_documents
    async with sessions() as db:
        original = db.commit

        async def lost_ack():
            await original()
            raise OSError("commit acknowledgement unavailable")

        with patch.object(db, "commit", lost_ack):
            with pytest.raises(HTTPException) as error:
                await replace_document(
                    db,
                    riders[0],
                    DocumentType.LICENCIA,
                    ValidatedDocument(PDF, ".pdf"),
                    allow_pending=False,
                )
        assert error.value.status_code == 503
    async with sessions() as db:
        doc = await db.get(RiderDocument, doc_id)
        assert doc.status == DocumentStatus.PENDIENTE
        assert resolve_document_file(riders[0], doc.file_url).read_bytes() == PDF
    assert len(list(root.rglob("*.pdf"))) == 2


@pytest.mark.asyncio
async def test_upload_waits_for_review_and_cannot_overwrite_approved_document(
    pg_documents,
):
    sessions, riders, doc_id, root = pg_documents
    async with sessions() as reviewer:
        doc = await lock_document(reviewer, doc_id)
        doc.status = DocumentStatus.APROBADO
        attempted = asyncio.create_task(submit(sessions, riders[0]))
        await asyncio.sleep(0.03)
        assert not attempted.done()
        await reviewer.commit()
    with pytest.raises(HTTPException) as error:
        await attempted
    assert error.value.status_code == 400
    assert len(list(root.rglob("*.pdf"))) == 1
