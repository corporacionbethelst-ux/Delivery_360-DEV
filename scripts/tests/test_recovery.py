"""Backup integrity and restore boundaries, without touching Docker or user data."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from scripts import recovery, recovery_probe


def tar_bytes(name="documents/test.pdf", kind=tarfile.REGTYPE, uid=10001, mode=0o640):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        m = tarfile.TarInfo(name)
        m.type = kind
        m.uid = m.gid = uid
        m.mode = mode
        payload = b"%PDF restored"
        m.size = len(payload) if m.isfile() else 0
        if m.issym() or m.islnk():
            m.linkname = "/outside"
        tar.addfile(m, io.BytesIO(payload))
    return data.getvalue()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self):
        p = self.root / "backups" / "aaaaaaaaaaaa"
        p.mkdir(parents=True)
        files = {"database.dump": b"PGDMP sample", "uploads.tar.gz": tar_bytes()}
        for name, data in files.items():
            (p / name).write_bytes(data)
        m = dict(
            version=1,
            backup_id=p.name,
            source_instance="1" * 16,
            files={
                n: {"sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()
            },
            uploads=recovery.archive_manifest(files["uploads.tar.gz"]),
        )
        (p / "manifest.json").write_text(json.dumps(m))
        return p, m

    def test_private_files_are_exclusive_and_preserve_existing_data(self):
        p = self.root / "private"
        recovery.private(p, "preserved")
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            recovery.private(p, "lost")
        self.assertEqual(p.read_text(), "preserved")

    def test_empty_tables_and_row_order_are_compared_correctly(self):
        a = "COPY public.empty (id) FROM stdin;\n\\.\nCOPY public.rows (id, value) FROM stdin;\n2\tb\n1\ta\n\\.\n"
        b = a.replace("2\tb\n1\ta", "1\ta\n2\tb")
        self.assertEqual(recovery.table_fingerprints(a), recovery.table_fingerprints(b))
        self.assertEqual(recovery.table_fingerprints(a)["empty"]["rows"], 0)
        self.assertNotEqual(
            recovery.table_fingerprints(a),
            recovery.table_fingerprints(a.replace("1\ta", "1\tc")),
        )

    def test_archive_preserves_permissions_owner_and_bytes(self):
        v = recovery.archive_manifest(tar_bytes())["documents/test.pdf"]
        self.assertEqual(v["mode"], 0o640)
        self.assertEqual(v["uid"], 10001)
        self.assertEqual(v["sha256"], hashlib.sha256(b"%PDF restored").hexdigest())

    def test_unsafe_tar_members_are_rejected(self):
        for n, t, u, m in [
            ("../escape", tarfile.REGTYPE, 10001, 0o644),
            ("/absolute", tarfile.REGTYPE, 10001, 0o644),
            ("a\\b", tarfile.REGTYPE, 10001, 0o644),
            ("sym", tarfile.SYMTYPE, 10001, 0o644),
            ("hard", tarfile.LNKTYPE, 10001, 0o644),
            ("dev", tarfile.CHRTYPE, 10001, 0o644),
            ("root", tarfile.REGTYPE, 0, 0o644),
            ("suid", tarfile.REGTYPE, 10001, 0o4644),
        ]:
            with self.subTest(name=n), self.assertRaises(ValueError):
                recovery.archive_manifest(tar_bytes(n, t, u, m))

    def test_hash_failure_precedes_any_docker_mutation(self):
        p, m = self.bundle()
        (p / "database.dump").write_bytes(b"corrupt")
        tool = object.__new__(recovery.Recovery)
        tool.root = self.root
        tool.source = {"instance": "1" * 16}
        tool.run = MagicMock()
        with self.assertRaises(ValueError):
            tool.restore(p.name, api_image="local-api")
        tool.run.assert_not_called()

    def test_archive_manifest_mismatch_is_rejected(self):
        p, m = self.bundle()
        self.assertEqual(recovery.load_bundle(p), m)
        m["uploads"] = {}
        (p / "manifest.json").write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            recovery.load_bundle(p)

    def test_backup_symlinks_and_identifiers_cannot_escape(self):
        p, m = self.bundle()
        (p / "database.dump").unlink()
        (p / "database.dump").symlink_to(self.root / "other")
        with self.assertRaises(ValueError):
            recovery.load_bundle(p)
        for value in ["../main", "a" * 12 + ";rm", "", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                recovery.identifier(value)

    def test_stop_refuses_foreign_names_and_labels(self):
        tool = object.__new__(recovery.Recovery)
        tool.root = self.root
        tool.run = MagicMock(
            side_effect=[
                b"container\n",
                json.dumps(
                    [
                        {
                            "Config": {"Labels": {recovery.LABEL: "b" * 12}},
                            "Name": "/delivery360_db",
                        }
                    ]
                ).encode(),
            ]
        )
        with self.assertRaises(ValueError):
            tool.stop("a" * 12)
        self.assertFalse(any(c.args[0][0] == "stop" for c in tool.run.call_args_list))

    def test_stop_preserves_volumes_and_only_stops_owned_container(self):
        tool = object.__new__(recovery.Recovery)
        tool.root = self.root
        rid = "a" * 12
        tool.run = MagicMock(
            side_effect=[
                b"container\n",
                json.dumps(
                    [
                        {
                            "Config": {"Labels": {recovery.LABEL: rid}},
                            "Name": "/delivery360-recovery-" + rid + "-db",
                        }
                    ]
                ).encode(),
                b"",
            ]
        )
        tool.stop(rid)
        self.assertEqual(
            tool.run.call_args_list[-1].args[0], ["stop", "-t", "10", "container"]
        )

    def test_backup_requires_an_offline_application(self):
        tool = object.__new__(recovery.Recovery)
        tool.source = {"instance": "1" * 16}
        tool.docker = ["docker"]
        tool.compose = ["docker", "compose"]
        tool.source_sql = MagicMock(return_value="1" * 16)
        tool.run = MagicMock(return_value=b"api\ntest-db\n")
        with self.assertRaisesRegex(ValueError, "Detén"):
            tool.source_ready()

    def test_readiness_waits_for_postgres_as_pid_one(self):
        tool = object.__new__(recovery.Recovery)
        tool.docker = ["docker"]
        tool.state = {"names": {"db": "owned"}}
        tool.env = {}
        with patch.object(
            recovery.subprocess,
            "run",
            side_effect=[MagicMock(returncode=1), MagicMock(returncode=0)],
        ) as run, patch.object(recovery.time, "sleep"):
            tool.wait_db()
        self.assertEqual(run.call_count, 2)
        self.assertIn("/proc/1/comm", run.call_args.args[0][-1])

    def test_new_api_secret_and_disabled_external_effects(self):
        tool = object.__new__(recovery.Recovery)
        tool.source = {"instance": "1" * 16}
        env = tool.api_environment(
            {"db": "restored", "redis": "cache"}, "private", "a" * 12
        )
        self.assertGreaterEqual(len(env["SECRET_KEY"]), 64)
        for k in [
            "EMAILS_ENABLED",
            "NOTIFICATIONS_ENABLED",
            "TRACKING_SCHEDULER_ENABLED",
            "ENABLE_ELECTRONIC_INVOICING",
            "CELERY_BEAT_ENABLED",
        ]:
            self.assertEqual(env[k], "false")
        self.assertIn("@restored:", env["DATABASE_URL"])
        self.assertEqual(env["TWILIO_AUTH_TOKEN"], "")

    def test_probe_cannot_send_credentials_to_nonlocal_or_userinfo_url(self):
        for base in [
            "https://127.0.0.1:8000",
            "http://127.0.0.1:80@evil.example",
            "http://127.0.0.1:8000/path",
            "http://localhost:8000",
            "http://127.0.0.1:99999",
        ]:
            with self.subTest(base=base), patch.object(
                recovery_probe, "build_opener"
            ) as opener, self.assertRaises(ValueError):
                recovery_probe.probe({"base": base})
            opener.return_value.open.assert_not_called()

    def test_existing_destination_is_refused_before_creating_resources(self):
        p, _ = self.bundle()
        credentials = self.root / "credentials.json"
        credentials.write_text(
            json.dumps({"SUPERADMIN": {"email": "synthetic", "password": "synthetic"}})
        )
        tool = object.__new__(recovery.Recovery)
        tool.root = self.root
        tool.source = {"instance": "1" * 16}
        tool.run = MagicMock(
            side_effect=[b"[]", b"delivery360-recovery-aaaaaaaaaaaa-data\n"]
        )
        with patch.object(recovery.local_test, "ACCOUNTS", credentials), patch.object(
            recovery.secrets, "token_hex", return_value="a" * 12
        ), self.assertRaisesRegex(ValueError, "existente"):
            tool.restore(p.name, api_image="local-api")
        self.assertFalse(any("create" in c.args[0] for c in tool.run.call_args_list))

    def test_duplicate_archive_members_are_refused(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as tar:
            for _ in range(2):
                member = tarfile.TarInfo("duplicate")
                member.uid = member.gid = 10001
                tar.addfile(member)
        with self.assertRaises(ValueError):
            recovery.archive_manifest(output.getvalue())

    def probe_responses(self, document):
        payloads = [
            (200, {"checks": {"database": True, "redis": True}}),
            (401, {}),
            (200, {"access_token": "private-token"}),
            (200, {"role": "SUPERADMIN"}),
            (200, []),
            (200, []),
            (200, {}),
            (401, {}),
            (200, document),
        ]
        responses = []
        for status, payload in payloads:
            response = MagicMock()
            response.code = status
            response.read.return_value = (
                payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            )
            response.__enter__.return_value = response
            responses.append(response)
        opener = MagicMock()
        opener.open.side_effect = responses
        return opener

    def test_functional_probe_checks_auth_and_document_without_exposing_token(self):
        payload = b"%PDF restored"
        opener = self.probe_responses(payload)
        config = {
            "base": "http://127.0.0.1:8000",
            "account": {"email": "synthetic", "password": "private-password"},
            "document": {
                "id": "synthetic",
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
        }
        with patch.object(recovery_probe, "build_opener", return_value=opener):
            checks = recovery_probe.probe(config)
        self.assertEqual(len(checks), 9)
        self.assertNotIn("private-token", json.dumps(checks))
        self.assertNotIn("private-password", json.dumps(checks))

    def test_functional_probe_rejects_changed_document_bytes(self):
        config = {
            "base": "http://127.0.0.1:8000",
            "account": {"email": "synthetic", "password": "private-password"},
            "document": {"id": "synthetic", "sha256": "0" * 64},
        }
        with patch.object(
            recovery_probe, "build_opener", return_value=self.probe_responses(b"wrong")
        ), self.assertRaisesRegex(ValueError, "download"):
            recovery_probe.probe(config)

    def test_docker_failure_keeps_private_diagnostic_without_exposing_it(self):
        tool = object.__new__(recovery.Recovery)
        tool.root, tool.state, tool.docker, tool.env = self.root, None, ["docker"], {}
        result = MagicMock(
            returncode=1, stderr=b"private-database-password", stdout=b""
        )
        with patch.object(
            recovery.subprocess, "run", return_value=result
        ), self.assertRaises(ValueError) as failure:
            tool.run(["info"])
        self.assertNotIn("private-database-password", str(failure.exception))
        logs = list(self.root.glob("backup-diagnostic-*.private"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(logs[0].read_bytes(), b"private-database-password")

    def test_container_probe_supports_private_checkout_without_binding_source_file(
        self,
    ):
        scripts = self.root / "scripts"
        scripts.mkdir()
        source = scripts / "recovery_probe.py"
        recovery.private(source, 'print("trusted probe")')
        tool = object.__new__(recovery.Recovery)
        tool.docker = ["docker"]
        with patch.object(recovery.local_test, "ROOT", self.root):
            command = tool.probe_command({"api": "owned-api"})
        self.assertEqual(
            command[:6], ["docker", "exec", "-i", "owned-api", "python", "-c"]
        )
        self.assertEqual(command[-1], source.read_text())
        self.assertNotIn(str(source), command)


if __name__ == "__main__":
    unittest.main()
