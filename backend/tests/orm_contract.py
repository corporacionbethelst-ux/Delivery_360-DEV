"""Structural contract for mappings changed without a database migration."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, CreateIndex
from app.core.database import Base

TABLES = (
    "users",
    "rider_wallets",
    "financial_transactions",
    "payout_requests",
    "financials",
)


def mapping_contract():
    dialect = postgresql.dialect()
    contract = {}
    for name in TABLES:
        table = Base.metadata.tables[name]
        defaults = {}
        for column in table.columns:
            args = []
            for value in (column.default, column.onupdate):
                if value is None:
                    args.append(None)
                elif callable(value.arg):
                    args.append(value.arg.__qualname__)
                else:
                    args.append(str(value.arg))
            defaults[column.name] = args
        contract[name] = {
            "ddl": str(CreateTable(table).compile(dialect=dialect)),
            "indexes": sorted(
                str(CreateIndex(index).compile(dialect=dialect))
                for index in table.indexes
            ),
            "defaults": defaults,
            "enums": {
                column.name: list(column.type.enums)
                for column in table.columns
                if hasattr(column.type, "enums")
            },
        }
    return contract
