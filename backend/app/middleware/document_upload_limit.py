"""Bound raw upload requests before multipart parsing, including chunked bodies.

A bounded private temporary spool avoids buffering the entire request in memory.
The framework sees the multipart stream only after the byte limit is verified.
"""

import tempfile
import anyio
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Scope, Receive, Send, Message
from app.services.document_uploads import MAX_DOCUMENT_BYTES


class DocumentUploadLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "").rstrip("/")
        parts = path.split("/")
        registration = path == "/api/v1/auth/register-rider"
        single = (
            len(parts) == 7
            and parts[:4] == ["", "api", "v1", "riders"]
            and parts[-2:] == ["documents", "upload"]
        )
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not (registration or single)
        ):
            await self.app(scope, receive, send)
            return
        limit = MAX_DOCUMENT_BYTES * (4 if registration else 1) + 1024 * 1024
        lengths = [
            v for k, v in scope.get("headers", []) if k.lower() == b"content-length"
        ]
        declared = None
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit() or len(lengths[0]) > 20:
                await JSONResponse(
                    {"detail": "Content-Length inválido"}, status_code=400
                )(scope, receive, send)
                return
            declared = int(lengths[0])
            if declared > limit:
                await JSONResponse(
                    {"detail": "La petición de documentos excede el límite permitido"},
                    status_code=413,
                )(scope, receive, send)
                return
        spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
        total = 0
        try:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    continue
                data = message.get("body", b"")
                total += len(data)
                if total > limit:
                    await JSONResponse(
                        {
                            "detail": "La petición de documentos excede el límite permitido"
                        },
                        status_code=413,
                    )(scope, receive, send)
                    return
                await anyio.to_thread.run_sync(spool.write, data)
                if not message.get("more_body", False):
                    break
            if declared is not None and declared != total:
                await JSONResponse(
                    {"detail": "Longitud de petición inconsistente"}, status_code=400
                )(scope, receive, send)
                return
            await anyio.to_thread.run_sync(spool.seek, 0)
            finished = False
            position = 0

            async def replay() -> Message:
                nonlocal finished, position
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
