"""Install real notification tables in otherwise minimal ledger test schemas."""

from sqlalchemy import inspect, text
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
        NotificationLog,
        NotificationTemplate,
        NotificationPreference,
        UserDeviceToken,
    ):
        if connection.dialect.name == "postgresql":
            for column in model.__table__.columns:
                if hasattr(column.type, "create"):
                    column.type.create(connection, checkfirst=True)
        model.__table__.create(connection, checkfirst=True)
