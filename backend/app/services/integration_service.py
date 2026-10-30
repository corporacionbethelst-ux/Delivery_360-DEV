"""Integration registry transactions; external adapters require verified implementation."""

import json
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import UUID
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ValidationError, NotFoundError, AppException
from app.core.json_types import JsonValue, json_value
from app.core.reporting_period import aware_utc
from app.models.integration import (
    Integration,
    IntegrationType,
    IntegrationStatus,
    WebhookEvent,
    WebhookEventType,
)
from app.models.audit_log import AuditLog, ActionType
from app.models.user import User
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationPatch,
    IntegrationRead,
    IntegrationDiagnostic,
)

IntegrationConfig = dict[str, Any]
POSOrderData = dict[str, Any]
ERPFinancialData = dict[str, Any]
WebhookPayload = dict[str, Any]
MAX_JSON_BYTES = 65536


class TestConnectionResult(TypedDict):
    success: bool
    error: str | None
    message: str | None
    performed: bool
    connection_verified: bool


def bounded_json(value: object) -> tuple[JsonValue, str]:
    try:
        clean = json_value(value)
        encoded = json.dumps(
            clean, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("size")
        return clean, encoded
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ValidationError(
            "Configuración o payload JSON inválido o superior a 64 KiB"
        ) from None


def require_uuid(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise ValidationError("El identificador de integración debe ser UUID")


def public_statement():
    # Read presence flags in SQL. Raw secrets/configuration/provider errors never
    # enter a public result or a registry audit entry.
    def present(column):
        return func.coalesce(func.length(func.btrim(column)) > 0, False)

    return select(
        Integration.id,
        Integration.name,
        Integration.integration_type,
        Integration.provider,
        Integration.status,
        Integration.sync_enabled,
        Integration.sync_frequency_minutes,
        Integration.consecutive_failures,
        Integration.last_sync_at,
        Integration.last_error_at,
        Integration.sync_last_run,
        Integration.sync_next_run,
        Integration.created_at,
        Integration.updated_at,
        Integration.created_by,
        present(Integration.api_url).label("has_endpoint"),
        present(Integration.credentials).label("has_credentials"),
        present(Integration.config).label("has_config"),
        present(Integration.webhook_url).label("has_webhook"),
        present(Integration.webhook_secret).label("has_signing_secret"),
        present(Integration.last_error_message).label("has_last_error"),
    )


def public_summary(row) -> IntegrationRead:
    data = dict(row)
    data["type"] = data["integration_type"]
    data["is_active"] = data["status"] == IntegrationStatus.ACTIVE
    for key in (
        "last_sync_at",
        "last_error_at",
        "sync_last_run",
        "sync_next_run",
        "created_at",
        "updated_at",
    ):
        data[key] = aware_utc(data[key]) if data[key] is not None else None
    if data["consecutive_failures"] is not None and data["consecutive_failures"] < 0:
        data["consecutive_failures"] = None
    if (
        data["sync_frequency_minutes"] is not None
        and data["sync_frequency_minutes"] <= 0
    ):
        data["sync_frequency_minutes"] = None
    return IntegrationRead.model_validate(data)


class IntegrationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_integration(self, integration_id: UUID) -> Integration | None:
        """Internal ORM compatibility only; HTTP uses the explicit projection."""
        require_uuid(integration_id)
        return await self.db.scalar(
            select(Integration).where(Integration.id == integration_id)
        )

    async def get_summary(
        self, integration_id: UUID, *, lock: bool = False
    ) -> IntegrationRead | None:
        require_uuid(integration_id)
        query = public_statement().where(Integration.id == integration_id)
        if lock:
            query = query.with_for_update()
        row = (await self.db.execute(query)).mappings().first()
        return public_summary(row) if row is not None else None

    async def list_integrations(
        self,
        integration_type: IntegrationType | None = None,
        status: IntegrationStatus | None = None,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[IntegrationRead]:
        if (
            type(skip) is not int
            or not 0 <= skip <= 10000
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValidationError("Paginación fuera del límite admitido")
        query = public_statement()
        if integration_type is not None:
            query = query.where(Integration.integration_type == integration_type)
        if status is not None:
            query = query.where(Integration.status == status)
        rows = (
            (
                await self.db.execute(
                    query.order_by(Integration.name, Integration.id)
                    .offset(skip)
                    .limit(limit)
                )
            )
            .mappings()
            .all()
        )
        return [public_summary(row) for row in rows]

    def _audit(
        self,
        actor: User | None,
        identifier: UUID,
        action: ActionType,
        old_values: dict[str, JsonValue] | None,
        new_values: dict[str, JsonValue],
    ) -> None:
        self.db.add(
            AuditLog(
                user_id=actor.id if actor else None,
                user_role=actor.role.value if actor and actor.role else None,
                action_type=action,
                resource_type="integration",
                resource_id=str(identifier),
                old_values=old_values,
                new_values=new_values,
                success=True,
                description="Cambio de metadatos del registro de integraciones",
                changes_summary=",".join(sorted(new_values)),
            )
        )

    async def create_integration(
        self,
        name: str,
        integration_type: IntegrationType,
        config: IntegrationConfig | None = None,
        enabled: bool = False,
        *,
        provider: str | None = None,
        sync_frequency_minutes: int = 60,
        actor: User | None = None,
    ) -> Integration:
        if enabled is not False:
            raise ValidationError(
                "La activación requiere un adaptador y una conexión verificados"
            )
        data = IntegrationCreate(
            name=name,
            integration_type=integration_type,
            provider=provider,
            sync_frequency_minutes=sync_frequency_minutes,
        )
        serialized = None
        if config is not None:
            if not isinstance(config, dict):
                raise ValidationError(
                    "La configuración interna debe ser un objeto JSON"
                )
            _, serialized = bounded_json(config)
        row = Integration(
            name=data.name,
            integration_type=data.integration_type,
            provider=data.provider,
            config=serialized,
            status=IntegrationStatus.INACTIVE,
            sync_enabled=False,
            sync_frequency_minutes=data.sync_frequency_minutes,
            created_by=actor.id if actor else None,
        )
        try:
            self.db.add(row)
            await self.db.flush()
            self._audit(
                actor,
                row.id,
                ActionType.CREATE,
                None,
                {
                    "name": row.name,
                    "integration_type": row.integration_type.value,
                    "provider": row.provider,
                    "status": "INACTIVE",
                    "sync_enabled": False,
                    "sync_frequency_minutes": row.sync_frequency_minutes,
                },
            )
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            raise
        await self.db.refresh(row)
        return row

    async def patch_metadata(
        self,
        integration_id: UUID,
        patch: IntegrationPatch,
        *,
        actor: User | None = None,
    ) -> IntegrationRead:
        try:
            before = await self.get_summary(integration_id, lock=True)
            if before is None:
                raise NotFoundError("Integración no encontrada")
            values = patch.model_dump(exclude_unset=True)
            if "sync_frequency_minutes" in values and (
                before.status != IntegrationStatus.INACTIVE
                or before.sync_enabled is not False
            ):
                raise AppException(
                    "Debe pausar la integración antes de cambiar la frecuencia", 409
                )
            old = {key: getattr(before, key) for key in values}
            if old != values:
                await self.db.execute(
                    update(Integration)
                    .where(Integration.id == integration_id)
                    .values(**values)
                )
                self._audit(
                    actor, integration_id, ActionType.CONFIG_CHANGE, old, values
                )
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            raise
        result = await self.get_summary(integration_id)
        assert result is not None
        return result

    async def pause(
        self, integration_id: UUID, *, actor: User | None = None
    ) -> IntegrationRead:
        try:
            before = await self.get_summary(integration_id, lock=True)
            if before is None:
                raise NotFoundError("Integración no encontrada")
            if (
                before.status != IntegrationStatus.INACTIVE
                or before.sync_enabled is not False
                or before.sync_next_run is not None
            ):
                await self.db.execute(
                    update(Integration)
                    .where(Integration.id == integration_id)
                    .values(
                        status=IntegrationStatus.INACTIVE,
                        sync_enabled=False,
                        sync_next_run=None,
                    )
                )
                self._audit(
                    actor,
                    integration_id,
                    ActionType.STATUS_CHANGE,
                    {
                        "status": before.status.value if before.status else None,
                        "sync_enabled": before.sync_enabled,
                        "sync_next_run": (
                            before.sync_next_run.isoformat()
                            if before.sync_next_run
                            else None
                        ),
                    },
                    {
                        "status": "INACTIVE",
                        "sync_enabled": False,
                        "sync_next_run": None,
                    },
                )
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            raise
        result = await self.get_summary(integration_id)
        assert result is not None
        return result

    async def update_integration_status(
        self, integration_id: UUID, status: IntegrationStatus
    ) -> Integration | None:
        if status != IntegrationStatus.INACTIVE:
            raise ValidationError(
                "La activación requiere un adaptador y una conexión verificados"
            )
        if await self.get_summary(integration_id) is None:
            return None
        await self.pause(integration_id)
        return await self.get_integration(integration_id)

    async def diagnostics(self, integration_id: UUID) -> IntegrationDiagnostic:
        summary = await self.get_summary(integration_id)
        if summary is None:
            raise NotFoundError("Integración no encontrada")
        reasons = ["verified_adapter_required"]
        if summary.status != IntegrationStatus.ACTIVE:
            reasons.append("registry_inactive")
        if summary.sync_enabled:
            reasons.append("legacy_sync_flag_requires_review")
        if not summary.has_endpoint and not summary.has_webhook:
            reasons.append("endpoint_not_recorded")
        if not summary.has_credentials:
            reasons.append("credentials_not_recorded")
        return IntegrationDiagnostic(
            integration_id=integration_id,
            status=summary.status,
            blocking_reasons=reasons,
        )

    async def test_connection(self, integration_id: UUID) -> TestConnectionResult:
        # A configured flag, a template URL, or a /health response is not proof
        # of a working, authenticated provider adapter. This performs no network IO.
        exists = await self.get_summary(integration_id)
        return {
            "success": False,
            "error": "verified_adapter_required" if exists else "not_found",
            "message": "No se realizó una prueba externa",
            "performed": False,
            "connection_verified": False,
        }

    async def sync_with_pos(self, order_data: POSOrderData) -> dict[str, Any]:
        return {
            "success": False,
            "error": "verified_adapter_required",
            "performed": False,
        }

    async def sync_with_erp(self, financial_data: ERPFinancialData) -> dict[str, Any]:
        return {
            "success": False,
            "error": "verified_adapter_required",
            "performed": False,
        }

    async def trigger_webhook(
        self, event_type: str, payload: WebhookPayload, webhook_url: str
    ) -> bool:
        # Outbound delivery needs durable event identity, endpoint policy, signing,
        # retries and provider evidence before this legacy service can send it.
        return False

    async def register_webhook_event(
        self,
        integration_id: UUID,
        event_type: str,
        payload: WebhookPayload,
        success: bool,
        response_code: int | None = None,
    ) -> WebhookEvent:
        require_uuid(integration_id)
        if success is not False:
            raise ValidationError(
                "El éxito externo requiere evidencia verificable del proveedor"
            )
        try:
            kind = WebhookEventType(event_type)
        except ValueError:
            raise ValidationError("Tipo de evento no admitido") from None
        if response_code is not None and (
            type(response_code) is not int or not 100 <= response_code <= 599
        ):
            raise ValidationError("Código HTTP inválido")
        clean, _ = bounded_json(payload)
        try:
            # Lock the parent, as registry updates do; retain FK/history and avoid
            # racing a future archival process. This is an internal failure record.
            if await self.get_summary(integration_id, lock=True) is None:
                raise NotFoundError("Integración no encontrada")
            event = WebhookEvent(
                integration_id=integration_id,
                event_type=kind,
                payload=clean,
                success=False,
                response_code=response_code,
                triggered_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            self.db.add(event)
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            raise
        await self.db.refresh(event)
        return event


def get_integration_service(db: AsyncSession) -> IntegrationService:
    return IntegrationService(db)
