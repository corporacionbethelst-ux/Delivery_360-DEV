"""Keep URL credentials out of Uvicorn logs without changing access-log tuples."""

import logging
import re

_QUERY = re.compile(
    r'([?&](?:token|access_token|refresh_token|authorization)=)[^&\s"<>]+',
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9_.~+/-]+=*", re.IGNORECASE)
_KEYS = frozenset(
    ("token", "access_token", "refresh_token", "authorization", "password")
)


def _redact(value):
    if isinstance(value, str):
        return _BEARER.sub("Bearer [REDACTED]", _QUERY.sub(r"\1[REDACTED]", value))
    if isinstance(value, tuple):
        return tuple(_redact(part) for part in value)
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in _KEYS else _redact(part)
            for key, part in value.items()
        }
    return value


class QueryCredentialsFilter(logging.Filter):
    def filter(self, record):
        record.msg = _redact(record.msg)
        record.args = _redact(record.args)
        return True


def install_log_redaction():
    for name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(
            getattr(item, "name", None) == "delivery360_query_credentials"
            for item in logger.filters
        ):
            logger.addFilter(QueryCredentialsFilter("delivery360_query_credentials"))
