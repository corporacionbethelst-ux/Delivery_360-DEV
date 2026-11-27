"""Bounded read-only latency baseline for the marked local laboratory only."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

if __package__:
    from . import local_test, recovery, recovery_probe
else:
    import local_test
    import recovery
    import recovery_probe


PATHS = {
    "orders": "/api/v1/orders?limit=20&offset=0",
    "zones": "/api/v1/zones",
    "exact_settings": "/api/v1/settings/exact/v2",
}
MAX_BODY = 2 * 1024 * 1024


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def summarize(samples, elapsed):
    good = [s["milliseconds"] for s in samples if s["error"] is None]
    return {
        "requests": len(samples),
        "succeeded": len(good),
        "failed": len(samples) - len(good),
        "elapsed_seconds": round(elapsed, 6),
        "completed_requests_per_second": round(len(samples) / elapsed, 3),
        "successful_latency_ms": (
            {
                "p50": percentile(good, 0.50),
                "p95": percentile(good, 0.95),
                "p99": percentile(good, 0.99),
                "max": max(good),
            }
            if good
            else None
        ),
    }


class Client:
    def __init__(self, port):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("Puerto local inválido")
        self.base = "http://127.0.0.1:" + str(port)
        self.token = None

    def request(self, path, form=None):
        allowed = set(PATHS.values()) | {
            "/api/v1/auth/login",
            "/api/v1/auth/me",
            "/health/ready",
        }
        if path not in allowed or (form is not None and path != "/api/v1/auth/login"):
            raise ValueError("Operación fuera del ensayo")
        headers = {"Authorization": "Bearer " + self.token} if self.token else {}
        body = None
        if form is not None:
            body = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(self.base + path, data=body, headers=headers)
        try:
            response = build_opener(ProxyHandler({}), recovery_probe.NoRedirect()).open(
                request, timeout=5
            )
        except HTTPError as error:
            response = error
        with response:
            if response.code != 200:
                return response.code, None, "http_status"
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                return 200, None, "response_too_large"
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                return 200, None, "invalid_json"
            if not isinstance(result, (dict, list)):
                return 200, None, "unexpected_shape"
            return 200, result, None

    def sample(self, name):
        start = time.perf_counter()
        try:
            status, _, error = self.request(PATHS[name])
        except Exception:
            # Never echo URLs, credentials, response bodies or provider exceptions.
            status, error = None, "transport"
        return {
            "endpoint": name,
            "status": status,
            "error": error,
            "milliseconds": round((time.perf_counter() - start) * 1000, 3),
        }


def verify_target(tool):
    ids = (
        tool.run(tool.compose[len(tool.docker) :] + ["ps", "-q", "api"])
        .decode()
        .split()
    )
    if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{12,64}", ids[0]):
        raise ValueError("Se requiere una única API del laboratorio en ejecución")
    cid = ids[0]

    def inspect(template):
        return tool.run(["inspect", "--format", template, cid]).decode().strip()

    labels = json.loads(inspect("{{json .Config.Labels}}"))
    if (
        labels.get("com.docker.compose.project")
        != "delivery360-local-test-" + tool.source["instance"]
        or labels.get("com.docker.compose.service") != "api"
        or inspect("{{.State.Running}}") != "true"
    ):
        raise ValueError("API ajena al laboratorio o detenida")
    ports = json.loads(inspect("{{json .NetworkSettings.Ports}}"))
    if {k: v for k, v in ports.items() if v} != {
        "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(tool.source["api_port"])}]
    }:
        raise ValueError(
            "La publicación no coincide con la API loopback del laboratorio"
        )
    if tool.source_sql("SELECT id FROM local_test_instance") != tool.source["instance"]:
        raise ValueError("La base no pertenece al laboratorio")
    image = inspect("{{.Image}}")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("Imagen no identificada")
    return image


def snapshot(tool):
    tables = tool.source_tables()
    required = {
        "orders",
        "deliveries",
        "payouts",
        "zones",
        "platform_settings",
        "local_test_instance",
    }
    if not required <= tables.keys():
        raise ValueError("Faltan tablas operativas del laboratorio")
    return {
        name: tables[name] for name in sorted(recovery.FINANCIAL_TABLES & tables.keys())
    }


def run(tool, samples=12, workers=4):
    if type(samples) is not int or not 3 <= samples <= 24 or samples % 3:
        raise ValueError("Usa entre 3 y 24 muestras por etapa, múltiplo de 3")
    if type(workers) is not int or not 2 <= workers <= 4:
        raise ValueError("Usa entre 2 y 4 lectores concurrentes")
    image = verify_target(tool)
    client = Client(tool.source["api_port"])
    status, ready, error = client.request("/health/ready")
    if (
        error
        or status != 200
        or not isinstance(ready, dict)
        or ready.get("checks") != {"database": True, "redis": True}
    ):
        raise ValueError("Dependencias del laboratorio no listas")
    account = json.loads(local_test.ACCOUNTS.read_text())["SUPERADMIN"]
    status, pair, error = client.request(
        "/api/v1/auth/login",
        {"username": account["email"], "password": account["password"]},
    )
    if (
        error
        or status != 200
        or not isinstance(pair, dict)
        or not isinstance(pair.get("access_token"), str)
        or not pair["access_token"]
    ):
        raise ValueError("No se pudo autenticar el ensayo")
    client.token = pair["access_token"]
    status, profile, error = client.request("/api/v1/auth/me")
    if (
        error
        or status != 200
        or not isinstance(profile, dict)
        or profile.get("role") != "SUPERADMIN"
    ):
        raise ValueError("Identidad inesperada en el laboratorio")
    before = snapshot(tool)
    stages = []
    names = list(PATHS)
    for concurrency in (1, workers):
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(
                executor.map(
                    client.sample, [names[i % len(names)] for i in range(samples)]
                )
            )
        elapsed = time.perf_counter() - start
        stages.append(
            {
                "concurrency": concurrency,
                **summarize(results, elapsed),
                "endpoints": {
                    name: summarize(
                        [s for s in results if s["endpoint"] == name], elapsed
                    )
                    for name in names
                },
                "samples": results,
            }
        )
    after = snapshot(tool)
    return {
        "version": 1,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "local_read_baseline",
        "production_capacity_verified": False,
        "external_delivery_verified": False,
        "api_image_id": image,
        "includes_login_latency": False,
        "login_changes_auth_metadata": True,
        "protected_tables": sorted(before),
        "protected_snapshots": {"before": before, "after": after},
        "protected_data_unchanged": before == after,
        "stages": stages,
        "passed": before == after and all(s["failed"] == 0 for s in stages),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--wait-request-window", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("No se sobrescriben informes existentes")
    tool = recovery.Recovery()
    verify_target(tool)
    if args.wait_request_window:
        for _ in range(61):
            time.sleep(1)
    result = run(tool, args.samples, args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    local_test.write_private(args.output, json.dumps(result, indent=2) + "\n")
    print(
        "Ensayo local registrado; datos de negocio conservados:",
        result["protected_data_unchanged"],
    )
    if not result["passed"]:
        raise SystemExit(
            "Ensayo fallido; revisar estados y métricas del informe privado"
        )


if __name__ == "__main__":
    main()
