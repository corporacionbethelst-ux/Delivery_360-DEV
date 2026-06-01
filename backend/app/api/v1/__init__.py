from app.api.v1 import auth
from app.api.v1 import orders
from app.api.v1 import riders
# 1. Importar módulos reales explícitos
from app.api.v1 import deliveries as deliveries_module
from app.api.v1 import alerts as alerts_module
from app.api.v1 import vehicles as vehicles_module # Importar el nuevo módulo correctamente

# 2. Importar solo lo necesario de routers_combined para los otros módulos
from app.api.v1.routers_combined import (
    shifts_router,
    financial_router,
    productivity_router, 
    routes_router,
    dashboard_router,
    integrations_router,
    users_router,
)

# 3. Manejo seguro de payouts (si existe)
try:
    from app.api.v1 import payouts as payouts_module
except ImportError:
    from app.api.v1.routers_combined import payouts_router
    import types
    payouts_module = types.ModuleType("payouts")
    payouts_module.router = payouts_router

import types

# Función auxiliar para crear módulos ficticios
def _make_module(router_obj, name):
    m = types.ModuleType(name)
    m.router = router_obj
    return m

# 4. ASIGNACIÓN CORREGIDA
deliveries = deliveries_module
alerts = alerts_module
vehicles = vehicles_module # <--- ASIGNAR EL MÓDULO REAL DE VEHÍCULOS AQUÍ

# Los demás siguen siendo wrappers hacia routers_combined
shifts       = _make_module(shifts_router,        "shifts")
financial    = _make_module(financial_router,     "financial")
productivity = _make_module(productivity_router,  "productivity")
routes       = _make_module(routes_router,        "routes")
dashboard    = _make_module(dashboard_router,     "dashboard")
integrations = _make_module(integrations_router,  "integrations")
users        = _make_module(users_router,         "users")

# Payouts
if not hasattr(payouts_module, 'router'):
    payouts = _make_module(payouts_router, "payouts")
else:
    payouts = payouts_module

__all__ = [
    "auth",
    "orders",
    "riders",
    "payouts",
    "deliveries",
    "alerts",
    "vehicles", # <--- ASEGURAR QUE ESTÉ EN LA LISTA
    "shifts",
    "financial",
    "productivity",
    "routes",
    "dashboard",
    "integrations",
    "users"
]