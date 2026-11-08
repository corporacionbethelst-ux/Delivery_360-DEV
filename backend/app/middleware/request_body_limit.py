"""Bound request bytes and read time before JSON/form parsers can allocate them."""

import asyncio
import tempfile
import anyio
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Scope, Receive, Send, Message


class BodyRejected(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


class BoundedBodyMiddleware:
    READ_TIMEOUT_SECONDS = 30.0
    MEMORY_SPOOL_BYTES = 1024 * 1024

    def __init__(self, app: ASGIApp):
        self.app = app

    def request_limit(self, scope: Scope) -> int | None:
        raise NotImplementedError

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self.request_limit(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return
        lengths = [
            value
            for key, value in scope.get("headers", [])
            if key.lower() == b"content-length"
        ]
        declared = None
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit() or len(lengths[0]) > 20:
                await self.reject(scope, receive, send, 400, "Content-Length inválido")
                return
            if any(key.lower() == b"transfer-encoding" for key, _ in scope["headers"]):
                await self.reject(
                    scope, receive, send, 400, "Framing de petición ambiguo"
                )
                return
            declared = int(lengths[0])
            if declared > limit:
                await self.reject(
                    scope, receive, send, 413, "La petición excede el límite permitido"
                )
                return
        spool = tempfile.SpooledTemporaryFile(
            max_size=self.MEMORY_SPOOL_BYTES, mode="w+b"
        )
        try:
            total = 0
            try:
                async with asyncio.timeout(self.READ_TIMEOUT_SECONDS):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        if message["type"] != "http.request":
                            raise BodyRejected(400, "Petición inválida")
                        data = message.get("body", b"")
                        total += len(data)
                        if total > limit:
                            raise BodyRejected(
                                413, "La petición excede el límite permitido"
                            )
                        await anyio.to_thread.run_sync(spool.write, data)
                        if not message.get("more_body", False):
                            break
                if declared is not None and declared != total:
                    raise BodyRejected(400, "Longitud de petición inconsistente")
            except TimeoutError:
                await self.reject(
                    scope, receive, send, 408, "Tiempo de recepción agotado"
                )
                return
            except BodyRejected as exc:
                await self.reject(scope, receive, send, exc.status, exc.detail)
                return
            await anyio.to_thread.run_sync(spool.seek, 0)
            position = 0
            finished = False

            async def replay() -> Message:
                nonlocal position, finished
                if finished:
                    return await receive()
                chunk = await anyio.to_thread.run_sync(spool.read, 64 * 1024)
                position += len(chunk)
                finished = position >= total
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": not finished,
                }

            await self.app(scope, replay, send)
        finally:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(spool.close)

    @staticmethod
    async def reject(
        scope: Scope, receive: Receive, send: Send, status: int, detail: str
    ) -> None:
        await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)


class RequestBodyLimitMiddleware(BoundedBodyMiddleware):
    """General writes: 1 MiB; login forms: 64 KiB. Uploads have their own policy."""

    DEFAULT_LIMIT = 1024 * 1024
    LOGIN_LIMIT = 64 * 1024

    def request_limit(self, scope: Scope) -> int | None:
        if scope["type"] != "http" or scope.get("method") not in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            return None
        from app.middleware.document_upload_limit import document_request_limit

        if document_request_limit(scope) is not None:
            return None
        if scope.get("path", "").rstrip("/") == "/api/v1/auth/login":
            return self.LOGIN_LIMIT
        return self.DEFAULT_LIMIT
