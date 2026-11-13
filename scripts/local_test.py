"""Start an isolated, persistent local Delivery360 laboratory with Docker Compose."""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".delivery360-testing"
CONFIG = STATE / "config.json"
ENV = STATE / "runtime.env"
ACCOUNTS = STATE / "credentials.json"


class LocalRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old, new = urlsplit(request.full_url), urlsplit(newurl)
        if new.scheme != "http" or new.netloc != old.netloc:
            raise ValueError("Se rechazó una redirección fuera del laboratorio local")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def compose_environment():
    # Values must come from this instance's env file, not another exported laboratory.
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("LOCAL_TEST_")
    }


def write_private(path, text):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(text)


def initialize(web_port, api_port):
    if CONFIG.exists():
        print("El laboratorio ya está configurado. Se conservan credenciales y datos.")
        return
    if web_port == api_port or any(
        not 1024 <= port <= 65535 for port in (web_port, api_port)
    ):
        raise ValueError("Usa dos puertos distintos entre 1024 y 65535")
    STATE.mkdir(mode=0o700, exist_ok=True)
    if ENV.exists() or ACCOUNTS.exists():
        raise ValueError(
            "Inicialización incompleta: conserva y revisa los archivos existentes; no se sobrescriben"
        )
    instance = secrets.token_hex(8)
    password = secrets.token_urlsafe(24)
    users = {
        role: {"email": login + ".local-test@example.com", "password": password}
        for role, login in (
            ("SUPERADMIN", "admin"),
            ("GERENTE", "gerente"),
            ("OPERADOR", "operador"),
            ("REPARTIDOR", "repartidor"),
            ("AUDITOR", "auditor"),
            ("CLIENTE", "cliente"),
        )
    }
    values = {
        "LOCAL_TEST_ID": instance,
        "LOCAL_TEST_WEB_PORT": str(web_port),
        "LOCAL_TEST_API_PORT": str(api_port),
        "LOCAL_TEST_SECRET": secrets.token_hex(48),
        "LOCAL_TEST_DB_PASSWORD": secrets.token_hex(24),
        "LOCAL_TEST_PASSWORD": password,
    }
    write_private(
        ENV, "".join(key + "=" + value + "\n" for key, value in values.items())
    )
    write_private(ACCOUNTS, json.dumps(users, indent=2) + "\n")
    write_private(
        CONFIG,
        json.dumps(
            {
                "version": 1,
                "instance": instance,
                "web_port": web_port,
                "api_port": api_port,
            },
            indent=2,
        )
        + "\n",
    )
    print(
        "Laboratorio configurado. Las credenciales privadas están en .delivery360-testing/credentials.json"
    )


def configuration():
    if not CONFIG.exists():
        raise ValueError("Ejecuta primero: python scripts/local_test.py init")
    data = json.loads(CONFIG.read_text())
    if (
        data.get("version") != 1
        or not re.fullmatch(r"[a-f0-9]{16}", data.get("instance", ""))
        or any(
            type(data.get(key)) is not int or not 1024 <= data[key] <= 65535
            for key in ("web_port", "api_port")
        )
        or data["web_port"] == data["api_port"]
    ):
        raise ValueError("Configuración local no válida")
    return data


def local_docker():
    if os.environ.get("DOCKER_CONTEXT"):
        query = [
            "docker",
            "context",
            "inspect",
            os.environ["DOCKER_CONTEXT"],
            "--format",
            "{{.Endpoints.docker.Host}}",
        ]
        endpoint = subprocess.check_output(query, text=True).strip()
    elif os.environ.get("DOCKER_HOST"):
        endpoint = os.environ["DOCKER_HOST"]
    else:
        endpoint = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            text=True,
        ).strip()
    if not endpoint.startswith(("unix://", "npipe://")):
        raise ValueError(
            "Este laboratorio requiere un Docker local (socket Unix o Docker Desktop); se rechaza un daemon remoto"
        )
    return ["docker", "--host", endpoint]


def compose(data, docker, ca=None):
    command = docker + [
        "compose",
        "--project-name",
        "delivery360-local-test-" + data["instance"],
        "--env-file",
        str(ENV),
        "-f",
        str(ROOT / "compose.testing.yml"),
    ]
    if ca:
        certificate = Path(ca).resolve()
        if not certificate.is_file():
            raise ValueError("No se encuentra el certificado de compilación")
        overlay = {
            "services": {
                name: {
                    "build": {"secrets": [{"source": "proxy_ca", "target": "proxy_ca"}]}
                }
                for name in ("api", "web")
            },
            "secrets": {"proxy_ca": {"file": str(certificate)}},
        }
        path = STATE / "build-ca.json"
        path.write_text(json.dumps(overlay))
        command += ["-f", str(path)]
    return command


