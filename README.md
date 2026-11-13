# Delivery360

Aplicación de gestión de órdenes, repartidores, flota, configuración y auditoría.

Para realizar pruebas funcionales locales con la API y la base de datos reales:

```bash
python scripts/local_test.py init
python scripts/local_test.py up
python scripts/local_test.py credentials
```

Necesitas Python 3.11+ y Docker con Compose v2. El comando de arranque confirma
cuándo puedes entrar en <http://localhost:3088/login>. Los datos y credenciales
se generan para un laboratorio independiente y se conservan al detenerlo.

[Guía de pruebas, roles, recorrido y límites](PRUEBAS_LOCALES.md).

[Backend y contratos](backend/README.md) ·
[Registro de entregas](Implementacion_de_mejoras_V1.md).

El laboratorio local permite pruebas funcionales; no acredita preparación para
producción, proveedores externos, pagos reales ni pruebas de carga.
