# Informe maestro de mejoras y alineación del repositorio

## Propósito

Este documento sirve como guía maestra para continuar el trabajo en un entorno nuevo y limpio. Resume el estado esperado del sistema, los cambios críticos implementados, los archivos que deben verificarse y el orden recomendado para reparar/alinear el repositorio remoto antes de seguir agregando nuevas funcionalidades.

La prioridad inmediata es estabilizar y alinear el módulo financiero, payouts, zonas y vehículos con la versión correcta y compilable, evitando conflictos de GitHub y mezclas parciales de código.

## Contexto del problema

Durante el trabajo anterior se implementaron mejoras grandes en varias áreas:

- Zonas operativas como entidad real de base de datos, API y frontend.
- Endurecimiento del módulo de vehículos y corrección de conflictos de rutas que causaban errores 422.
- Finanzas manager: resumen, transacciones, payouts y reportes reales.
- Finanzas rider: ganancias, solicitud de retiro e historial de payouts.
- Conciliación financiera y trazabilidad de saldos/payouts.

Sin embargo, al resolver conflictos directamente en GitHub, algunos archivos pudieron quedar mezclados o parcialmente alineados. Por eso, antes de seguir con nuevas mejoras, debe crearse un entorno limpio, clonar `main`, verificar los archivos críticos y restaurar la versión coherente si falta algún bloque.

## Repositorio remoto y rama base

Repositorio remoto:

```bash
https://github.com/corporacionbethelst-ux/Delivery_360-DEV.git
```

Rama base actual:

```bash
main
```

## Flujo recomendado en un entorno nuevo

### 1. Clonar el repositorio limpio

```bash
git clone https://github.com/corporacionbethelst-ux/Delivery_360-DEV.git
cd Delivery_360-DEV
git checkout main
git pull origin main
```

### 2. Crear una rama exclusiva de reparación/alineación

No trabajar directamente sobre `main`.

```bash
git checkout -b fix/financial-alignment
```

### 3. Confirmar estado inicial

```bash
git status --short
git log --oneline -5
```

El árbol debe estar limpio antes de reparar.

## Archivos críticos que deben verificarse

Los archivos más importantes para revisar son:

```text
backend/app/api/v1/financial.py
backend/app/api/v1/payouts.py
backend/app/models/financial.py
backend/app/models/payout.py
backend/app/models/__init__.py
backend/app/models/all_models.py
backend/alembic/versions/a617d286d3d0_initial_schema_complete.py
frontend/src/services/financial.service.ts
frontend/src/services/payout.service.ts
frontend/src/app/(dashboard)/manager/financial/reports/page.tsx
frontend/src/app/(dashboard)/manager/financial/payouts/[id]/page.tsx
frontend/src/app/(dashboard)/rider/earnings/page.tsx
```

## Qué debe existir en cada archivo

### 1. `backend/app/api/v1/financial.py`

Debe contener el endpoint de desglose auditable de ganancias del rider:

```python
@router.get("/riders/me/earnings")
async def get_my_earnings_breakdown(...):
```

Este endpoint debe:

- validar que el usuario sea `REPARTIDOR`;
- resolver el `Rider` del usuario autenticado;
- permitir filtros por `type`, `date_from`, `date_to`, `limit` y `offset`;
- devolver `items` serializados con `_serialize_transaction`.

También debe contener el endpoint de conciliación financiera gerencial:

```python
@router.get("/reconciliation")
async def get_financial_reconciliation(...):
```

Este endpoint debe calcular:

- `gross_order_value`;
- `delivery_revenue`;
- `completed_orders`;
- `ledger_transactions`;
- `rider_earnings`;
- `rider_deductions`;
- `adjustments`;
- `net_rider_liability`;
- `pending_payouts`;
- `processed_payouts`;
- `rejected_payouts`;
- `available_liability`;
- `total_costs`;
- `net_margin_after_rider_costs`;
- `payout_count`.

La función `_serialize_transaction` debe incluir:

