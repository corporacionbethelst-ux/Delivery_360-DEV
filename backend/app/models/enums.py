# app/models/enums.py
from enum import Enum

class VehicleType(str, Enum):
    MOTO = "MOTO"
    AUTO = "AUTO"
    FURGONETA = "FURGONETA"
    BICICLETA = "BICICLETA"

class VehicleStatus(str, Enum):
    ACTIVO = "ACTIVO"
    MANTENIMIENTO = "MANTENIMIENTO"
    BAJA = "BAJA"


def get_bonificable_causes() -> list[str]:
    """Retorna lista de valores de causas bonificables."""
    return [
        "CLIENTE_NO_ESTA",
        "CLIENTE_NO_CONTESTA",
        "DIRECCION_INCORRECTA",
        "DIRECCION_NO_EXISTE",
        "COMERCIO_CERRADO",
        "CLIENTE_RECHAZA",
        "ZONA_INSEGURA",
        "FUERZA_MAYOR",
        "EDIFICIO_RESTRINGIDO",
    ]


def check_is_bonificable(cause: "DeliveryFailureCause") -> bool:
    """
    Función helper para verificar si una causa es bonificable.
    
    Args:
        cause: Instancia de DeliveryFailureCause
        
    Returns:
        True si la causa da derecho al bono por intento fallido
    """
    if isinstance(cause, DeliveryFailureCause):
        return cause.value in get_bonificable_causes()
    return False


class DeliveryFailureCause(str, Enum):
    """
    Causas estandarizadas para entregas fallidas.
    Determina automáticamente si el repartidor recibe bono por intento fallido.
    """
    # === CAUSAS EXTERNAS (BONIFICABLES - 1500 COP) ===
    CLIENTE_NO_ESTA = "CLIENTE_NO_ESTA"  # Cliente no estaba en el lugar
    CLIENTE_NO_CONTESTA = "CLIENTE_NO_CONTESTA"  # No responde teléfono/portero
    DIRECCION_INCORRECTA = "DIRECCION_INCORRECTA"  # Dirección errónea o incompleta
    DIRECCION_NO_EXISTE = "DIRECCION_NO_EXISTE"  # Dirección no existe
    COMERCIO_CERRADO = "COMERCIO_CERRADO"  # Restaurante/tienda cerrado
    CLIENTE_RECHAZA = "CLIENTE_RECHAZA"  # Cliente rechazó el pedido
    ZONA_INSEGURA = "ZONA_INSEGURA"  # Zona peligrosa o inaccesible
    FUERZA_MAYOR = "FUERZA_MAYOR"  # Lluvia extrema, bloqueo, accidente vial
    EDIFICIO_RESTRINGIDO = "EDIFICIO_RESTRINGIDO"  # Acceso denegado por seguridad
    
    # === CAUSAS DEL REPARTIDOR (NO BONIFICABLES) ===
    REPARTIDOR_NO_QUIERE_ENTREGAR = "REPARTIDOR_NO_QUIERE_ENTREGAR"  # Negativa por comodidad
    REPARTIDOR_LLEGO_TARDE = "REPARTIDOR_LLEGO_TARDE"  # Llegó fuera del tiempo SLA
    REPARTIDOR_ERROR_PROPIO = "REPARTIDOR_ERROR_PROPIO"  # Error operativo del rider
    REPARTIDOR_VEHICULO_FALLA = "REPARTIDOR_VEHICULO_FALLA"  # Falla mecánica de la moto
    REPARTIDOR_SIN_BATERIA = "REPARTIDOR_SIN_BATERIA"  # Celular/moto sin batería
    OTRO_REPARTIDOR = "OTRO_REPARTIDOR"  # Otro repartidor tomó la entrega
    
    @property
    def is_bonificable(self) -> bool:
        """Determina si esta causa da derecho al bono por intento fallido."""
        return check_is_bonificable(self)