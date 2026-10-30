"""Public registry metadata. Provider secrets and arbitrary configuration are private."""

from datetime import datetime
from typing import Literal
from uuid import UUID
import unicodedata
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models.integration import IntegrationType, IntegrationStatus


def label(value: str) -> str:
    value = value.strip()
    if not value or any(unicodedata.category(char) in ("Cc", "Cf") for char in value):
        raise ValueError(
            "El texto debe ser visible y no contener caracteres de control"
        )
    return value


class IntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    integration_type: IntegrationType
    provider: str | None = Field(default=None, max_length=50)
    sync_frequency_minutes: int = Field(default=60, ge=1, le=1440, strict=True)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return label(value) if isinstance(value, str) else value

    @field_validator("provider", mode="before")
    @classmethod
    def clean_provider(cls, value):
        if value is None or isinstance(value, str) and not value.strip():
            return None
        return label(value) if isinstance(value, str) else value


class IntegrationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: str | None = Field(default=None, max_length=50)
    sync_frequency_minutes: int | None = Field(default=None, ge=1, le=1440, strict=True)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        if value is None:
            raise ValueError("El nombre no puede ser nulo")
        return label(value) if isinstance(value, str) else value

    @field_validator("provider", mode="before")
    @classmethod
    def clean_provider(cls, value):
        if value is None or isinstance(value, str) and not value.strip():
            return None
        return label(value) if isinstance(value, str) else value

    @field_validator("sync_frequency_minutes")
    @classmethod
    def frequency_not_null(cls, value):
        if value is None:
            raise ValueError("La frecuencia no puede ser nula")
        return value

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_fields_set:
            raise ValueError("Debe indicar al menos un campo de metadatos")
        return self


class IntegrationRead(BaseModel):
    id: UUID
    name: str
    integration_type: IntegrationType
    type: IntegrationType
    provider: str | None
    status: IntegrationStatus | None
    is_active: bool
    sync_enabled: bool | None
    sync_frequency_minutes: int | None
    consecutive_failures: int | None = Field(ge=0)
    last_sync_at: datetime | None
    last_error_at: datetime | None
    sync_last_run: datetime | None
    sync_next_run: datetime | None
    created_at: datetime | None
    updated_at: datetime | None
    created_by: UUID | None
    has_endpoint: bool
    has_credentials: bool
    has_config: bool
    has_webhook: bool
    has_signing_secret: bool
    has_last_error: bool
    connection_verified: Literal[False] = False


class IntegrationDiagnostic(BaseModel):
    integration_id: UUID
    status: IntegrationStatus | None
    performed: Literal[False] = False
    connection_verified: Literal[False] = False
    synchronization_available: Literal[False] = False
    outcome: Literal["not_checked"] = "not_checked"
    blocking_reasons: list[str]
