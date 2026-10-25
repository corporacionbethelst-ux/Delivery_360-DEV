"""Document review and eligibility. All mutations lock Rider then document.

Callers authorize the actor and own commit/rollback. Automatic document approval
never lifts a suspension or an administratively inactive state.
"""

from uuid import UUID
import anyio
from fastapi import HTTPException
from sqlalchemy import case, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.document_files import (
    document_revision,
    ensure_document_revision,
    resolve_document_file,
)
from app.models.rider import Rider, RiderStatus, utc_now_naive
from app.models.rider_document import RiderDocument, DocumentStatus, DocumentType

REQUIRED_DOCUMENT_TYPES = frozenset(DocumentType)


async def lock_rider(db: AsyncSession, rider_id: UUID) -> None:
    if (
        await db.scalar(select(Rider.id).where(Rider.id == rider_id).with_for_update())
        is None
    ):
        raise HTTPException(status_code=404, detail="Repartidor no encontrado")


async def lock_document(db: AsyncSession, document_id: UUID) -> RiderDocument:
    rider_id = await db.scalar(
        select(RiderDocument.rider_id).where(RiderDocument.id == document_id)
    )
    if rider_id is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    await lock_rider(db, rider_id)
    doc = await db.scalar(
        select(RiderDocument)
        .where(RiderDocument.id == document_id, RiderDocument.rider_id == rider_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


async def rider_documents(db: AsyncSession, rider_id: UUID) -> list[RiderDocument]:
    return list(
        (
            await db.scalars(
                select(RiderDocument)
                .where(RiderDocument.rider_id == rider_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


def required_document_error(documents: list[RiderDocument]) -> str | None:
    types = [doc.type for doc in documents]
    if len(types) != len(set(types)):
        return "Hay documentos duplicados que requieren revisión"
    missing = REQUIRED_DOCUMENT_TYPES - set(types)
    if missing:
        return "Faltan documentos requeridos: " + ", ".join(
            sorted(kind.value for kind in missing)
        )
    if any(doc.status != DocumentStatus.APROBADO for doc in documents):
        return "Todos los documentos requeridos deben estar aprobados"
    if any(not doc.file_url for doc in documents):
        return "Un documento requerido no tiene archivo disponible"
    return None


def _availability_error(documents: list[RiderDocument]) -> str | None:
    for doc in documents:
        try:
            path = resolve_document_file(doc.rider_id, doc.file_url)
            with path.open("rb") as source:
                if not source.read(1):
                    return "Un documento requerido está vacío"
        except (HTTPException, OSError):
            return "Un documento requerido no está disponible"
    return None


async def document_readiness_error(db: AsyncSession, rider_id: UUID) -> str | None:
    documents = await rider_documents(db, rider_id)
    error = required_document_error(documents)
    return error or await anyio.to_thread.run_sync(_availability_error, documents)


async def restrict_rider_documents(db: AsyncSession, rider_id: UUID) -> None:
    """Close availability while preserving administrative suspension/inactivity."""
    await db.execute(
        update(Rider)
        .where(Rider.id == rider_id)
        .values(
            status=case(
                (
                    Rider.status.in_((RiderStatus.ACTIVO, RiderStatus.OCUPADO)),
                    literal(RiderStatus.PENDIENTE, type_=Rider.__table__.c.status.type),
                ),
                else_=Rider.status,
            ),
            is_online=False,
        )
    )


async def reconcile_document_eligibility(
    db: AsyncSession, rider_id: UUID, *, auto_activate: bool = False
) -> None:
    error = await document_readiness_error(db, rider_id)
    if error:
        await restrict_rider_documents(db, rider_id)
        return
    status = await db.scalar(select(Rider.status).where(Rider.id == rider_id))
    if auto_activate and status == RiderStatus.PENDIENTE:
        await db.execute(
            update(Rider)
            .where(Rider.id == rider_id)
            .values(
                status=RiderStatus.ACTIVO, approved_at=utc_now_naive(), is_online=False
            )
        )
    elif status not in (RiderStatus.ACTIVO, RiderStatus.OCUPADO):
        await db.execute(
            update(Rider).where(Rider.id == rider_id).values(is_online=False)
        )


async def review_document(
    db: AsyncSession,
    document_id: UUID,
    target: DocumentStatus,
    expected_revision: str | None,
    reason: str | None = None,
) -> dict[str, str]:
    if target not in (DocumentStatus.APROBADO, DocumentStatus.RECHAZADO):
        raise HTTPException(status_code=400, detail="Estado de revisión inválido")
    if target == DocumentStatus.RECHAZADO and (not reason or not reason.strip()):
        raise HTTPException(
            status_code=400, detail="Se requiere un motivo para el rechazo"
        )
    doc = await lock_document(db, document_id)
    ensure_document_revision(doc, expected_revision)
    if target == DocumentStatus.APROBADO:
        peers = await rider_documents(db, doc.rider_id)
        if sum(item.type == doc.type for item in peers) > 1:
            raise HTTPException(
                status_code=409,
                detail="Hay documentos duplicados que requieren revisión",
            )
        error = await anyio.to_thread.run_sync(_availability_error, [doc])
        if error:
            raise HTTPException(status_code=409, detail=error)
    doc.status = target
    doc.rejection_reason = (
        reason.strip() if target == DocumentStatus.RECHAZADO and reason else None
    )
    doc.updated_at = utc_now_naive()
    await db.flush()
    await reconcile_document_eligibility(
        db, doc.rider_id, auto_activate=target == DocumentStatus.APROBADO
    )
    return {
        "message": f"Documento {target.value.lower()} correctamente",
        "doc_id": str(doc.id),
        "status": target.value,
        "revision": document_revision(doc),
    }


async def delete_reviewed_document(
    db: AsyncSession, document_id: UUID, expected_revision: str | None
) -> dict[str, str]:
    doc = await lock_document(db, document_id)
    ensure_document_revision(doc, expected_revision)
    rider_id = doc.rider_id
    response = {"message": "Documento eliminado exitosamente", "doc_id": str(doc.id)}
    await db.delete(doc)
    await db.flush()
    await reconcile_document_eligibility(db, rider_id)
    return response


async def ensure_rider_can_report_online(
    db: AsyncSession, rider: Rider, *, allow_busy: bool = False
) -> None:
    """Authorize availability under the parent lock; caller commits success.

    Denials persist the safety restriction before raising. Call before adding
    location rows or other changes: a denied report must not commit its payload.
    """
    await lock_rider(db, rider.id)
    await db.refresh(rider, attribute_names=["status", "is_online", "approved_at"])
    permitted = (
        (RiderStatus.ACTIVO, RiderStatus.OCUPADO)
        if allow_busy
        else (RiderStatus.ACTIVO,)
    )
    if rider.status not in permitted:
        rider.is_online = False
        await db.commit()
        raise HTTPException(
            status_code=403,
            detail="No puedes conectarte hasta que un gerente active tu cuenta",
        )
    error = await document_readiness_error(db, rider.id)
    if error:
        await restrict_rider_documents(db, rider.id)
        await db.commit()
        raise HTTPException(
            status_code=403, detail=f"La documentación requiere revisión. {error}"
        )
