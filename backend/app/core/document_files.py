"""Private file access within the existing persistent uploads volume."""

import hashlib
import hmac
import json
import re
from app.models.rider_document import RiderDocument
from pathlib import Path
from uuid import UUID

import anyio
from fastapi import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


def document_download_url(document_id: UUID, reference: str | None) -> str | None:
    return f"/api/v1/riders/documents/{document_id}/download" if reference else None


def document_revision(doc: RiderDocument) -> str:
    """Fingerprint the immutable file reference and current review metadata.

    This is an optimistic concurrency token, not an authorization credential or
    a digest attesting to bytes modified outside the application's writers.
    """
    fields = [
        str(doc.id),
        str(doc.rider_id),
        doc.type.value,
        doc.file_url,
        doc.status.value,
        doc.rejection_reason,
        doc.updated_at.isoformat() if doc.updated_at else None,
    ]
    return hashlib.sha256(
        json.dumps(fields, separators=(",", ":")).encode()
    ).hexdigest()


def ensure_document_revision(doc: RiderDocument, expected: str | None) -> None:
    if (
        expected is not None
        and len(expected) == 66
        and expected.startswith('"')
        and expected.endswith('"')
    ):
        expected = expected[1:-1]
    if expected is None:
        raise HTTPException(
            status_code=409,
            detail="Recarga la documentación para enviar la revisión actual",
        )
    if re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        raise HTTPException(status_code=422, detail="Revisión de documento inválida")
    if not hmac.compare_digest(document_revision(doc), expected):
        raise HTTPException(
            status_code=409,
            detail="El documento cambió. Recarga y revisa la nueva versión",
        )


def resolve_document_file(rider_id: UUID, reference: str | None) -> Path:
    """Resolve one local file belonging to this rider; never fetch a remote URL."""
    prefix = f"/uploads/documents/{rider_id}/"
    if reference and not reference.startswith("/"):
        reference = "/" + reference
    if not reference or not reference.startswith(prefix):
        raise HTTPException(status_code=404, detail="Archivo no disponible")
    filename = reference[len(prefix) :]
    if (
        not filename
        or filename in (".", "..")
        or any(c in filename for c in ("/", "\\", "\x00", "?", "#", ":"))
    ):
        raise HTTPException(status_code=404, detail="Archivo no disponible")
    rider_dir = (Path("uploads").resolve() / "documents").resolve() / str(rider_id)
    try:
        candidate = (rider_dir / filename).resolve(strict=True)
        if candidate.parent != rider_dir or not candidate.is_file():
            raise OSError("Invalid document location")
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(status_code=404, detail="Archivo no disponible") from None
    return candidate


class PublicUploads(StaticFiles):
    """Deny documents and their symbolic link aliases; retain other static files."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if Path(path).parts and Path(path).parts[0] == "documents":
            raise StarletteHTTPException(status_code=404)
        full_path, _ = await anyio.to_thread.run_sync(self.lookup_path, path)
        if full_path:
            candidate = Path(full_path).resolve()
            for directory in self.all_directories:
                if candidate.is_relative_to((Path(directory) / "documents").resolve()):
                    raise StarletteHTTPException(status_code=404)
        return await super().get_response(path, scope)
