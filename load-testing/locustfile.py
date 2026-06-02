"""
Script de prueba de carga con Locust para Delivery360
Permite simular múltiples usuarios concurrentes para evaluar performance
"""

from locust import HttpUser, task, between, events
import random
import json
from datetime import datetime

class RiderUser(HttpUser):
    """Simula un repartidor usando la aplicación"""
    
    wait_time = between(2, 5)  # Espera entre 2-5 segundos entre tareas
    host = "http://localhost:8000"
    
    def on_start(self):
        """Login al iniciar"""
        # Credenciales de prueba (deben existir en el seed data)
        login_response = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "rider1@delivery360.com",
                "password": "password123"
            }
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}
    
    @task(3)
    def get_my_orders(self):
        """Obtener mis órdenes asignadas (endpoint frecuente)"""
        self.client.get(
            "/api/v1/orders/my-orders",
            headers=self.headers,
            name="/orders/my-orders"
        )
    
    @task(2)
    def update_location(self):
        """Actualizar ubicación GPS (simulado)"""
        self.client.post(
            "/api/v1/riders/update-location",
            json={
                "latitude": 40.416775 + random.uniform(-0.01, 0.01),
                "longitude": -3.703790 + random.uniform(-0.01, 0.01)
            },
            headers=self.headers,
            name="/riders/update-location"
        )
    
    @task(1)
    def get_dashboard(self):
        """Ver dashboard del repartidor"""
        self.client.get(
            "/api/v1/dashboard/rider",
            headers=self.headers,
            name="/dashboard/rider"
        )


class OperatorUser(HttpUser):
    """Simula un operador gestionando entregas"""
    
    wait_time = between(3, 8)
    host = "http://localhost:8000"
    
    def on_start(self):
        """Login como operador"""
        login_response = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "operator@delivery360.com",
                "password": "password123"
            }
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}
    
    @task(4)
    def list_orders(self):
        """Listar órdenes (operación muy frecuente)"""
        self.client.get(
            "/api/v1/orders?status=PENDING&limit=50",
            headers=self.headers,
            name="/orders [LIST]"
        )
    
    @task(3)
    def list_riders(self):
        """Listar repartidores disponibles"""
        self.client.get(
            "/api/v1/riders?status=ACTIVO&limit=50",
            headers=self.headers,
            name="/riders [LIST]"
        )
    
    @task(2)
    def create_order(self):
        """Crear nueva orden"""
        order_data = {
            "customer_name": f"Cliente Test {random.randint(1, 1000)}",
            "customer_phone": "+573001234567",
            "pickup_address": "Calle 123 #45-67",
            "delivery_address": "Carrera 45 #123-89",
            "delivery_contact": "Juan Pérez",
            "priority": random.choice(["NORMAL", "ALTA", "URGENTE"]),
            "sla_minutes": 60
        }
        self.client.post(
            "/api/v1/orders",
            json=order_data,
            headers=self.headers,
            name="/orders [CREATE]"
        )
    
    @task(1)
    def assign_rider(self):
        """Asignar repartidor a orden (simulado)"""
        order_id = f"{random.randint(1, 100)}"
        rider_id = f"{random.randint(1, 50)}"
        self.client.post(
            f"/api/v1/orders/{order_id}/assign",
            json={"rider_id": rider_id},
            headers=self.headers,
            name="/orders/[id]/assign"
        )


class ManagerUser(HttpUser):
    """Simula un gerente revisando métricas"""
    
    wait_time = between(5, 15)
    host = "http://localhost:8000"
    
    def on_start(self):
        """Login como gerente"""
        login_response = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "manager@delivery360.com",
                "password": "password123"
            }
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}
    
    @task(3)
    def view_dashboard(self):
        """Ver dashboard gerencial"""
        self.client.get(
            "/api/v1/dashboard/manager",
            headers=self.headers,
            name="/dashboard/manager"
        )
    
    @task(2)
    def view_productivity(self):
        """Ver métricas de productividad"""
        self.client.get(
            "/api/v1/productivity/metrics",
            headers=self.headers,
            name="/productivity/metrics"
        )
    
    @task(1)
    def view_financial(self):
        """Ver reporte financiero"""
        self.client.get(
            "/api/v1/financial/summary",
            headers=self.headers,
            name="/financial/summary"
        )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Configuración inicial antes de iniciar pruebas"""
    print("\n" + "="*60)
    print("🚀 INICIANDO PRUEBAS DE CARGA - DELIVERY360")
    print("="*60)
    print(f"⏰ Hora de inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Usuarios simulados:")
    print(f"   - Repartidores (RiderUser): {environment.runner.user_classes_count.get(RiderUser, 0)}")
    print(f"   - Operadores (OperatorUser): {environment.runner.user_classes_count.get(OperatorUser, 0)}")
    print(f"   - Gerentes (ManagerUser): {environment.runner.user_classes_count.get(ManagerUser, 0)}")
    print("="*60 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Resumen final después de las pruebas"""
    stats = environment.stats
    
    print("\n" + "="*60)
    print("📈 RESUMEN DE PRUEBAS DE CARGA - DELIVERY360")
    print("="*60)
    print(f"⏰ Hora de finalización: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n📊 ESTADÍSTICAS GLOBALES:")
    print(f"   - Total Requests: {stats.total.num_requests}")
    print(f"   - Total Failures: {stats.total.num_failures}")
    print(f"   - Success Rate: {(1 - stats.total.num_failures/stats.total.num_requests)*100:.2f}%" if stats.total.num_requests > 0 else "   - Success Rate: N/A")
    print(f"\n🔥 TOP ENDPOINTS POR DEMANDA:")
    
    # Ordenar endpoints por número de requests
    sorted_endpoints = sorted(
        [(name, s.num_requests, s.avg_response_time) 
         for name, s in stats.entries.items()],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    for i, (endpoint, requests, avg_time) in enumerate(sorted_endpoints, 1):
        print(f"   {i}. {endpoint}: {requests} reqs, {avg_time:.2f}ms avg")
    
    print("\n⚠️ ENDPOINTS CON MÁS ERRORES:")
    error_endpoints = [
        (name, s.num_failures) 
        for name, s in stats.entries.items() 
        if s.num_failures > 0
    ]
    
    if error_endpoints:
        for endpoint, failures in sorted(error_endpoints, key=lambda x: x[1], reverse=True)[:5]:
            print(f"   - {endpoint}: {failures} fallos")
    else:
        print("   ✅ ¡Sin errores detectados!")
    
    print("="*60 + "\n")


# Para ejecutar:
# locust -f locustfile.py --host=http://localhost:8000
#
# Opciones recomendadas:
# --users=100        # Número total de usuarios concurrentes
# --spawn-rate=10    # Usuarios que se agregan por segundo
# --run-time=5m      # Duración de la prueba
# --headless         # Modo sin interfaz web
