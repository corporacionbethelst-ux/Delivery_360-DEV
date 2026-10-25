"""Upload policy, owned file cleanup and commit ambiguity with real SQLite rows."""

import asyncio
import io
import stat
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, UploadFile, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers

from tests.test_private_documents import documents  # noqa: F401
from app.api.v1 import riders as api, auth, vehicles
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.document_files import resolve_document_file, document_revision
from app.middleware.document_upload_limit import DocumentUploadLimitMiddleware
from app.models.user import User, UserRole
from app.models.rider import Rider
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.services import document_uploads as service

PDF = b"%PDF-1.4 test document"


def upload(data=PDF, filename="document.pdf", mime="application/pdf"):
    return UploadFile(
        io.BytesIO(data), filename=filename, headers=Headers({"content-type": mime})
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename,mime,data,code",
    [
        ("a.svg", "image/svg+xml", b"<svg/>", 415),
        ("a.pdf", "text/html", PDF, 415),
        ("a.png", "image/png", PDF, 415),
        ("a.pdf", "application/pdf", b"<html>not PDF</html>", 415),
        ("a.jpg", "image/jpeg", b"MZ executable", 415),
        ("a.pdf", "application/pdf", b"", 422),
        ("no-extension", "application/pdf", PDF, 415),
    ],
)
async def test_rejects_unsupported_empty_or_mismatched_files(
    filename, mime, data, code
):
    with pytest.raises(HTTPException) as error:
        await service.validate_document(upload(data, filename, mime))
    assert error.value.status_code == code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename,mime,data,extension",
    [
        ("report.PDF", "application/pdf", PDF, ".pdf"),
        ("photo.png", "image/png", b"\x89PNG\r\n\x1a\ncontainer", ".png"),
        ("photo.jpeg", "image/jpeg", b"\xff\xd8\xffcontainer", ".jpg"),
        ("photo.jpg", "application/octet-stream", b"\xff\xd8\xffcontainer", ".jpg"),
    ],
)
async def test_accepts_allowed_magic_and_normalizes_generated_extension(
    filename, mime, data, extension
):
    document = await service.validate_document(upload(data, filename, mime))
    assert document.data == data and document.extension == extension


@pytest.mark.asyncio
async def test_exact_size_boundary_is_accepted_and_only_one_extra_byte_is_read(
    monkeypatch,
):
    monkeypatch.setattr(service, "MAX_DOCUMENT_BYTES", 16)
    assert (
        len((await service.validate_document(upload(b"%PDF-1.4" + b"x" * 8))).data)
        == 16
    )
    file = upload(b"%PDF-1.4" + b"x" * 100)
    with pytest.raises(HTTPException) as error:
        await service.validate_document(file)
    assert error.value.status_code == 413
    assert file.file.tell() == 17


@pytest.fixture
async def submissions(documents):
    _, db, doc, current, _, root, old_file = documents
    context = {
        "doc_id": doc.id,
        "rider_id": doc.rider_id,
        "old_reference": doc.file_url,
        "root": root,
        "old_file": old_file,
        "current": current,
    }
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.RECHAZADO,
            rejection_reason="Review",
            updated_at=datetime.utcnow(),
        )
    )
    await db.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(vehicles.router, prefix="/api/v1")
    app.add_middleware(DocumentUploadLimitMiddleware)

    async def database():
        try:
            yield db
        except Exception:
            await db.rollback()
            raise

    async def identity():
        return current[0]

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db, context


async def post_document(
    client,
    context,
    *,
    admin=False,
    data=PDF,
    filename="licencia.pdf",
    mime="application/pdf",
):
    path = (
        f"/api/v1/riders/{context['rider_id']}/documents/upload"
        if admin
        else "/api/v1/riders/me/documents/upload"
    )
    return await client.post(
        path, data={"type": "LICENCIA"}, files={"file": (filename, data, mime)}
    )


async def references(db, doc_id):
    return (
        await db.execute(
            select(RiderDocument.file_url, RiderDocument.status).where(
                RiderDocument.id == doc_id
            )
        )
    ).one()


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_valid_replacement_keeps_history_and_private_download(submissions, admin):
    client, db, context = submissions
    if admin:
        context["current"][0].role = UserRole.GERENTE
    response = await post_document(
        client, context, admin=admin, filename="../../client-name.pdf"
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["file_url"]
        == f"/api/v1/riders/documents/{context['doc_id']}/download"
    )
    reference, status = await references(db, context["doc_id"])
    assert status == DocumentStatus.PENDIENTE
    assert reference != context["old_reference"] and "client-name" not in reference
    path = resolve_document_file(context["rider_id"], reference)
    assert path.read_bytes() == PDF and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert context["old_file"].exists()
    download = await client.get(response.json()["file_url"])
    assert download.status_code == 200 and download.content == PDF


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,admin",
    [
        (DocumentStatus.APROBADO, False),
        (DocumentStatus.PENDIENTE, False),
        (DocumentStatus.APROBADO, True),
    ],
)
async def test_existing_review_rules_are_preserved_without_new_files(
    submissions, status, admin
):
    client, db, context = submissions
    await db.execute(
        update(RiderDocument).values(status=status, updated_at=datetime.utcnow())
    )
    await db.commit()
    if admin:
        context["current"][0].role = UserRole.GERENTE
    assert (await post_document(client, context, admin=admin)).status_code == 400
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
async def test_admin_can_still_replace_pending_document(submissions):
    client, db, context = submissions
    await db.execute(
        update(RiderDocument).values(
            status=DocumentStatus.PENDIENTE, updated_at=datetime.utcnow()
        )
    )
    await db.commit()
    context["current"][0].role = UserRole.SUPERADMIN
    assert (await post_document(client, context, admin=True)).status_code == 200


