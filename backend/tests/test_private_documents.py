"""Document confidentiality: real HTTP, local files, ownership and DDL contracts."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.api.v1 import riders as api
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.core.document_files import PublicUploads
from app.models.rider import Rider, RiderStatus
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus
from app.models.user import User, UserRole
from tests.orm_contract import detailed_mapping_contract


def test_document_mapping_preserves_postgresql_contract():
    expected = json.loads(
        (Path(__file__).parent / "fixtures/orm_document_contract.json").read_text()
    )
    assert detailed_mapping_contract(("rider_documents",)) == expected


@pytest.fixture
async def documents(db_session, test_user, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    second_user = User(
        email="other-doc@example.test",
        hashed_password="unused",
        first_name="Other",
        last_name="Rider",
        role=UserRole.REPARTIDOR,
    )
    db_session.add(second_user)
    await db_session.flush()
    rider, other_rider = Rider(user_id=test_user.id, status=RiderStatus.ACTIVO), Rider(
        user_id=second_user.id, status=RiderStatus.ACTIVO
    )
    db_session.add_all([rider, other_rider])
    await db_session.flush()
    root = tmp_path / "uploads"
    folder = root / "documents" / str(rider.id)
    folder.mkdir(parents=True)
    file = folder / "licencia.pdf"
    file.write_bytes(b"%PDF-1.4 private document")
    doc = RiderDocument(
        rider_id=rider.id,
        type=DocumentType.LICENCIA,
        status=DocumentStatus.PENDIENTE,
        file_url=f"/uploads/documents/{rider.id}/licencia.pdf",
    )
    db_session.add(doc)
    await db_session.commit()
    current = [SimpleNamespace(id=test_user.id, role=UserRole.REPARTIDOR)]
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.mount("/uploads", PublicUploads(directory=str(root)))

    async def database():
        yield db_session

    async def identity():
        return current[0]

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = identity
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, db_session, doc, current, second_user.id, root, file


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [UserRole.SUPERADMIN, UserRole.GERENTE, UserRole.OPERADOR, UserRole.REPARTIDOR],
)
async def test_authorized_download_returns_attachment_and_private_headers(
    documents, role
):
    client, db, doc, current, _, _, file = documents
    current[0].role = role
    with patch.object(db, "commit", wraps=db.commit) as commit:
        response = await client.get(f"/api/v1/riders/documents/{doc.id}/download")
        commit.assert_not_awaited()
    assert response.status_code == 200, response.text
    assert response.content == file.read_bytes()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_other_rider_sees_same_response_as_missing_document(documents):
    client, _, doc, current, other_user, _, _ = documents
    current[0].id = other_user
    foreign = await client.get(f"/api/v1/riders/documents/{doc.id}/download")
    missing = await client.get(f"/api/v1/riders/documents/{uuid4()}/download")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.CLIENTE, UserRole.AUDITOR, None])
async def test_disallowed_roles_are_rejected_before_document_lookup(documents, role):
    client, db, doc, current, _, _, _ = documents
    current[0].role = role
    with patch.object(db, "scalar", wraps=db.scalar) as query:
        assert (
            await client.get(f"/api/v1/riders/documents/{doc.id}/download")
        ).status_code == 403
        query.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_authentication_never_returns_document(documents):
    _, _, doc, _, _, _, _ = documents
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/riders/documents/{doc.id}/download")
    assert response.status_code == 401
    assert b"%PDF" not in response.content


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("encoding", ["documents", "%64ocuments", "safe/../documents"])
async def test_static_urls_do_not_expose_existing_documents(
    documents, method, encoding
):
    client, _, doc, _, _, _, _ = documents
    response = await client.request(
        method, f"/uploads/{encoding}/{doc.rider_id}/licencia.pdf"
    )
    assert response.status_code == 404
    assert b"private document" not in response.content


@pytest.mark.asyncio
async def test_static_symlink_alias_is_denied_but_other_public_assets_work(documents):
    client, _, _, _, _, root, file = documents
    (root / "alias.pdf").symlink_to(file)
    (root / "banner.txt").write_text("public banner")
    assert (await client.get("/uploads/alias.pdf")).status_code == 404
    public = await client.get("/uploads/banner.txt")
    assert public.status_code == 200 and public.text == "public banner"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference",
    [
        None,
        "",
        "https://example.test/private.pdf",
        "/etc/passwd",
        "/uploads/documents/other-rider/secret.pdf",
        "../secret.pdf",
        "__PREFIX__../secret.pdf",
        "__PREFIX__missing.pdf",
        "__PREFIX__licencia.pdf?token=unsafe",
        "__PREFIX__nested/file.pdf",
    ],
)
async def test_missing_remote_or_unsafe_references_never_serve_bytes(
    documents, reference
):
    client, db, doc, _, _, _, _ = documents
    if reference:
        reference = reference.replace(
            "__PREFIX__", f"/uploads/documents/{doc.rider_id}/"
        )
    await db.execute(
        update(RiderDocument)
        .where(RiderDocument.id == doc.id)
        .values(file_url=reference, updated_at=datetime.utcnow())
    )
    await db.commit()
    response = await client.get(f"/api/v1/riders/documents/{doc.id}/download")
    assert response.status_code == 404
    assert b"private document" not in response.content


@pytest.mark.asyncio
async def test_authorized_endpoint_rejects_symlink_escape(documents):
    client, _, doc, _, _, root, file = documents
    outside = root.parent / "secret.pdf"
    outside.write_bytes(b"another secret")
    file.unlink()
    file.symlink_to(outside)
    response = await client.get(f"/api/v1/riders/documents/{doc.id}/download")
    assert response.status_code == 404 and b"another secret" not in response.content


@pytest.mark.asyncio
async def test_metadata_uses_authenticated_route_instead_of_storage_url(documents):
    client, _, doc, current, _, _, _ = documents
    own = await client.get("/api/v1/riders/me/documents")
    assert own.status_code == 200, own.text
    expected = f"/api/v1/riders/documents/{doc.id}/download"
    assert own.json()[0]["file_url"] == expected
    current[0].role = UserRole.GERENTE
    staff = await client.get(f"/api/v1/riders/{doc.rider_id}/documents")
    assert staff.status_code == 200, staff.text
    assert staff.json()[0]["file_url"] == expected
    assert "/uploads/" not in staff.text


def test_application_mount_uses_document_excluding_static_handler():
    from app.main import app

    mount = next(route for route in app.routes if route.path == "/uploads")
    assert isinstance(mount.app, PublicUploads)


@pytest.mark.asyncio
async def test_old_http_cache_cannot_bypass_private_static_guard(
    documents, monkeypatch
):
    from app.middleware.cache_middleware import CacheMiddleware, settings, cache_service

    _, _, doc, _, _, root, _ = documents
    app = FastAPI()
    app.mount("/uploads", PublicUploads(directory=str(root)))
    app.add_middleware(CacheMiddleware)
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(cache_service, "connected", True)
    cached = AsyncMock(
        return_value={
            "body": "private document",
            "status_code": 200,
            "media_type": "application/pdf",
        }
    )
    monkeypatch.setattr(cache_service, "get", cached)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/uploads/documents/{doc.rider_id}/licencia.pdf")
    assert response.status_code == 404
    cached.assert_not_awaited()
