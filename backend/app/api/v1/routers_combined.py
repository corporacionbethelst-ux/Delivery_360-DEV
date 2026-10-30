"""Compatibility imports for canonical routers; no alternative endpoint handlers.

The application mounts canonical modules directly. Importing this module must
never activate an older implementation when a required API module fails.
"""

from app.api.v1.deliveries import router as deliveries_router
from app.api.v1.shifts import router as shifts_router
from app.api.v1.financial import router as financial_router
from app.api.v1.productivity import router as productivity_router
from app.api.v1.routes import router as routes_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.alerts import router as alerts_router
from app.api.v1.audit import router as audit_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.users import router as users_router
from app.api.v1.payouts import router as payouts_router

__all__ = [
    "deliveries_router",
    "shifts_router",
    "financial_router",
    "productivity_router",
    "routes_router",
    "dashboard_router",
    "alerts_router",
    "audit_router",
    "integrations_router",
    "users_router",
    "payouts_router",
]
