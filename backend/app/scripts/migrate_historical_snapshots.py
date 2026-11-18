"""Retired backfill: history must never be repriced from current settings.

New snapshots are written by canonical delivery closures. Existing amounts and
unknown units are preserved by migration 20261117_bonus_currency. This module
intentionally opens no database connection and never displays a database URL.
"""

import sys

MESSAGE = (
    "Operación retirada: no se recalculan bonos históricos desde configuración actual. "
    "Conserva los snapshots existentes y su moneda desconocida; revisa las "
    "inconsistencias sin modificar el historial."
)


async def migrate_historical_snapshots():
    raise RuntimeError(MESSAGE)


if __name__ == "__main__":
    print(MESSAGE, file=sys.stderr)
    raise SystemExit(2)
