"""Private offline backup and isolated restore rehearsal for the marked local lab."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import signal
import socket
import subprocess
import sys
import tarfile
import time

if __package__:
    from . import local_test
else:
    import local_test

LABEL = "delivery360.recovery"
LIMIT = 256 * 1024 * 1024
FINANCIAL_TABLES = {
    "orders",
    "deliveries",
    "financials",
    "financial_transactions",
    "rider_wallets",
    "payouts",
    "payout_status_history",
    "bcv_rates",
    "usd_ves_quotes",
    "order_currency_quotes",
    "customer_collections",
    "customer_collection_reviews",
    "customer_refunds",
    "customer_refund_events",
    "zones",
    "platform_settings",
    "rider_documents",
}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{12}", value):
        raise ValueError("Identificador de recuperación inválido")
    return value


def private(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def table_fingerprints(raw):
    tables = {}
    pattern = r"COPY public\.([a-z_0-9]+) \(([^\n]+)\) FROM stdin;\n(.*?)^\\\.\n"
    for name, columns, block in re.findall(pattern, raw, re.S | re.M):
        if name in tables:
            raise ValueError("Duplicate dump table")
        rows = sorted(block.splitlines())
        tables[name] = {
            "rows": len(rows),
            "sha256": hashlib.sha256(
                json.dumps([columns, rows], ensure_ascii=False).encode()
            ).hexdigest(),
        }
    if not tables:
        raise ValueError("No public COPY tables in the backup")
    return tables


def archive_manifest(data):
    if len(data) > LIMIT:
        raise ValueError("El archivo de documentos supera el límite local")
    result = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("Ruta o tipo de documento no permitido")
            name = str(path)
            if (
                name in result
                or member.mode & 0o7000
                or member.uid != 10001
                or member.gid != 10001
            ):
                raise ValueError("Metadatos de documentos no válidos")
            total += member.size
            if total > LIMIT or len(result) >= 10000 or member.size > 32 * 1024 * 1024:
                raise ValueError("Límites de documentos superados")
            digest = None
            if member.isfile():
                f = archive.extractfile(member)
                digest = hashlib.sha256(f.read()).hexdigest()
            result[name] = {
                "kind": "file" if member.isfile() else "directory",
                "mode": member.mode,
                "uid": member.uid,
                "gid": member.gid,
                "size": member.size,
                "sha256": digest,
            }
    return result


def load_bundle(path):
    for name in ("manifest.json", "database.dump", "uploads.tar.gz"):
        if (path / name).is_symlink() or not (path / name).is_file():
            raise ValueError("Respaldo incompleto o enlace no permitido")
    m = json.loads((path / "manifest.json").read_text())
    if (
        m.get("version") != 1
        or m.get("backup_id") != identifier(path.name)
        or not re.fullmatch("[a-f0-9]{16}", m.get("source_instance", ""))
    ):
        raise ValueError("Manifiesto de respaldo inválido")
    for name in ("database.dump", "uploads.tar.gz"):
        q = path / name
        if (
            q.stat().st_size > LIMIT
            or hashlib.sha256(q.read_bytes()).hexdigest() != m["files"][name]["sha256"]
        ):
            raise ValueError("Integridad del respaldo no confirmada")
    if (
        not (path / "database.dump").read_bytes().startswith(b"PGDMP")
        or archive_manifest((path / "uploads.tar.gz").read_bytes()) != m["uploads"]
    ):
        raise ValueError("Contenido de respaldo no confirmado")
    return m


class Recovery:
    def __init__(self):
        self.source = local_test.configuration()
        self.docker = local_test.local_docker()
        self.compose = local_test.compose(self.source, self.docker)
        self.env = local_test.compose_environment()
        self.root = local_test.STATE / "recovery"
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.state = None
        self.process = None

    def run(self, args, *, data=None):
        r = subprocess.run(
            self.docker + args,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )
        if r.returncode:
            if self.state:
                log = self.root / "runs" / self.state["id"] / "diagnostic.private"
                if not log.exists():
                    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(r.stderr)
            raise ValueError(
                "Falló una operación Docker; los recursos propios y el diagnóstico privado se conservan"
            )
        return r.stdout

    def source_exec(self, *args):
        return self.run(
            self.compose[len(self.docker) :] + ["exec", "-T", "test-db", *args]
        )

    def source_sql(self, query):
        return (
            self.source_exec(
                "psql",
                "-U",
                "local_test",
                "-d",
                "test_delivery360_manual",
                "-Atc",
                query,
            )
            .decode()
            .strip()
        )

    def source_ready(self):
        if (
            self.source_sql("SELECT id FROM local_test_instance")
            != self.source["instance"]
        ):
            raise ValueError("La identidad de la base original no coincide")
        active = (
            self.run(
                self.compose[len(self.docker) :]
                + ["ps", "--status", "running", "--services"]
            )
            .decode()
            .splitlines()
        )
        if set(active) & {"api", "web", "setup"}:
            raise ValueError(
                "Detén api/web antes del respaldo offline; no se detienen automáticamente"
            )
        if (
            self.source_sql(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'"
            )
            != "0"
        ):
            raise ValueError(
                "La base original tiene otras conexiones; requiere pausa offline"
            )

    def source_tables(self):
        return table_fingerprints(
            self.source_exec(
                "pg_dump",
                "-U",
                "local_test",
                "-d",
                "test_delivery360_manual",
                "--data-only",
            ).decode()
        )

    def tar(self, volume):
        return self.run(
            [
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--user",
                "10001:10001",
                "-v",
                volume + ":/target:ro",
                "redis:7-alpine",
                "tar",
                "czf",
                "-",
                "-C",
                "/target",
                ".",
            ]
        )

    def backup(self):
        self.source_ready()
        before = self.source_tables()
        volume = "delivery360-local-test-" + self.source["instance"] + "_test_uploads"
        uploads = self.tar(volume)
        upload_meta = archive_manifest(uploads)
        dump = self.source_exec(
            "pg_dump", "-U", "local_test", "-d", "test_delivery360_manual", "-Fc"
        )
        if len(dump) > LIMIT:
            raise ValueError("Respaldo local demasiado grande")
        self.source_ready()
        if before != self.source_tables() or upload_meta != archive_manifest(
            self.tar(volume)
        ):
            raise ValueError(
                "El laboratorio cambió durante el respaldo; no se publica un paquete completo"
            )
        head = self.source_sql("SELECT version_num FROM alembic_version")
        if not re.fullmatch("[a-zA-Z0-9_]+", head):
            raise ValueError("Head de migración inválido")
        backup_id = secrets.token_hex(6)
        parent = self.root / "backups"
        parent.mkdir(mode=0o700, exist_ok=True)
        target = parent / backup_id
        target.mkdir(mode=0o700)
        for name, data in [("database.dump", dump), ("uploads.tar.gz", uploads)]:
            fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        manifest = {
            "version": 1,
            "backup_id": backup_id,
            "source_instance": self.source["instance"],
            "migration_head": head,
            "tables": before,
            "uploads": upload_meta,
            "files": {
                n: {"sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d)}
                for n, d in [("database.dump", dump), ("uploads.tar.gz", uploads)]
            },
            "consistency": "offline_local_lab_checked_before_and_after",
        }
        private(target / "manifest.json", json.dumps(manifest, indent=2))
        load_bundle(target)
        return backup_id

    def names(self, run_id):
        prefix = "delivery360-recovery-" + identifier(run_id)
        return {
            k: prefix + "-" + k
            for k in ("db", "redis", "api", "data", "uploads", "net")
        }

    def stop(self, run_id):
        names = self.names(run_id)
        state_path = self.root / "runs" / run_id / "state.json"
        if state_path.is_file():
            state = json.loads(state_path.read_text())
            pid = state.get("native_pid")
            if pid and Path("/proc", str(pid), "environ").exists():
                environment = Path("/proc", str(pid), "environ").read_bytes()
                expected = ("DELIVERY360_RECOVERY_ID=" + run_id).encode()
                if expected not in environment.split(b"\0") or os.getpgid(pid) != pid:
                    raise ValueError("No se detiene un proceso nativo ajeno")
                os.killpg(pid, signal.SIGTERM)
        ids = (
            self.run(["ps", "-aq", "--filter", "label=" + LABEL + "=" + run_id])
            .decode()
            .splitlines()
        )
        for cid in ids:
            info = json.loads(self.run(["inspect", cid]))[0]
            if info["Config"]["Labels"].get(LABEL) != run_id or info["Name"].lstrip(
                "/"
            ) not in {names[k] for k in ("db", "redis", "api")}:
                raise ValueError("No se detiene un contenedor ajeno")
            self.run(["stop", "-t", "10", cid])

    def sql(self, query):
        return (
            self.run(
                [
                    "exec",
                    self.state["names"]["db"],
                    "psql",
                    "-U",
                    "local_test",
                    "-d",
                    "test_recovery",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-Atc",
                    query,
                ]
            )
            .decode()
            .strip()
        )

    def restored_tables(self):
        return table_fingerprints(
            self.run(
                [
                    "exec",
                    self.state["names"]["db"],
                    "pg_dump",
                    "-U",
                    "local_test",
                    "-d",
                    "test_recovery",
                    "--data-only",
                ]
            ).decode()
        )

    def wait_db(self):
        name = self.state["names"]["db"]
        for _ in range(90):
            r = subprocess.run(
                self.docker
                + [
                    "exec",
                    name,
                    "sh",
                    "-ec",
                    'test "$(cat /proc/1/comm)" = postgres && pg_isready -U local_test -d postgres',
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self.env,
            )
            if r.returncode == 0:
                return
            time.sleep(1)
        raise ValueError("PostgreSQL no terminó su inicialización")

    def restore(self, backup_id, *, api_image=None, python=None):
        path = self.root / "backups" / identifier(backup_id)
        if path.is_symlink():
            raise ValueError("Directorio de respaldo no permitido")
        m = load_bundle(path)
        if m["source_instance"] != self.source["instance"]:
            raise ValueError("Respaldo de otra instancia local")
        accounts = json.loads(local_test.ACCOUNTS.read_text())
        account = accounts["SUPERADMIN"]
        if api_image:
            self.run(["image", "inspect", api_image])
        if python and os.name != "posix":
            raise ValueError("Modo nativo requiere POSIX; usa --api-image")
        run_id = secrets.token_hex(6)
        names = self.names(run_id)
        for kind, keys, template in [
            ("volume", ("data", "uploads"), "{{.Name}}"),
            ("network", ("net",), "{{.Name}}"),
            ("container", ("db", "redis", "api"), "{{.Names}}"),
        ]:
            arguments = (
                [kind, "ls"]
                + (["-a"] if kind == "container" else [])
                + ["--format", template]
            )
            existing = set(self.run(arguments).decode().splitlines())
            if any(names[key] in existing for key in keys):
                raise ValueError("No se reutilizan recursos de un destino existente")
        run_dir = self.root / "runs" / run_id
        run_dir.mkdir(mode=0o700, parents=True)
        self.state = {
            "version": 1,
            "id": run_id,
            "backup_id": backup_id,
            "names": names,
            "status": "creating",
        }
        state_file = run_dir / "state.json"
        private(state_file, json.dumps(self.state))
        checks = ["backup_hashes_and_archive_validated"]
        report = None
        try:
            label = LABEL + "=" + run_id
            for key in ("data", "uploads"):
                self.run(["volume", "create", "--label", label, names[key]])
            self.run(
                ["network", "create", "--internal", "--label", label, names["net"]]
            )
            password = secrets.token_hex(24)
            db_env = run_dir / "db.env"
            private(
                db_env,
                "POSTGRES_USER=local_test\nPOSTGRES_DB=postgres\nPOSTGRES_PASSWORD="
                + password
                + "\n",
            )
            ports = ["-p", "127.0.0.1::5432"] if python else []
            self.run(
                [
                    "run",
                    "-d",
                    "--pull=never",
                    "--name",
                    names["db"],
                    "--label",
                    label,
                    "--network",
                    names["net"],
                    "--env-file",
                    str(db_env),
                    "-v",
                    names["data"] + ":/var/lib/postgresql/data",
                    *ports,
                    "postgis/postgis:16-3.4",
                ]
            )
            self.wait_db()
            self.run(
                [
                    "exec",
                    names["db"],
                    "createdb",
                    "-U",
                    "local_test",
                    "-T",
                    "template0",
                    "test_recovery",
                ]
            )
            self.run(
                [
                    "exec",
                    "-i",
                    names["db"],
                    "pg_restore",
                    "--exit-on-error",
                    "-U",
                    "local_test",
                    "-d",
                    "test_recovery",
                ],
                data=(path / "database.dump").read_bytes(),
            )
            checks.append("database_restored_after_final_postgres_start")
            if self.restored_tables() != m["tables"]:
                raise ValueError("Filas restauradas diferentes")
            if (
                self.sql("SELECT version_num FROM alembic_version")
                != m["migration_head"]
                or self.sql("SELECT count(*) FROM pg_constraint WHERE NOT convalidated")
                != "0"
            ):
                raise ValueError("Esquema restaurado no confirmado")
            checks.append("all_table_rows_and_migration_head_match")
            helper = [
                "run",
                "--rm",
                "--pull=never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
            ]
            self.run(
                helper
                + [
                    "--cap-add",
                    "CHOWN",
                    "-v",
                    names["uploads"] + ":/target",
                    "redis:7-alpine",
                    "chown",
                    "10001:10001",
                    "/target",
                ]
            )
            self.run(
                helper
                + [
                    "--user",
                    "10001:10001",
                    "-i",
                    "-v",
                    names["uploads"] + ":/target",
                    "redis:7-alpine",
                    "tar",
                    "xzpf",
                    "-",
                    "-C",
                    "/target",
                ],
                data=(path / "uploads.tar.gz").read_bytes(),
            )
            permissions = []
            for name, metadata in sorted(
                m["uploads"].items(),
                key=lambda item: len(PurePosixPath(item[0]).parts),
                reverse=True,
            ):
                permissions.extend([format(metadata["mode"], "o"), "/target/" + name])
            for offset in range(0, len(permissions), 400):
                self.run(
                    helper
                    + [
                        "--user",
                        "10001:10001",
                        "-v",
                        names["uploads"] + ":/target",
                        "redis:7-alpine",
                        "sh",
                        "-ec",
                        'while [ "$#" -gt 0 ]; do mode="$1"; file="$2"; shift 2; chmod "$mode" "$file"; done',
                        "recovery",
                        *permissions[offset : offset + 400],
                    ]
                )
            if archive_manifest(self.tar(names["uploads"])) != m["uploads"]:
                raise ValueError("Documentos/permisos restaurados diferentes")
            checks.append("all_document_bytes_modes_and_owners_match")
            ports = ["-p", "127.0.0.1::6379"] if python else []
            self.run(
                [
                    "run",
                    "-d",
                    "--pull=never",
                    "--name",
                    names["redis"],
                    "--label",
                    label,
                    "--network",
                    names["net"],
                    *ports,
                    "redis:7-alpine",
                ]
            )
            config = self.api_environment(names, password, run_id)
            if python:
                api_config = self.native_api(run_dir, path, python, config)
            else:
                private(
                    run_dir / "api.env",
                    "".join(k + "=" + v + "\n" for k, v in config.items()),
                )
                self.run(
                    [
                        "run",
                        "-d",
                        "--pull=never",
                        "--name",
                        names["api"],
                        "--label",
                        label,
                        "--network",
                        names["net"],
                        "--read-only",
                        "--tmpfs",
                        "/tmp:rw,noexec,nosuid,size=32m",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--user",
                        "10001:10001",
                        "--env-file",
                        str(run_dir / "api.env"),
                        "-v",
                        names["uploads"] + ":/app/uploads:ro",
                        "-v",
                        str(local_test.ROOT / "scripts/recovery_probe.py")
                        + ":/recovery_probe.py:ro",
                        api_image,
                    ]
                )
                api_config = {"base": "http://127.0.0.1:8000"}
            docs = json.loads(
                self.sql(
                    "SELECT coalesce(json_agg(json_build_object('id',id,'file_url',file_url)),'[]'::json) FROM rider_documents"
                )
            )
            document = None
            for doc in docs:
                file = doc["file_url"].removeprefix("/uploads/")
                metadata = m["uploads"].get(file)
                if metadata and metadata["kind"] == "file":
                    document = {"id": doc["id"], "sha256": metadata["sha256"]}
                    break
            api_config.update(account=account, document=document)
            probe_command = (
                [python, str(local_test.ROOT / "scripts/recovery_probe.py")]
                if python
                else self.docker
                + ["exec", "-i", names["api"], "python", "/recovery_probe.py"]
            )
            for _ in range(60):
                if self.process and self.process.poll() is not None:
                    raise ValueError(
                        "El proceso API restaurado terminó antes de estar listo"
                    )
                result = subprocess.run(
                    probe_command + ["--ready"],
                    input=json.dumps(api_config).encode(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if k in ("PATH", "LANG", "LC_ALL")
                    },
                )
                if result.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise ValueError(
                    "No se confirmó el arranque y acceso de la API restaurada"
                )
            result = subprocess.run(
                probe_command,
                input=json.dumps(api_config).encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode:
                private(
                    run_dir / "probe-error.private",
                    result.stdout.decode(errors="replace"),
                )
                raise ValueError(
                    "La prueba funcional restaurada falló; revisar diagnóstico privado"
                )
            checks += json.loads(result.stdout)["checks"]
            after = self.restored_tables()
            if any(after.get(t) != m["tables"].get(t) for t in FINANCIAL_TABLES):
                raise ValueError(
                    "Las lecturas cambiaron historia operativa o monetaria"
                )
            checks.append("api_reads_preserve_operational_financial_history")
            report = {
                "version": 1,
                "run_id": run_id,
                "backup_id": backup_id,
                "checks": checks,
                "errors": [],
                "tables": len(m["tables"]),
                "rows": sum(t["rows"] for t in m["tables"].values()),
                "documents": sum(t["kind"] == "file" for t in m["uploads"].values()),
                "mode": "native_posix" if python else "isolated_container",
                "no_source_writes": True,
                "no_seed_or_migration": True,
                "production_readiness": False,
            }
        except Exception as error:
            private(
                run_dir / "failure.private", type(error).__name__ + ": " + str(error)
            )
            raise
        finally:
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.stop(run_id)
            self.state["status"] = "verified_stopped" if report else "failed_stopped"
            state_file.write_text(json.dumps(self.state, indent=2))
        report["containers_stopped"] = True
        report["volumes_retained"] = True
        private(run_dir / "result.json", json.dumps(report, indent=2))
        return report

    def api_environment(self, names, password, run_id):
        return {
            "APP_ENV": "testing",
            "PYTHONDONTWRITEBYTECODE": "1",
            "ENVIRONMENT": "testing",
            "SECRET_KEY": secrets.token_hex(48),
            "DATABASE_URL": "postgresql+asyncpg://local_test:"
            + password
            + "@"
            + names["db"]
            + ":5432/test_recovery",
            "DATABASE_URL_SYNC": "postgresql://local_test:"
            + password
            + "@"
            + names["db"]
            + ":5432/test_recovery",
            "REDIS_URL": "redis://" + names["redis"] + ":6379/0",
            "CELERY_BROKER_URL": "redis://" + names["redis"] + ":6379/0",
            "CELERY_RESULT_BACKEND": "redis://" + names["redis"] + ":6379/0",
            "REDIS_HOST": names["redis"],
            "REDIS_PORT": "6379",
            "LOCAL_TEST_ID": self.source["instance"],
            "TRACKING_SCHEDULER_ENABLED": "false",
            "EMAILS_ENABLED": "false",
            "NOTIFICATIONS_ENABLED": "false",
            "ENABLE_ELECTRONIC_INVOICING": "false",
            "FISCAL_SANDBOX_ENABLED": "false",
            "CELERY_BEAT_ENABLED": "false",
            "WORKER_SLA_MONITOR_ENABLED": "false",
            "WORKER_PRODUCTIVITY_ENABLED": "false",
            "WORKER_REPORTS_ENABLED": "false",
            "WORKER_NOTIFICATION_RETRY_ENABLED": "false",
            "GOOGLE_MAPS_API_KEY": "",
            "MAPBOX_API_KEY": "",
            "SENTRY_DSN": "",
            "FCM_PROJECT_ID": "",
            "TWILIO_ACCOUNT_SID": "",
            "TWILIO_AUTH_TOKEN": "",
            "DELIVERY360_RECOVERY_ID": run_id,
        }

    def native_api(self, run_dir, path, python, config):
        app = run_dir / "app"
        app.mkdir()
        uploads = app / "uploads"
        uploads.mkdir()
        # All members and sizes have been checked before creating resources.
        with tarfile.open(path / "uploads.tar.gz", "r:gz") as archive:
            for member in archive:
                target = uploads / str(PurePosixPath(member.name))
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
                    target.chmod(member.mode)
        for service, port in [("db", "5432"), ("redis", "6379")]:
            info = json.loads(self.run(["inspect", self.state["names"][service]]))[0]
            binding = info["NetworkSettings"]["Ports"][port + "/tcp"][0]
            if binding["HostIp"] != "127.0.0.1":
                raise ValueError("Puerto de recuperación no local")
            host = self.state["names"][service]
            host_port = binding["HostPort"]
            for key in (
                "DATABASE_URL",
                "DATABASE_URL_SYNC",
                "REDIS_URL",
                "CELERY_BROKER_URL",
                "CELERY_RESULT_BACKEND",
            ):
                config[key] = (
                    config[key]
                    .replace(
                        "@" + host + ":" + port + "/", "@127.0.0.1:" + host_port + "/"
                    )
                    .replace(
                        "//" + host + ":" + port + "/", "//127.0.0.1:" + host_port + "/"
                    )
                )
            if service == "redis":
                config.update(REDIS_HOST="127.0.0.1", REDIS_PORT=host_port)
        config.update(
            PYTHONPATH=str(local_test.ROOT / "backend"),
            PATH=os.environ.get("PATH", ""),
            LANG="C.UTF-8",
        )
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        listener.set_inheritable(True)
        port = listener.getsockname()[1]
        fd = os.open(
            run_dir / "api-log.private", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(fd, "wb") as log:
            self.process = subprocess.Popen(
                [
                    str(Path(python).absolute()),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--fd",
                    str(listener.fileno()),
                ],
                cwd=app,
                env=config,
                stdout=log,
                stderr=subprocess.STDOUT,
                pass_fds=(listener.fileno(),),
                start_new_session=True,
            )
        self.state["native_pid"] = self.process.pid
        (run_dir / "state.json").write_text(json.dumps(self.state, indent=2))
        listener.close()
        return {"base": "http://127.0.0.1:" + str(port)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("backup")
    restore = sub.add_parser("restore")
    restore.add_argument("backup_id", type=identifier)
    mode = restore.add_mutually_exclusive_group(required=True)
    mode.add_argument("--api-image")
    mode.add_argument("--python", type=Path)
    restore.add_argument("--report", type=Path)
    stop = sub.add_parser("stop")
    stop.add_argument("run_id", type=identifier)
    args = parser.parse_args()
    if getattr(args, "report", None) and args.report.exists():
        raise ValueError("No se sobrescribe un reporte existente")
    recovery = Recovery()
    if args.action == "backup":
        print(json.dumps({"backup_id": recovery.backup()}))
    elif args.action == "stop":
        recovery.stop(args.run_id)
        print("Contenedores propios detenidos; volúmenes conservados.")
    else:
        result = recovery.restore(
            args.backup_id, api_image=args.api_image, python=args.python
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            private(args.report, json.dumps(result, indent=2))
        print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        tarfile.TarError,
        json.JSONDecodeError,
    ):
        print(
            "No se completó la recuperación; conserva respaldos y revisa el estado/diagnóstico privado en .delivery360-testing/recovery.",
            file=sys.stderr,
        )
        raise SystemExit(1)
