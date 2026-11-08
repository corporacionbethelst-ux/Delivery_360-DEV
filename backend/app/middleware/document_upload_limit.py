"""Document request limits before multipart parsing, with a bounded private spool."""

# Keep the module-level tempfile alias used by existing spool lifetime contracts.
from app.middleware.request_body_limit import BoundedBodyMiddleware, tempfile
from starlette.types import Scope
from app.services.document_uploads import MAX_DOCUMENT_BYTES


def document_request_limit(scope: Scope) -> int | None:
    if scope["type"] != "http" or scope.get("method") != "POST":
        return None
    path = scope.get("path", "").rstrip("/")
    parts = path.split("/")
    registration = path == "/api/v1/auth/register-rider"
    single = (
        len(parts) == 7
        and parts[:4] == ["", "api", "v1", "riders"]
        and parts[-2:] == ["documents", "upload"]
    )
    if registration or single:
        return MAX_DOCUMENT_BYTES * (4 if registration else 1) + 1024 * 1024
    return None


class DocumentUploadLimitMiddleware(BoundedBodyMiddleware):
    def request_limit(self, scope: Scope) -> int | None:
        return document_request_limit(scope)