@pytest.mark.asyncio
async def test_invalid_replacement_leaves_old_reference_and_file(submissions):
    client, db, context = submissions
    response = await post_document(client, context, data=b"<html>bad</html>")
    assert response.status_code == 415
    reference, status = await references(db, context["doc_id"])
    assert reference == context["old_reference"] and status == DocumentStatus.RECHAZADO
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
async def test_sql_failure_before_commit_removes_only_new_file(submissions):
    client, db, context = submissions
    with patch.object(
        db,
        "flush",
        side_effect=IntegrityError(
            "sensitive internal statement", {}, Exception("failure")
        ),
    ):
        response = await post_document(client, context)
    assert response.status_code == 503 and "sensitive" not in response.text
    reference, status = await references(db, context["doc_id"])
    assert reference == context["old_reference"] and status == DocumentStatus.RECHAZADO
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
async def test_partial_disk_failure_removes_new_file_and_hides_internal_path(
    submissions,
):
    client, db, context = submissions
    with patch.object(service.os, "fsync", side_effect=OSError("/private/path secret")):
        response = await post_document(client, context)
    assert response.status_code == 503 and "/private/path" not in response.text
    assert (await references(db, context["doc_id"]))[0] == context["old_reference"]
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_uncertain_commit_never_deletes_a_potentially_confirmed_file(
    submissions, committed
):
    client, db, context = submissions
    commit = db.commit

    async def lost_ack():
        if committed:
            await commit()
        raise OSError("lost acknowledgement")

    with patch.object(db, "commit", lost_ack):
        response = await post_document(client, context)
    assert response.status_code == 503 and "Revisa el estado" in response.text
    assert len(list(context["root"].rglob("*.pdf"))) == 2
    reference, _ = await references(db, context["doc_id"])
    assert (reference != context["old_reference"]) is committed
    assert resolve_document_file(context["rider_id"], reference).exists()


async def register(client, *, bad_last=False):
    names = (
        "license_file",
        "id_card_file",
        "vehicle_registration_file",
        "insurance_file",
    )
    files = {
        name: (
            name + ".pdf",
            b"bad" if bad_last and name == names[-1] else PDF,
            "application/pdf",
        )
        for name in names
    }
    return await client.post(
        "/api/v1/auth/register-rider",
        data={
            "email": f"{uuid4()}@example.test",
            "password": "valid-password",
            "first_name": "New",
            "last_name": "Rider",
            "vehicle_type": "MOTO",
        },
        files=files,
    )


async def counts(db):
    return tuple(
        [
            await db.scalar(select(func.count()).select_from(model))
            for model in (User, Rider, RiderDocument)
        ]
    )


@pytest.mark.asyncio
async def test_invalid_fourth_document_creates_no_account_or_files(submissions):
    client, db, context = submissions
    before = await counts(db)
    assert (await register(client, bad_last=True)).status_code == 415
    assert await counts(db) == before
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
async def test_registration_saves_four_valid_documents_in_single_batch(submissions):
    client, db, context = submissions
    before = await counts(db)
    response = await register(client)
    assert response.status_code == 201, response.text
    assert await counts(db) == tuple(x + delta for x, delta in zip(before, (1, 1, 4)))
    rider_id = await db.scalar(
        select(Rider.id).where(Rider.user_id == UUID(response.json()["user_id"]))
    )
    paths = list((context["root"] / "documents" / str(rider_id)).iterdir())
    assert len(paths) == 4 and all(path.read_bytes() == PDF for path in paths)
    assert (
        await db.scalar(
            select(User.role).where(User.id == UUID(response.json()["user_id"]))
        )
        == UserRole.REPARTIDOR
    )