```python
"balance_before"
"balance_after"
"source_type"
"source_id"
"idempotency_key"
"created_by_user_id"
```

Debe existir conversión monetaria segura con `Decimal`, por ejemplo:

```python
def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _float_money(value) -> float:
    return float(_money(value))
```

### 2. `backend/app/api/v1/payouts.py`

Debe importar:

```python
from app.models.payout import Payout, PayoutStatus, PayoutMethod, PayoutStatusHistory
```

`PayoutRequestBody` debe aceptar:

```python
idempotency_key: Optional[str] = Field(None, max_length=100)
```

Debe existir serializador de historial:

```python
def _serialize_status_history(row: PayoutStatusHistory):
```

Debe existir función para registrar historial:

```python
def _add_status_history(...):
```

La solicitud de payout debe:

- validar rol `REPARTIDOR`;
- resolver rider autenticado;
- respetar `idempotency_key` si viene;
- calcular saldo disponible con `Decimal`;
- validar monto máximo y mínimo;
- crear `Payout` con `balance_before`, `balance_after`, `requested_by_user_id` e `idempotency_key`;
- registrar historial inicial con `PayoutStatusHistory`.

La aprobación de payout debe:

- usar `with_for_update()` para bloquear la fila;
- permitir aprobar solo si está `PENDIENTE`;
- recalcular saldo disponible excluyendo el payout actual;
- validar saldo antes de aprobar;
- actualizar `balance_before`, `balance_after`, `processed_by_user_id`, `processed_at`, `reference_code`;
- crear una transacción financiera `RETIRO` con trazabilidad;
- registrar historial de estado.

Debe existir:

```python
@router.get("/{payout_id}/history")
async def get_payout_history(...):
```

### 3. `backend/app/models/financial.py`

El modelo `Financial` debe tener estos campos:

```python
balance_before = Column(Numeric(10, 2), default=0.0)
balance_after = Column(Numeric(10, 2), default=0.0)
source_type = Column(String(50), index=True)
source_id = Column(String(100), index=True)
idempotency_key = Column(String(100), unique=True, index=True)
created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
```

Estos campos permiten trazabilidad y conciliación.

### 4. `backend/app/models/payout.py`

El modelo `Payout` debe tener:

```python
idempotency_key = Column(String(100), unique=True, nullable=True, index=True)
balance_before = Column(Numeric(10, 2), nullable=True)
balance_after = Column(Numeric(10, 2), nullable=True)
requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
processed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
status_history = relationship("PayoutStatusHistory", back_populates="payout", cascade="all, delete-orphan", order_by="PayoutStatusHistory.created_at")
```

También debe existir el modelo:

```python
class PayoutStatusHistory(Base):
```

con campos:

```python
payout_id
old_status
new_status
reason
changed_by_user_id
balance_before
balance_after
created_at
```

### 5. `backend/app/models/__init__.py` y `backend/app/models/all_models.py`

Deben importar/exportar:

```python
Payout
PayoutStatus
PayoutMethod
PayoutStatusHistory
```

Esto asegura que SQLAlchemy registre los modelos.

### 6. Migración Alembic `a617d286d3d0_initial_schema_complete.py`

Debe incluir en `financials`:

```python
balance_before
balance_after
source_type
source_id
idempotency_key
created_by_user_id
```

Debe incluir índices para:

```python
ix_financials_created_by_user_id
ix_financials_idempotency_key
ix_financials_source_id
ix_financials_source_type
```

Debe incluir en `payouts`:

```python
idempotency_key
balance_before
balance_after
requested_by_user_id
processed_by_user_id
updated_at
```

Debe crear tabla:

```python
payout_status_history
```

con sus índices, incluyendo:

```python
idx_payout_status_history_payout_date
```

En `downgrade()` debe eliminar primero `payout_status_history`, luego `payouts`, respetando orden inverso.

