import re
from typing import Optional, Dict, Any

class DeliveryIssueAnalyzer:
    """
    Analiza la descripción de una incidencia para determinar si fue 
    causada por factores externos al repartidor.
    """
    
    # Palabras clave que indican CAUSA EXTERNA (Cliente, Comercio, Fuerza Mayor)
    EXTERNAL_CAUSES = [
        "cliente no estaba", "no habia nadie", "nadie abrio", "puerta cerrada",
        "direccion incorrecta", "direccion mala", "no existe la direccion",
        "comercio cerrado", "restaurante cerrado", "tienda cerrada",
        "cliente no contesta", "telefono apagado", "no responde",
        "zona peligrosa", "inseguridad", "bloqueo", "protesta",
        "lluvia fuerte", "accidente via", "calles inundadas",
        "falta de luz", "sin ascensor", "edificio restringido"
    ]

    # Palabras clave que indican CULPA DEL REPARTIDOR
    RIDER_FAULTS = [
        "se me cayo", "se cayó la comida", "derrame", "olvide", "se me olvido",
        "llegue tarde", "me equivoque", "confundi la direccion", "error mio",
        "moto se daño", "ponchadura", "me quede sin bateria", "choque",
        "no quise subir", "pereza", "lejos", "mucha fila" # Si el rider se niega por comodidad
    ]

    @staticmethod
    def analyze(text: Optional[str]) -> Dict[str, Any]:
        """
        Analiza el texto y devuelve si es causa externa y la confianza.
        Retorna: {
            "is_external_fault": bool,
            "reason": str,
            "confidence": str (high/low)
        }
        """
        if not text:
            return {
                "is_external_fault": False,
                "reason": "Sin descripción proporcionada",
                "confidence": "high"
            }

        text_lower = text.lower()

        # 1. Detectar Culpa del Repartidor (Prioridad alta para descartar pago)
        for fault in DeliveryIssueAnalyzer.RIDER_FAULTS:
            if fault in text_lower:
                return {
                    "is_external_fault": False,
                    "reason": f"Indicio de culpa del repartidor: '{fault}'",
                    "confidence": "high"
                }

        # 2. Detectar Causa Externa
        for cause in DeliveryIssueAnalyzer.EXTERNAL_CAUSES:
            if cause in text_lower:
                return {
                    "is_external_fault": True,
                    "reason": f"Causa externa detectada: '{cause}'",
                    "confidence": "high"
                }

        # 3. Si no hay coincidencias exactas, podríamos usar lógica difusa o asumir por defecto
        # Por seguridad operativa, si no está claro, asumimos que NO es culpa externa (no pagar)
        # O podrías devolver 'review_required' para que un humano lo apruebe.
        return {
            "is_external_fault": False,
            "reason": "No se detectaron patrones claros de causa externa. Requiere revisión manual.",
            "confidence": "low"
        }
