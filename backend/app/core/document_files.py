"""Private file access within the existing persistent uploads volume."""

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