> Nota profesional: para producción real es mejor crear una migración incremental nueva, por ejemplo `add_financial_traceability.py`, en vez de modificar una migración inicial ya aplicada. Si la base aún está en fase temprana y la migración inicial no se ha aplicado en producción, puede mantenerse así temporalmente.

### 7. `frontend/src/services/financial.service.ts`

Debe tener interfaces:

```ts
FinancialTransaction
RiderEarningsBreakdown
FinancialReconciliation
RiderEarningsBreakdownParams
```

Debe tener método:

```ts
getMyEarningsBreakdown()
```

que llame:

```ts
/financial/riders/me/earnings
```

Debe tener método:

```ts
getReconciliation()
```

que llame:

```ts
/financial/reconciliation
```

### 8. `frontend/src/services/payout.service.ts`

La interfaz `Payout` debe incluir:

```ts
balance_before?: number | null;
balance_after?: number | null;
requested_by_user_id?: string | null;
processed_by_user_id?: string | null;
idempotency_key?: string | null;
```

Debe existir:

```ts
export interface PayoutStatusHistory
```

Debe existir función:

```ts
buildIdempotencyKey()
```

`requestPayout()` debe enviar una llave idempotente cuando no venga una explícita.

Debe existir método:

```ts
getHistory(id: string)
```

que llame:

```ts
/payouts/${payoutId}/history
```

### 9. `frontend/src/app/(dashboard)/manager/financial/reports/page.tsx`

Debe importar:

```ts
FinancialReconciliation
```

desde `financial.service.ts`.

Debe tener estado:

```ts
const [reconciliation, setReconciliation] = useState<FinancialReconciliation | null>(null);
```

`loadReport()` debe cargar en paralelo:

```ts
financialService.getOrdersReport(...)
financialService.getReconciliation(...)
```

Debe mostrar panel visual:

```text
Conciliación Financiera
```

con métricas de ganancias riders, retiros pendientes/procesados, pasivo disponible, transacciones ledger y solicitudes payout.

### 10. `frontend/src/app/(dashboard)/manager/financial/payouts/[id]/page.tsx`

Debe importar:

```ts
PayoutStatusHistory
```

Debe tener estado:

```ts
const [history, setHistory] = useState<PayoutStatusHistory[]>([]);
```

Debe cargar payout e historial:

```ts
const [data, historyData] = await Promise.all([
  payoutService.getById(payoutId),
  payoutService.getHistory(payoutId),
]);
```

Debe mostrar sección:

```text
Trazabilidad y Conciliación
```

con saldo antes/después e historial de estados.

### 11. `frontend/src/app/(dashboard)/rider/earnings/page.tsx`

Debe importar:

```ts
FinancialTransaction
```

Debe tener estado:

```ts
const [recentMovements, setRecentMovements] = useState<FinancialTransaction[]>([]);
```

Debe cargar:

```ts
financialService.getMyEarnings()
payoutService.getAvailableBalance()
financialService.getMyEarningsBreakdown({ limit: 5 })
```

Debe mostrar bloque:

```text
Últimos movimientos financieros
```

con descripción, tipo, fecha, monto y saldo posterior.

## Comandos de verificación obligatorios

Después de reparar o alinear, ejecutar:

```bash
git diff --check
```

```bash
python -m py_compile backend/app/api/v1/financial.py backend/app/api/v1/payouts.py backend/app/models/financial.py backend/app/models/payout.py backend/alembic/versions/a617d286d3d0_initial_schema_complete.py
```

Para frontend financiero:

```bash
cd frontend && npm run type-check -- --pretty false 2>&1 | rg "financial.service|payout.service|financial/reports|rider/earnings|manager/financial/payouts"
```

Este comando no debe devolver errores relacionados con esos archivos.

El type-check global puede fallar por errores preexistentes fuera de Finanzas, especialmente:

- globals de Jest;
- deliveries;
- riders/shifts;
- `order-cache.service`.

## Comandos rápidos de búsqueda para confirmar alineación