def api_request(base, path, method="GET", body=None, token=None, form=False):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = None
    if body is not None:
        payload = urlencode(body).encode() if form else json.dumps(body).encode()
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    request = Request(base + path, data=payload, headers=headers, method=method)
    try:
        response = build_opener(ProxyHandler({}), LocalRedirect()).open(
            request, timeout=15
        )
    except HTTPError as error:
        response = error
    with response:
        raw = response.read(1_000_000)
        return response.code, json.loads(raw)


def check(data, authenticate=True):
    base = "http://localhost:" + str(data["api_port"])
    web = "http://localhost:" + str(data["web_port"]) + "/login"
    with build_opener(ProxyHandler({}), LocalRedirect()).open(
        web, timeout=15
    ) as response:
        if response.code != 200 or "text/html" not in response.headers.get(
            "Content-Type", ""
        ):
            raise ValueError("La interfaz web no está lista")
    status, result = api_request(base, "/health/ready")
    if status != 200 or result.get("checks") != {"database": True, "redis": True}:
        raise ValueError("API, PostgreSQL o Redis no están listos")
    if authenticate:
        users = json.loads(ACCOUNTS.read_text())
        role = "SUPERADMIN"
        account = users[role]
        code, pair = api_request(
            base,
            "/api/v1/auth/login",
            "POST",
            {"username": account["email"], "password": account["password"]},
            form=True,
        )
        if code != 200 or not isinstance(pair.get("access_token"), str):
            raise ValueError("No se pudo iniciar sesión con el rol " + role)
        code, profile = api_request(base, "/api/v1/auth/me", token=pair["access_token"])
        if code != 200 or profile.get("role") != role:
            raise ValueError("Identidad o rol no confirmados")
    print("Interfaz, API, PostgreSQL y Redis listos.")
    if authenticate:
        print("Inicio de sesión e identidad SUPERADMIN confirmados.")
    print("Abre http://localhost:" + str(data["web_port"]) + "/login")
    print("Swagger: " + base + "/docs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--web-port", type=int, default=3088)
    init.add_argument("--api-port", type=int, default=8088)
    up = sub.add_parser("up")
    up.add_argument("--build-ca")
    up.add_argument(
        "--no-build", action="store_true", help="Usar imágenes locales ya compiladas"
    )
    for action in ("check", "status", "down", "credentials"):
        sub.add_parser(action)
    args = parser.parse_args()
    if args.action == "init":
        initialize(args.web_port, args.api_port)
        return
    data = configuration()
    if args.action == "credentials":
        print(ACCOUNTS.read_text())
        return
    if args.action == "check":
        check(data)
        return
    docker = local_docker()
    subprocess.run(docker + ["info", "--format", "{{.ServerVersion}}"], check=True)
    command = compose(data, docker, getattr(args, "build_ca", None))
    if args.action == "up":

        def run(arguments):
            subprocess.run(
                command + arguments, cwd=ROOT, check=True, env=compose_environment()
            )

        if not args.no_build:
            run(["build", "api", "web"])
        wait = ["up", "--no-build", "--detach", "--wait", "--wait-timeout", "180"]
        run(wait + ["test-db", "test-redis"])
        # Releasing the initializer before creating the API saves a runtime rootfs.
        # Stop an existing API before migrations; volumes and credentials survive.
        run(["rm", "--stop", "--force", "web", "api"])
        run(["run", "--rm", "--no-deps", "setup"])
        run(wait + ["--no-deps", "api"])
        run(wait + ["--no-deps", "web"])
        check(data)
    elif args.action == "status":
        subprocess.run(
            command + ["ps", "--all"], cwd=ROOT, check=True, env=compose_environment()
        )
    elif args.action == "down":
        subprocess.run(
            command + ["down"], cwd=ROOT, check=True, env=compose_environment()
        )
        print("Laboratorio detenido. Los volúmenes y credenciales se conservan.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print("No se pudo completar la operación local: " + str(error), file=sys.stderr)
        raise SystemExit(1)
