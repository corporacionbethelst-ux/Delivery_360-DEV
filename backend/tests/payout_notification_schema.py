"""Install real notification tables in otherwise minimal ledger test schemas."""

from sqlalchemy import inspect, text, MetaData
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.notification import (
    NotificationLog,
    NotificationTemplate,
    NotificationPreference,
    UserDeviceToken,
)


def create_payout_notification_schema(connection):
    if not inspect(connection).has_table("deliveries"):
        connection.execute(text("CREATE TABLE deliveries (id UUID PRIMARY KEY)"))
    for model in (
        AuditLog,
        NotificationLog,
        NotificationTemplate,
        NotificationPreference,
        UserDeviceToken,
    ):
        if connection.dialect.name == "postgresql":
            for column in model.__table__.columns:
                if hasattr(column.type, "create"):
                    column.type.create(connection, checkfirst=True)
        if model is AuditLog and connection.dialect.name == "sqlite":
            # PostgreSQL's UUID server default is not valid SQLite DDL. Adapt
            # only a disposable copy; never mutate production ORM metadata.
            metadata = MetaData()
            User.__table__.to_metadata(metadata)
            table = AuditLog.__table__.to_metadata(metadata)
            table.c.id.server_default = None
            table.create(connection, checkfirst=True)
        else:
            model.__table__.create(connection, checkfirst=True)
