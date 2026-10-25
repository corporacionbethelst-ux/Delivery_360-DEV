# backend/app/models/rider_document.py
import uuid
from sqlalchemy import String, Text, text, Enum, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import enum
import sqlalchemy as sa


class DocumentType(str, enum.Enum):
    LICENCIA = "LICENCIA"
    DOCUMENTO_IDENTIDAD = "DOCUMENTO_IDENTIDAD"
    REGISTRO_VEHICULO = "REGISTRO_VEHICULO"
    SEGURO = "SEGURO"


class DocumentStatus(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"


class RiderDocument(Base):
    __tablename__ = "rider_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        default=uuid.uuid4,
        nullable=False,
    )
    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), default=DocumentStatus.PENDIENTE, nullable=False
    )
    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # CORRECCIÓN AQUÍ: Usar server_default con texto SQL
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), server_default=sa.text("NOW()"), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        server_default=sa.text("NOW()"),
        onupdate=sa.text("NOW()"),
        nullable=True,
    )

    # Relaciones
    rider = relationship("Rider", back_populates="documents")
