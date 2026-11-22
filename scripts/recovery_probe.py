"""Read-only functional probe of a restored local lab (login changes only auth metadata)."""

import hashlib
import json
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Unexpected API redirect")


def probe(config):
    opener = build_opener(ProxyHandler({}), NoRedirect())
    base = config["base"]
    if (
        not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", base)
        or not 1 <= int(base.rsplit(":", 1)[1]) <= 65535
    ):
        raise ValueError("Loopback API required")

    def request(path, *, token=None, body=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        payload = None
        if body is not None:
            payload = urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            response = opener.open(
                Request(base + path, data=payload, headers=headers), timeout=10
            )
        except HTTPError as error:
            response = error
        with response:
            return response.code, response.read(32 * 1024 * 1024)

    checks = []
    status, raw = request("/health/ready")
    if status != 200 or json.loads(raw).get("checks") != {
        "database": True,
        "redis": True,
    }:
        raise ValueError("Restored dependencies not ready")
    checks.append("restored_api_database_redis_ready")
    status, _ = request("/api/v1/orders?limit=1&offset=0")
    if status != 401:
        raise ValueError("Anonymous boundary not preserved")
    checks.append("anonymous_orders_rejected")
    account = config["account"]
    status, raw = request(
        "/api/v1/auth/login",
        body={"username": account["email"], "password": account["password"]},
    )
    pair = json.loads(raw)
    if status != 200 or not isinstance(pair.get("access_token"), str):
        raise ValueError("Restored login failed")
    token = pair["access_token"]
    checks.append("restored_login_works")
    status, raw = request("/api/v1/auth/me", token=token)
    if status != 200 or json.loads(raw).get("role") != "SUPERADMIN":
        raise ValueError("Restored role not preserved")
    checks.append("restored_superadmin_identity")
    for path, name in [
        ("/api/v1/orders?limit=1&offset=0", "restored_orders_read"),
        ("/api/v1/zones", "restored_zones_read"),
        ("/api/v1/settings/exact/v2", "restored_exact_settings_read"),
    ]:
        status, raw = request(path, token=token)
        if status != 200:
            raise ValueError("Restored operational read failed: " + name)
        json.loads(raw)
        checks.append(name)
    document = config.get("document")
    if not document:
        raise ValueError("A restored document is required for the download probe")
    path = "/api/v1/riders/documents/" + document["id"] + "/download"
    status, _ = request(path)
    if status != 401:
        raise ValueError("Anonymous document access not rejected")
    checks.append("anonymous_document_rejected")
    status, raw = request(path, token=token)
    if status != 200 or hashlib.sha256(raw).hexdigest() != document["sha256"]:
        raise ValueError("Restored document download changed")
    checks.append("authenticated_document_matches_backup")
    return checks


def ready(config):
    base = config["base"]
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", base):
        raise ValueError("Loopback API required")
    with build_opener(ProxyHandler({}), NoRedirect()).open(
        base + "/health/ready", timeout=2
    ) as response:
        if response.code != 200 or json.load(response).get("checks") != {
            "database": True,
            "redis": True,
        }:
            raise ValueError("Restored dependencies not ready")
    return {"ready": True}


if __name__ == "__main__":
    try:
        config = json.load(sys.stdin)
        print(
            json.dumps(
                ready(config) if "--ready" in sys.argv else {"checks": probe(config)}
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "error": (
                        str(error)
                        if isinstance(error, ValueError)
                        else "Restored API transport failed"
                    )
                }
            )
        )
        raise SystemExit(1)