@pytest.mark.asyncio
async def test_registration_late_disk_failure_rolls_back_all_new_rows_and_files(
    submissions,
):
    client, db, context = submissions
    before = await counts(db)
    write = service.DocumentUploadBatch._write

    def fail_third(batch, *args):
        if len(batch.paths) == 2:
            raise OSError("disk failure")
        return write(batch, *args)

    with patch.object(service.DocumentUploadBatch, "_write", fail_third):
        response = await register(client)
    assert response.status_code == 503
    assert await counts(db) == before
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
async def test_cancellation_before_commit_cleans_batch_and_propagates(submissions):
    _, db, context = submissions
    document = await service.validate_document(upload())
    with pytest.raises(asyncio.CancelledError):
        async with service.DocumentUploadBatch(db) as batch:
            await batch.store(document, context["rider_id"], DocumentType.SEGURO)
            raise asyncio.CancelledError()
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
async def test_duplicate_historical_documents_require_review(submissions):
    client, db, context = submissions
    db.add(
        RiderDocument(
            rider_id=context["rider_id"],
            type=DocumentType.LICENCIA,
            status=DocumentStatus.RECHAZADO,
        )
    )
    await db.commit()
    assert (await post_document(client, context)).status_code == 409
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
async def test_existing_file_is_never_overwritten_or_deleted_on_name_collision(
    submissions,
):
    client, db, context = submissions
    fixed_id = UUID("123e4567-e89b-42d3-a456-426614174000")
    collision = context["old_file"].parent / f"licencia_{fixed_id}.pdf"
    collision.write_bytes(b"previous upload")
    with patch.object(service, "uuid4", return_value=fixed_id):
        response = await post_document(client, context)
    assert response.status_code == 503
    assert collision.read_bytes() == b"previous upload"
    assert (await references(db, context["doc_id"]))[0] == context["old_reference"]


@pytest.mark.asyncio
async def test_symlink_directory_is_not_used_for_new_uploads(submissions):
    client, _, context = submissions
    folder = context["old_file"].parent
    actual = folder.with_name("retained-original")
    folder.rename(actual)
    folder.symlink_to(actual, target_is_directory=True)
    assert (await post_document(client, context)).status_code == 503
    assert len(list(actual.iterdir())) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,admin",
    [
        (UserRole.CLIENTE, False),
        (UserRole.AUDITOR, False),
        (UserRole.REPARTIDOR, True),
        (UserRole.OPERADOR, True),
    ],
)
async def test_upload_roles_are_enforced_before_file_storage(submissions, role, admin):
    client, _, context = submissions
    context["current"][0].role = role
    assert (await post_document(client, context, admin=admin)).status_code == 403
    assert list(context["root"].rglob("*.pdf")) == [context["old_file"]]


@pytest.mark.asyncio
async def test_symlink_document_root_is_rejected_before_creating_an_outside_directory(
    submissions, tmp_path
):
    _, db, context = submissions
    root = context["root"] / "documents"
    retained = root.with_name("retained-documents")
    root.rename(retained)
    outside = tmp_path / "outside"
    outside.mkdir()
    root.symlink_to(outside, target_is_directory=True)
    document = await service.validate_document(upload())
    with pytest.raises(HTTPException) as error:
        async with service.DocumentUploadBatch(db) as batch:
            await batch.store(document, uuid4(), DocumentType.SEGURO)
    assert error.value.status_code == 503
    assert not list(outside.iterdir())
    assert len(list(retained.rglob("*.pdf"))) == 1


@pytest.mark.asyncio
async def test_review_routes_keep_upload_rules_and_rider_state_coherent(submissions):
    client, db, context = submissions
    context["current"][0].role = UserRole.GERENTE
    assert (await post_document(client, context, admin=True)).status_code == 200
    path = f"/api/v1/riders/documents/{context['doc_id']}/status"
    revision = (
        await client.get(f"/api/v1/riders/{context['rider_id']}/documents")
    ).json()[0]["revision"]
    approved = await client.patch(
        path, json={"status": "APROBADO", "expected_revision": revision}
    )
    assert approved.status_code == 200, approved.text
    assert (await references(db, context["doc_id"]))[1] == DocumentStatus.APROBADO
    context["current"][0].role = UserRole.REPARTIDOR
    assert (await post_document(client, context)).status_code == 400
    context["current"][0].role = UserRole.GERENTE
    rejected = await client.patch(
        path,
        json={
            "status": "RECHAZADO",
            "rejection_reason": "Nueva revisión requerida",
            "expected_revision": approved.json()["revision"],
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert (await references(db, context["doc_id"]))[1] == DocumentStatus.RECHAZADO
    assert (
        await db.scalar(select(Rider.is_online).where(Rider.id == context["rider_id"]))
        is False
    )


@pytest.mark.asyncio
async def test_delete_removes_reference_but_does_not_delete_historical_file(
    submissions,
):
    client, db, context = submissions
    context["current"][0].role = UserRole.GERENTE
    row = await db.get(RiderDocument, context["doc_id"])
    await db.refresh(row)
    response = await client.delete(
        f"/api/v1/riders/documents/{context['doc_id']}",
        headers={"If-Match": document_revision(row)},
    )
    assert response.status_code == 200, response.text
    assert (
        await db.scalar(
            select(RiderDocument.id).where(RiderDocument.id == context["doc_id"])
        )
        is None
    )
    assert context["old_file"].exists()
    assert (
        await client.get(f"/api/v1/riders/documents/{context['doc_id']}/download")
    ).status_code == 404
