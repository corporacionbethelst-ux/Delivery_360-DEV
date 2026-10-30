"""Canonical API modules. Required feature import failures must stop startup."""

from fastapi import APIRouter
from . import auth
from . import orders
from . import riders
from . import telemetry
from . import tracking
from . import users
from . import roles
from . import audit
from . import settings
from . import deliveries
from . import alerts
from . import vehicles
from . import zones
from . import financial
from . import shifts
from . import reconciliation
from . import productivity
from . import routes
from . import dashboard
from . import integrations
from . import payouts
from . import wallet
from . import notifications
from . import fiscal

_API_MODULES = (
    auth,
    orders,
    riders,
    telemetry,
    tracking,
    users,
    roles,
    audit,
    settings,
    deliveries,
    alerts,
    vehicles,
    zones,
    financial,
    shifts,
    reconciliation,
    productivity,
    routes,
    dashboard,
    integrations,
    payouts,
    wallet,
    notifications,
    fiscal,
)

for _module in _API_MODULES:
    _router = getattr(_module, "router", None)
    if not isinstance(_router, APIRouter) or not _router.routes:
        raise RuntimeError(
            f"Required API module has no populated APIRouter: {_module.__name__}"
        )

__all__ = [_module.__name__.rsplit(".", 1)[-1] for _module in _API_MODULES]
