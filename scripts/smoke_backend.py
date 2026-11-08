"""Exercise an isolated local backend; never accepts a remote/production URL."""

import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def response(base, path, *, oversized=False):
    headers = {"Content-Length": "999999999"} if oversized else {}
    request = Request(base + path, data=b"" if oversized else None, headers=headers)
    try:
        result = urlopen(request, timeout=4)
    except HTTPError as error:
        result = error
    with result:
        body = result.read(8192)
        return result.code, json.loads(body), result.headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--redis-down", action="store_true")
    args = parser.parse_args()
    target = urlparse(args.base_url)
    if (
        target.scheme != "http"
        or target.hostname not in {"localhost", "127.0.0.1"}
        or target.username
        or target.password
        or target.path not in {"", "/"}
        or target.query
        or target.fragment
    ):
        parser.error("Only a plain local test URL is allowed")
    base = args.base_url.rstrip("/")
    expected = 503 if args.redis_down else 200
    deadline = time.monotonic() + 60
    while True:
        try:
            status, data, _ = response(base, "/health/ready")
            if status == expected:
                break
        except (URLError, TimeoutError, ConnectionError):
            pass
        if time.monotonic() >= deadline:
            raise SystemExit("Local backend did not reach the expected readiness state")
        time.sleep(0.5)
    assert data["checks"] == {"database": True, "redis": not args.redis_down}
    assert response(base, "/health/live")[0] == 200
    if not args.redis_down:
        status, _, headers = response(base, "/api/v1/auth/me")
        assert status == 401 and headers["WWW-Authenticate"] == "Bearer"
        for path in (
            "/api/v1/auth/login",
            "/api/v1/orders",
            "/api/v1/auth/register-rider",
        ):
            assert response(base, path, oversized=True)[0] == 413
    print(
        json.dumps(
            {
                "readiness": expected,
                "database": True,
                "redis": not args.redis_down,
                "liveness": 200,
                "mode": "synthetic local smoke",
            }
        )
    )


if __name__ == "__main__":
    main()
