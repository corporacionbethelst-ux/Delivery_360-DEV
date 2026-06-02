# 📚 API Documentation - Delivery360

## Descripción General

Esta documentación describe todos los endpoints de la API REST de Delivery360, organizada por módulos funcionales.

**Base URL**: `http://localhost:8000/api/v1`

**Autenticación**: Todos los endpoints (excepto login/registro) requieren header `Authorization: Bearer <token>`

---

## 🔐 Módulo de Autenticación

### `POST /auth/login`
Inicia sesión y obtiene tokens JWT.

**Request Body:**
```json
{
  "username": "usuario@ejemplo.com",
  "password": "contraseña123"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### `POST /auth/register`
Registra un nuevo repartidor.

**Request Body:**
```json
{
  "email": "rider@ejemplo.com",
  "password": "contraseña123",
  "first_name": "Juan",
  "last_name": "Pérez",
  "phone": "+573001234567",
  "role": "REPARTIDOR"
}
```

### `POST /auth/refresh`
Refresca el token de acceso usando el refresh token.

**Headers:** `Authorization: Bearer <refresh_token>`

### `POST /auth/recovery`
Solicita recuperación de contraseña por email.

**Request Body:**
```json
{
  "email": "usuario@ejemplo.com"
}
```

### `POST /auth/reset-password`
Restablece contraseña con token válido.

**Request Body:**
```json
{
  "token": "token_recibido_en_email",
  "new_password": "nuevaContraseña123"
}
```

### `GET /auth/me`
Obtiene información del usuario autenticado.

**Headers:** `Authorization: Bearer <access_token>`

**Response:**
```json
{
  "id": "uuid",
  "email": "usuario@ejemplo.com",
  "first_name": "Juan",
  "last_name": "Pérez",
  "role": "GERENTE",
  "is_active": true,
  "avatar_url": "https://..."
}
```

---

## 👥 Módulo de Usuarios

### `GET /users`
Lista todos los usuarios (solo SUPERADMIN, GERENTE).

**Query Params:**
- `skip`: int (default 0)
- `limit`: int (default 100)
- `role`: UserRole (opcional)
- `is_active`: bool (opcional)

### `GET /users/{user_id}`
Obtiene detalles de un usuario específico.

### `PUT /users/{user_id}`
Actualiza información de un usuario.

**Request Body:**
```json
{
  "first_name": "Carlos",
  "last_name": "López",
  "phone": "+573009876543"
}
```

### `DELETE /users/{user_id}`
Desactiva un usuario (soft delete).

---

## 🚴 Módulo de Repartidores

### `GET /riders`
Lista repartidores con filtros.

**Query Params:**
- `status`: RiderStatus (PENDIENTE, ACTIVO, INACTIVO, OCUPADO, SUSPENDIDO)
- `vehicle_type`: VehicleType (MOTO, BICICLETA, etc.)
- `skip`, `limit`: paginación

### `GET /riders/{rider_id}`
Obtiene perfil completo de repartidor incluyendo:
- Información personal
- Vehículo asignado
- Documentos
- Métricas de productividad
- Historial de entregas

### `POST /riders`
Crea perfil de repartidor (vinculado a usuario existente).

**Request Body:**
```json
{
  "user_id": "uuid-del-usuario",
  "vehicle_type": "MOTO",
  "vehicle_plate": "ABC123",
  "vehicle_model": "Honda CG 160",
  "vehicle_color": "Rojo",
  "license_number": "123456789",
  "license_expiry": "2025-12-31"
}
```

### `PUT /riders/{rider_id}/status`
Actualiza estado del repartidor.

**Request Body:**
```json
{
  "status": "ACTIVO"
}
```

### `GET /riders/{rider_id}/productivity`
Obtiene métricas de productividad del repartidor.

### `GET /riders/nearby`
Obtiene repartidores cercanos a una ubicación.

**Query Params:**
- `lat`: float (requerido)
- `lng`: float (requerido)
- `radius_km`: float (default 5.0)
- `status`: RiderStatus (default ACTIVO)

---

## 🚗 Módulo de Vehículos

### `GET /vehicles`
Lista vehículos de la flota.

**Query Params:**
- `status`: VehicleStatus (ACTIVO, MANTENIMIENTO, BAJA)
- `type`: VehicleType
- `rider_id`: uuid (filtrar por dueño)

### `GET /vehicles/{vehicle_id}`
Obtiene detalles de un vehículo.

### `POST /vehicles`
Registra nuevo vehículo.

**Request Body:**
```json
{
  "rider_id": "uuid-del-dueño",
  "type": "MOTO",
  "plate": "XYZ789",
  "model": "Yamaha MT-03",
  "color": "Azul",
  "year": 2022,
  "insurance_expiry": "2025-06-30"
}
```

### `PUT /vehicles/{vehicle_id}`
Actualiza información del vehículo.

### `DELETE /vehicles/{vehicle_id}`
Da de baja un vehículo.

---

## 📦 Módulo de Órdenes

### `GET /orders`
Lista órdenes con filtros.

**Query Params:**
- `status`: OrderStatus (PENDIENTE, ASIGNADO, EN_RECOLECCION, EN_RUTA, ENTREGADO, CANCELADO)
- `priority`: OrderPriority (NORMAL, ALTA, URGENTE)
- `customer_id`: uuid
- `date_from`, `date_to`: datetime
- `skip`, `limit`: paginación

### `GET /orders/{order_id}`
Obtiene detalles completos de una orden.

### `POST /orders`
Crea nueva orden de delivery.

**Request Body:**
```json
{
  "customer_id": "uuid-cliente",
  "restaurant_name": "Burger King",
  "restaurant_address": "Cra 4 #85-10",
  "restaurant_lat": 4.668,
  "restaurant_lng": -74.050,
  "delivery_address": "Cll 93B #13-30",
  "delivery_lat": 4.676,
  "delivery_lng": -74.047,
  "items": [
    {
      "product_name": "Whopper Doble",
      "quantity": 2,
      "unit_price": 28000,
      "total_price": 56000
    }
  ],
  "subtotal": 56000,
  "delivery_fee": 5000,
  "total": 61000,
  "priority": "NORMAL",
  "sla_minutes": 60,
  "notes": "Timbre no funciona, llamar al llegar"
}
```

### `PUT /orders/{order_id}/assign`
Asigna repartidor a una orden.

**Request Body:**
```json
{
  "rider_id": "uuid-repartidor"
}
```

### `PUT /orders/{order_id}/status`
Actualiza estado de la orden.

**Request Body:**
```json
{
  "status": "EN_RECOLECCION"
}
```

### `DELETE /orders/{order_id}`
Cancela una orden (solo si está PENDIENTE o ASIGNADO).

---

## 🚚 Módulo de Entregas

### `GET /deliveries`
Lista entregas activas e históricas.

**Query Params:**
- `status`: DeliveryStatus
- `rider_id`: uuid
- `order_id`: uuid
- `skip`, `limit`: paginación

### `GET /deliveries/{delivery_id}`
Obtiene detalles de entrega con tracking.

### `POST /deliveries`
Crea entrega vinculada a orden.

**Request Body:**
```json
{
  "order_id": "uuid-orden",
  "rider_id": "uuid-repartidor",
  "estimated_pickup_time": "2024-01-15T14:30:00",
  "estimated_delivery_time": "2024-01-15T15:00:00"
}
```

### `PUT /deliveries/{delivery_id}/tracking`
Actualiza ubicación GPS del repartidor.

**Request Body:**
```json
{
  "lat": 4.6732,
  "lng": -74.0485,
  "speed_kmh": 25.5,
  "battery_level": 75
}
```

### `POST /deliveries/{delivery_id}/complete`
Marca entrega como completada con prueba.

**Request Body:**
```json
{
  "proof_type": "FOTO",
  "photo_url": "https://storage.../foto.jpg",
  "signature": "firma_base64_opcional",
  "otp_code": "1234_opcional",
  "notes": "Entregado en portería"
}
```

### `POST /deliveries/{delivery_id}/fail`
Reporta entrega fallida.

**Request Body:**
```json
{
  "reason": "CLIENTE_NO_ESTABA",
  "notes": "Cliente no contestó teléfono"
}
```

---

## 💰 Módulo Financiero

### `GET /financial`
Lista transacciones financieras.

**Query Params:**
- `rider_id`: uuid
- `type`: TransactionType (PAGO_ENTREGA, BONO, DESCUENTO, AJUSTE, RETIRO)
- `status`: PaymentStatus (PENDIENTE, PROCESADO, CANCELADO)
- `date_from`, `date_to`: datetime

### `GET /financial/{transaction_id}`
Obtiene detalles de transacción.

### `POST /financial`
Registra nueva transacción.

**Request Body:**
```json
{
  "rider_id": "uuid-repartidor",
  "type": "PAGO_ENTREGA",
  "amount": 5000,
  "description": "Pago entrega #ORD-12345",
  "reference_id": "uuid-entrega"
}
```

### `GET /riders/{rider_id}/wallet`
Obtiene balance de billetera del repartidor.

**Response:**
```json
{
  "wallet_balance": 150000.00,
  "pending_balance": 25000.00,
  "total_earned": 2500000.00,
  "currency": "COP"
}
```

---

## 💸 Módulo de Pagos (Payouts)

### `GET /payouts`
Lista solicitudes de retiro.

**Query Params:**
- `rider_id`: uuid
- `status`: PayoutStatus (PENDIENTE, APROBADO, RECHAZADO, PROCESADO)
- `method`: PayoutMethod (TRANSFERENCIA, EFECTIVO, BILLETERA_DIGITAL)

### `POST /payouts`
Solicita retiro de fondos.

**Request Body:**
```json
{
  "rider_id": "uuid-repartidor",
  "amount": 100000,
  "method": "TRANSFERENCIA",
  "bank_account": "1234567890",
  "bank_name": "Bancolombia"
}
```

### `PUT /payouts/{payout_id}/approve`
Aprueba retiro (solo GERENTE, SUPERADMIN).

### `PUT /payouts/{payout_id}/reject`
Rechaza retiro con justificación.

**Request Body:**
```json
{
  "reason": "Saldo insuficiente verificado"
}
```

---

## ⏱️ Módulo de Turnos (Shifts)

### `GET /shifts`
Lista turnos programados.

**Query Params:**
- `rider_id`: uuid
- `date`: date
- `status`: SHIFT_ACTIVO, SHIFT_FINALIZADO

### `POST /shifts`
Programa nuevo turno.

**Request Body:**
```json
{
  "rider_id": "uuid-repartidor",
  "start_time": "2024-01-15T08:00:00",
  "end_time": "2024-01-15T16:00:00"
}
```

### `POST /shifts/{shift_id}/checkin`
Registro de entrada con geolocalización.

**Request Body:**
```json
{
  "lat": 4.6732,
  "lng": -74.0485
}
```

### `POST /shifts/{shift_id}/checkout`
Registro de salida.

---

## 📊 Módulo de Productividad

### `GET /productivity/{rider_id}`
Obtiene métricas de productividad de un repartidor.

**Response:**
```json
{
  "rider_id": "uuid",
  "total_deliveries": 150,
  "completed_deliveries": 145,
  "failed_deliveries": 5,
  "average_delivery_time_minutes": 28.5,
  "average_rating": 4.7,
  "total_earnings": 2500000,
  "level": 5,
  "badges": ["RAPIDO", "PUNTUAL", "EXCELENTE"]
}
```

### `GET /productivity/ranking`
Obtiene ranking de repartidores.

**Query Params:**
- `period`: day, week, month
- `limit`: int (default 10)

---

## 🗺️ Módulo de Rutas

### `GET /routes/{delivery_id}`
Obtiene ruta planificada para una entrega.

### `POST /routes`
Planifica nueva ruta optimizada.

**Request Body:**
```json
{
  "delivery_id": "uuid-entrega",
  "waypoints": [
    {"lat": 4.6732, "lng": -74.0485},
    {"lat": 4.6750, "lng": -74.0500}
  ]
}
```

### `GET /routes/{delivery_id}/deviations`
Detecta desviaciones de ruta planificada.

---

## 🔔 Módulo de Alertas

### `GET /alerts`
Lista alertas operacionales.

**Query Params:**
- `severity`: AlertSeverity (LOW, MEDIUM, HIGH, CRITICAL)
- `status`: ACTIVE, RESOLVED
- `type`: AlertType

### `POST /alerts`
Crea nueva alerta.

**Request Body:**
```json
{
  "type": "RETRASO_SLA",
  "severity": "HIGH",
  "delivery_id": "uuid-entrega",
  "title": "Entrega retrasada",
  "description": "La entrega supera el SLA en 15 minutos"
}
```

### `PUT /alerts/{alert_id}/resolve`
Marca alerta como resuelta.

**Request Body:**
```json
{
  "resolution_notes": "Rider contactado, llegará en 5 minutos"
}
```

---

## 📬 Módulo de Notificaciones

### `GET /notifications`
Obtiene notificaciones del usuario autenticado.

### `POST /notifications`
Envía notificación (solo staff).

**Request Body:**
```json
{
  "user_id": "uuid-destinatario",
  "type": "INFO",
  "priority": "HIGH",
  "title": "Nueva orden asignada",
  "message": "Tienes una nueva orden pendiente de recolección"
}
```

### `PUT /notifications/{notification_id}/read`
Marca notificación como leída.

---

## 📈 Dashboard

### `GET /dashboard/stats`
Obtiene estadísticas generales según rol del usuario.

**Response (para GERENTE):**
```json
{
  "active_riders": 25,
  "pending_orders": 12,
  " deliveries_today": 145,
  "revenue_today": 2500000,
  "average_delivery_time": 27.3,
  "customer_satisfaction": 4.6
}
```

### `GET /dashboard/map`
Obtiene datos para mapa en tiempo real.

---

## 🔗 Integraciones

### `POST /integrations/webhooks`
Registra webhook externo.

**Request Body:**
```json
{
  "url": "https://erp-cliente.com/webhook",
  "events": ["ORDER_CREATED", "DELIVERY_COMPLETED"],
  "secret": "shared_secret_key"
}
```

### `GET /integrations/pos/status`
Verifica estado de conexión POS.

---

## 📝 Auditoría

### `GET /audit/logs`
Obtiene logs de auditoría (solo SUPERADMIN).

**Query Params:**
- `user_id`: uuid
- `action`: string
- `date_from`, `date_to`: datetime

---

## ❌ Códigos de Error

| Código | Significado | Ejemplo |
|--------|-------------|---------|
| 400 | Bad Request | Datos inválidos |
| 401 | Unauthorized | Token ausente o inválido |
| 403 | Forbidden | Permisos insuficientes |
| 404 | Not Found | Recurso no existe |
| 409 | Conflict | Estado inválido para operación |
| 500 | Internal Server Error | Error del servidor |

**Formato de respuesta de error:**
```json
{
  "detail": "Mensaje descriptivo del error",
  "error_code": "ERROR_SPECIFIC_CODE"
}
```

---

## 🔑 Roles y Permisos

| Endpoint | SUPERADMIN | GERENTE | OPERADOR | REPARTIDOR | CLIENTE |
|----------|------------|---------|----------|------------|---------|
| auth/* | ✅ | ✅ | ✅ | ✅ | ✅ |
| users/* | ✅ | ✅ | ❌ | ❌ | ❌ |
| riders/* | ✅ | ✅ | ✅ | ⚠️ (propio) | ❌ |
| orders/* | ✅ | ✅ | ✅ | ⚠️ (asignadas) | ⚠️ (propias) |
| financial/* | ✅ | ✅ | ✅ | ⚠️ (propio) | ❌ |
| payouts/* | ✅ | ✅ | ❌ | ⚠️ (propio) | ❌ |
| dashboard/* | ✅ | ✅ | ✅ | ✅ | ❌ |

✅ = Acceso completo  
⚠️ = Acceso limitado a recursos propios  
❌ = Sin acceso

---

*Documentación generada como parte de la Fase 1 de preparación para producción*
