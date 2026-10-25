"""SQLite DDL accommodation only; production defaults remain unchanged."""

from app.models.audit_log import AuditLog


async def create_sqlite_audit_table(db):
    connection = await db.connection()
    previous = AuditLog.__table__.c.id.server_default
    try:
        AuditLog.__table__.c.id.server_default = None
        await connection.run_sync(
            lambda conn: AuditLog.__table__.create(conn, checkfirst=True)
        )
    finally:
        AuditLog.__table__.c.id.server_default = previous
