import logging
import pytest
from uvicorn.logging import AccessFormatter
from app.core.log_redaction import QueryCredentialsFilter, install_log_redaction


@pytest.mark.parametrize(
    "name", ["token", "access_token", "refresh_token", "authorization"]
)
def test_websocket_query_values_are_redacted_before_formatting(name):
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "",
        0,
        '%s - "WebSocket %s" [accepted]',
        (
            "local",
            f"/notifications/ws?{name}=synthetic.secret.signature&channel=orders",
        ),
        None,
    )
    QueryCredentialsFilter().filter(record)
    assert "synthetic.secret.signature" not in record.getMessage()
    assert f"{name}=[REDACTED]&channel=orders" in record.getMessage()


def test_access_formatter_keeps_status_and_tuple_shape():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:8000", "GET", "/ws?token=synthetic.secret.signature", "1.1", 200),
        None,
    )
    QueryCredentialsFilter().filter(record)
    assert len(record.args) == 5 and record.args[-1] == 200
    formatted = AccessFormatter(
        fmt="%(request_line)s %(status_code)s", use_colors=False
    ).format(record)
    assert "GET /ws?token=[REDACTED] HTTP/1.1" in formatted and "200" in formatted


def test_bearer_and_named_values_do_not_change_unrelated_data():
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "",
        0,
        "auth=%(authorization)s account=%(account)s",
        {
            "authorization": "Bearer synthetic.secret.signature",
            "account": "test-account",
        },
        None,
    )
    QueryCredentialsFilter().filter(record)
    assert record.getMessage() == "auth=[REDACTED] account=test-account"


def test_installation_is_idempotent_for_both_uvicorn_loggers():
    install_log_redaction()
    install_log_redaction()
    for name in ("uvicorn.error", "uvicorn.access"):
        assert (
            sum(
                f.name == "delivery360_query_credentials"
                for f in logging.getLogger(name).filters
            )
            == 1
        )
