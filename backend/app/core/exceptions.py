"""
Excepciones personalizadas para la aplicación - Fase 7 Enterprise
"""
from typing import Any, Optional, Dict


class AppException(Exception):
    """Excepción base para todas las excepciones de la aplicación."""
    def __init__(self, message: str, status_code: int = 500, detail: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {"message": message}
        super().__init__(self.message)


class NotFoundError(AppException):
    """Recurso no encontrado."""
    def __init__(self, message: str = "Recurso no encontrado"):
        super().__init__(message=message, status_code=404)


class ValidationError(AppException):
    """Error de validación de datos."""
    def __init__(self, message: str = "Error de validación"):
        super().__init__(message=message, status_code=400)


class UnauthorizedError(AppException):
    """No autorizado."""
    def __init__(self, message: str = "No autorizado"):
        super().__init__(message=message, status_code=401)


class ForbiddenError(AppException):
    """Acceso prohibido."""
    def __init__(self, message: str = "Acceso prohibido"):
        super().__init__(message=message, status_code=403)


class InsufficientFundsError(AppException):
    """Fondos insuficientes en wallet."""
    def __init__(self, message: str = "Fondos insuficientes"):
        super().__init__(message=message, status_code=400)


class DuplicateTransactionError(AppException):
    """Transacción duplicada (idempotencia)."""
    def __init__(self, message: str = "Transacción duplicada"):
        super().__init__(message=message, status_code=409)


class PayoutProcessingError(AppException):
    """Error al procesar payout."""
    def __init__(self, message: str = "Error al procesar payout"):
        super().__init__(message=message, status_code=500)


class DatabaseError(AppException):
    """Error de base de datos."""
    def __init__(self, message: str = "Error de base de datos"):
        super().__init__(message=message, status_code=500)
