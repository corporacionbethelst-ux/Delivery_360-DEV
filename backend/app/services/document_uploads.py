"""Bounded file validation and owned file/SQL submission lifecycle.

Magic checks identify permitted containers; they are not full decoding or malware
analysis. A commit exception is ambiguous: retain files until reconciliation.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal
from uuid import UUID, uuid4

import anyio
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.document_review import (
    lock_document as lock_document,
    restrict_rider_documents,
)
from app.core.document_files import document_revision
from app.models.rider import Rider, utc_now_naive
from app.models.rider_document import RiderDocument, DocumentType, DocumentStatus

logger = logging.getLogger(__name__)
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ValidatedDocument:
    data: bytes
    extension: str


async def validate_document(file: UploadFile) -> ValidatedDocument:
    extension = Path(file.filename or "").suffix.lower()
    types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    if extension not in types:
        raise HTTPException(
            status_code=415, detail="Solo se admiten documentos PDF, PNG o JPEG"
        )
    declared = (file.content_type or "").split(";", 1)[0].strip().lower()
    if declared not in ("", "application/octet-stream", types[extension]):
        raise HTTPException(
            status_code=415, detail="El tipo declarado no coincide con el archivo"
        )
    await file.seek(0)
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=413, detail="El documento excede el máximo de 10 MiB"
        )
    if not data:
        raise HTTPException(status_code=422, detail="El documento está vacío")
    expected = types[extension]
    matches = (
        expected == "application/pdf"
        and len(data) >= 8
        and data[:5] == b"%PDF-"
        and data[5:6].isdigit()
        and data[6:7] == b"."
        and data[7:8].isdigit()
        or expected == "image/png"
        and len(data) > 8
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        or expected == "image/jpeg"
        and len(data) > 3
        and data.startswith(b"\xff\xd8\xff")
    )
    if not matches:
        raise HTTPException(
            status_code=415, detail="El contenido no corresponde al formato declarado"
        )
    return ValidatedDocument(data, ".jpg" if expected == "image/jpeg" else extension)


class DocumentUploadBatch:
    """Own this request's new files and SQL transaction, without deleting history."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.paths: list[Path] = []
        self.commit_attempted = False
        self.committed = False

    async def __aenter__(self) -> "DocumentUploadBatch":
        return self

    def _write(
        self, document: ValidatedDocument, rider_id: UUID, kind: DocumentType
    ) -> str:
        root = Path("uploads").resolve() / "documents"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.resolve() != root:
            raise OSError("Document root must not be a symbolic link")
        directory = root / str(rider_id)
        directory.mkdir(exist_ok=True, mode=0o700)
        if directory.resolve() != directory:
            raise OSError("Document directories must not be symbolic links")
        filename = f"{kind.value.lower()}_{uuid4()}{document.extension}"
        path = directory / filename
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        self.paths.append(path)
        with os.fdopen(fd, "wb") as target:
            target.write(document.data)
            target.flush()
            os.fsync(target.fileno())
        return f"/uploads/documents/{rider_id}/{filename}"

    async def store(
        self, document: ValidatedDocument, rider_id: UUID, kind: DocumentType
    ) -> str:
        return await anyio.to_thread.run_sync(self._write, document, rider_id, kind)

    async def commit(self) -> None:
        await self.db.flush()
        self.commit_attempted = True
        await self.db.commit()
        self.committed = True

    def _cleanup(self) -> None:
        for path in self.paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.error(
                    "New document file cleanup failed; reconciliation required"
                )

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        if self.committed:
            return False
        with anyio.CancelScope(shield=True):
            try:
                await self.db.rollback()
            except Exception:
                logger.error("Document transaction rollback unavailable")
            if not self.commit_attempted:
                await anyio.to_thread.run_sync(self._cleanup)
        if exc is not None and not isinstance(exc, Exception):
            return False
        if isinstance(exc, HTTPException) and not self.commit_attempted:
            return False
        if self.commit_attempted:
            logger.error("Document commit outcome uncertain; new files retained")
            raise HTTPException(
                status_code=503,
                detail="No se pudo confirmar el resultado. Revisa el estado antes de volver a enviar documentos.",
            ) from None
        logger.error("Document submission failed before commit")
        raise HTTPException(
            status_code=503,
            detail="No se pudo guardar la documentación. Intenta nuevamente más tarde.",
        ) from None


async def replace_document(
    db: AsyncSession,
    rider_id: UUID,
    kind: DocumentType,
    document: ValidatedDocument,
    *,
    allow_pending: bool,
) -> dict[str, str | None]:
    from app.core.document_files import document_download_url

    async with DocumentUploadBatch(db) as batch:
        if (
            await db.scalar(
                select(Rider.id).where(Rider.id == rider_id).with_for_update()
            )
            is None
        ):
            raise HTTPException(
                status_code=404, detail="Perfil de repartidor no encontrado"
            )
        matches = list(
            (
                await db.scalars(
                    select(RiderDocument)
                    .where(
                        RiderDocument.rider_id == rider_id, RiderDocument.type == kind
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                    .limit(2)
                )
            ).all()
        )
        if len(matches) > 1:
            raise HTTPException(
                status_code=409, detail="Documentos duplicados requieren revisión"
            )
        doc = matches[0] if matches else None
        if doc is not None and (
            doc.status == DocumentStatus.APROBADO
            or doc.status == DocumentStatus.PENDIENTE
            and not allow_pending
        ):
            raise HTTPException(
                status_code=400,
                detail="El documento está aprobado o en revisión y no puede reemplazarse",
            )
        reference = await batch.store(document, rider_id, kind)
        if doc is None:
            doc = RiderDocument(id=uuid4(), rider_id=rider_id, type=kind)
            db.add(doc)
        doc.file_url = reference
        doc.status = DocumentStatus.PENDIENTE
        doc.rejection_reason = None
        doc.updated_at = utc_now_naive()
        await db.flush()
        await restrict_rider_documents(db, rider_id)
        response = {
            "id": str(doc.id),
            "type": doc.type.value,
            "status": doc.status.value,
            "file_url": document_download_url(doc.id, doc.file_url),
            "revision": document_revision(doc),
            "message": "Documento subido exitosamente.",
        }
        await batch.commit()
    return response