```bash
rg -n "get_financial_reconciliation|/reconciliation|balance_before|source_type|get_my_earnings_breakdown" backend/app/api/v1/financial.py
```

```bash
rg -n "PayoutStatusHistory|idempotency_key|with_for_update|get_payout_history|/history" backend/app/api/v1/payouts.py
```

```bash
rg -n "FinancialReconciliation|getReconciliation|getMyEarningsBreakdown" frontend/src/services/financial.service.ts
```

```bash
rg -n "PayoutStatusHistory|getHistory|buildIdempotencyKey" frontend/src/services/payout.service.ts
```

## Orden de reparación recomendado

### Prioridad 1: Backend runtime

1. `backend/app/api/v1/financial.py`
2. `backend/app/api/v1/payouts.py`
3. `backend/app/models/financial.py`
4. `backend/app/models/payout.py`
5. `backend/alembic/versions/a617d286d3d0_initial_schema_complete.py`

### Prioridad 2: Servicios frontend

6. `frontend/src/services/financial.service.ts`
7. `frontend/src/services/payout.service.ts`

### Prioridad 3: Pantallas frontend

8. `frontend/src/app/(dashboard)/manager/financial/reports/page.tsx`
9. `frontend/src/app/(dashboard)/manager/financial/payouts/[id]/page.tsx`
10. `frontend/src/app/(dashboard)/rider/earnings/page.tsx`

## Qué no hacer

No usar automáticamente:

```text
Accept both change
```

en archivos grandes de backend o servicios frontend. Puede duplicar funciones, endpoints, imports, interfaces o estados React.

No continuar con módulos nuevos hasta que Finanzas esté alineado y compilable.

No tocar todavía:

- auditoría;
- dashboard;
- deliveries;
- riders;
- shifts;
- rutas;
- integraciones;
- notificaciones.

## Próximas mejoras después de alinear Finanzas

Cuando la alineación esté completa, los siguientes bloques de trabajo recomendados son:

1. Crear tests backend específicos de Finanzas y Payouts.
2. Crear migración incremental para trazabilidad financiera si el entorno ya tiene bases migradas.
3. Resolver errores globales de TypeScript fuera de Finanzas.
4. Continuar con otro módulo funcional del sistema.

## Tests financieros recomendados

Crear o reforzar pruebas para:

- rider no puede ver payouts de otro rider;
- rider no puede retirar más que su saldo disponible;
- payout menor al mínimo falla;
- aprobar payout crea transacción `RETIRO`;
- aprobar dos veces el mismo payout falla;
- rechazar payout libera reserva de saldo;
- `/payouts/{id}/history` devuelve movimientos;
- `/financial/reconciliation` cuadra ingresos, costos, pasivos y margen;
- `/financial/riders/me/earnings` solo devuelve movimientos del rider autenticado.

## Checklist final para PR de reparación

```bash
git status --short
```

```bash
git diff --check
```

```bash
python -m py_compile backend/app/api/v1/financial.py backend/app/api/v1/payouts.py backend/app/models/financial.py backend/app/models/payout.py backend/alembic/versions/a617d286d3d0_initial_schema_complete.py
```

```bash
cd frontend && npm run type-check -- --pretty false 2>&1 | rg "financial.service|payout.service|financial/reports|rider/earnings|manager/financial/payouts"
```

Si todo está bien:

```bash
git add .
git commit -m "Align financial reconciliation and payout traceability"
git push origin fix/financial-alignment
```

Abrir PR hacia `main`.

## Resumen ejecutivo

Antes de continuar con nuevas mejoras, el nuevo entorno debe usar este documento como guía para verificar que el remoto `main` tenga correctamente alineadas las mejoras de:

- conciliación financiera;
- trazabilidad de ledger;
- historial de payouts;
- idempotencia;
- reportes manager;
- últimos movimientos financieros del rider;
- modelos y migración relacionados.

Cuando eso esté estable, se puede continuar con el siguiente módulo del sistema.
