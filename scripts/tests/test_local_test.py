"""Local lab secrets, instance preservation and Docker/HTTP boundaries."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.request import Request

from scripts import local_test


class LocalTestCommands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(local_test, key, self.root / name)
            for key, name in [
                ("STATE", "state"),
                ("CONFIG", "state/config.json"),
                ("ENV", "state/runtime.env"),
                ("ACCOUNTS", "state/credentials.json"),
            ]
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self.temp.cleanup)
        for item in self.patches:
            self.addCleanup(item.stop)

    def initialize(self):
        with contextlib.redirect_stdout(io.StringIO()):
            local_test.initialize(3088, 8088)

    def test_secrets_are_generated_privately_without_modifying_repo_env(self):
        self.initialize()
        config = local_test.configuration()
        self.assertEqual(config["web_port"], 3088)
        users = json.loads(local_test.ACCOUNTS.read_text())
        self.assertEqual(len(users), 6)
        self.assertGreaterEqual(len(users["SUPERADMIN"]["password"]), 24)
        self.assertNotIn("admin123", local_test.ACCOUNTS.read_text())
        if os.name != "nt":
            self.assertEqual(local_test.ENV.stat().st_mode & 0o777, 0o600)

    def test_reinitialization_preserves_instance_passwords_and_ports(self):
        self.initialize()
        before = [
            p.read_bytes()
            for p in (local_test.CONFIG, local_test.ENV, local_test.ACCOUNTS)
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            local_test.initialize(4000, 9000)
        self.assertEqual(
            before,
            [
                p.read_bytes()
                for p in (local_test.CONFIG, local_test.ENV, local_test.ACCOUNTS)
            ],
        )

    def test_partial_initialization_is_not_overwritten(self):
        local_test.STATE.mkdir()
        local_test.ENV.write_text("preserved")
        with self.assertRaises(ValueError):
            self.initialize()
        self.assertEqual(local_test.ENV.read_text(), "preserved")

    def test_invalid_ports_do_not_create_state(self):
        for ports in [(80, 8088), (3088, 3088), (65536, 8088)]:
            with self.subTest(ports=ports), self.assertRaises(ValueError):
                local_test.initialize(*ports)
        self.assertFalse(local_test.CONFIG.exists())

    def test_missing_configuration_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "init"):
            local_test.configuration()

    def test_invalid_instance_names_are_rejected(self):
        self.initialize()
        data = local_test.configuration()
        data["instance"] = "other-project;delete"
        local_test.CONFIG.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            local_test.configuration()

    @patch.dict(
        os.environ, {"DOCKER_HOST": "tcp://production.example:2376"}, clear=True
    )
    def test_remote_daemon_is_refused(self):
        with self.assertRaisesRegex(ValueError, "remoto"):
            local_test.local_docker()

    @patch.dict(os.environ, {"DOCKER_HOST": "unix:///var/run/docker.sock"}, clear=True)
    def test_local_socket_is_selected_explicitly(self):
        self.assertEqual(
            local_test.local_docker(),
            ["docker", "--host", "unix:///var/run/docker.sock"],
        )

    def test_project_is_private_and_down_never_requests_volume_deletion(self):
        self.initialize()
        data = local_test.configuration()
        command = local_test.compose(data, ["docker"])
        self.assertIn("delivery360-local-test-" + data["instance"], command)
        self.assertIn(str(local_test.ENV), command)
        with patch("sys.argv", ["local_test.py", "down"]), patch.object(
            local_test, "local_docker", return_value=["docker"]
        ), patch.object(
            local_test.subprocess, "run"
        ) as run, contextlib.redirect_stdout(
            io.StringIO()
        ):
            local_test.main()
        args = run.call_args.args[0]
        self.assertEqual(args[-1], "down")
        self.assertNotIn("-v", args)
        self.assertNotIn("--volumes", args)

    def test_start_waits_for_dependencies_and_releases_initializer_before_api(self):
        self.initialize()
        with patch("sys.argv", ["local_test.py", "up", "--no-build"]), patch.object(
            local_test, "local_docker", return_value=["docker"]
        ), patch.object(local_test.subprocess, "run") as run, patch.object(
            local_test, "check"
        ) as check:
            local_test.main()
        commands = [item.args[0] for item in run.call_args_list][1:]
        self.assertEqual(len(commands), 5)
        self.assertEqual(commands[0][-2:], ["test-db", "test-redis"])
        self.assertIn("--wait", commands[0])
        self.assertEqual(commands[1][-5:], ["rm", "--stop", "--force", "web", "api"])
        self.assertEqual(commands[2][-4:], ["run", "--rm", "--no-deps", "setup"])
        self.assertEqual(commands[3][-2:], ["--no-deps", "api"])
        self.assertEqual(commands[4][-2:], ["--no-deps", "web"])
        check.assert_called_once()

    def test_failed_initialization_never_starts_api_or_reports_readiness(self):
        self.initialize()
        error = local_test.subprocess.CalledProcessError(1, ["setup"])
        with patch("sys.argv", ["local_test.py", "up", "--no-build"]), patch.object(
            local_test, "local_docker", return_value=["docker"]
        ), patch.object(
            local_test.subprocess, "run", side_effect=[None, None, None, error]
        ) as run, patch.object(
            local_test, "check"
        ) as check:
            with self.assertRaises(local_test.subprocess.CalledProcessError):
                local_test.main()
        self.assertEqual(run.call_count, 4)
        check.assert_not_called()

    def test_redirect_cannot_send_local_credentials_to_other_origin(self):
        handler = local_test.LocalRedirect()
        request = Request("http://localhost:8088/api/v1/auth/me")
        for destination in ["https://external.example/", "http://localhost:9999/"]:
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "", {}, destination)

    @patch.dict(
        os.environ,
        {"LOCAL_TEST_PASSWORD": "another-lab", "HTTPS_PROXY": "preserved-proxy"},
        clear=True,
    )
    def test_inherited_lab_variables_do_not_override_private_env_file(self):
        env = local_test.compose_environment()
        self.assertNotIn("LOCAL_TEST_PASSWORD", env)
        self.assertEqual(env["HTTPS_PROXY"], "preserved-proxy")

    def test_check_refuses_unready_web_before_trying_credentials(self):
        response = MagicMock()
        response.__enter__.return_value.code = 503
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(
            local_test, "build_opener", return_value=opener
        ), patch.object(local_test, "api_request") as request:
            with self.assertRaisesRegex(ValueError, "interfaz"):
                local_test.check({"web_port": 3088, "api_port": 8088})
        request.assert_not_called()

    def test_check_refuses_unready_dependencies_with_a_healthy_web(self):
        response = MagicMock()
        response.__enter__.return_value.code = 200
        response.__enter__.return_value.headers = {"Content-Type": "text/html"}
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(
            local_test, "build_opener", return_value=opener
        ), patch.object(
            local_test,
            "api_request",
            return_value=(503, {"checks": {"database": False, "redis": True}}),
        ) as request:
            with self.assertRaisesRegex(ValueError, "PostgreSQL"):
                local_test.check({"web_port": 3088, "api_port": 8088})
        self.assertEqual(request.call_count, 1)

    def test_ready_check_uses_one_login_so_manual_testing_keeps_its_rate_budget(self):
        self.initialize()
        response = MagicMock()
        response.__enter__.return_value.code = 200
        response.__enter__.return_value.headers = {"Content-Type": "text/html"}
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(
            local_test, "build_opener", return_value=opener
        ), patch.object(
            local_test,
            "api_request",
            side_effect=[
                (200, {"checks": {"database": True, "redis": True}}),
                (200, {"access_token": "synthetic-test-token"}),
                (200, {"role": "SUPERADMIN"}),
            ],
        ) as request, contextlib.redirect_stdout(
            io.StringIO()
        ):
            local_test.check(local_test.configuration())
        paths = [call.args[1] for call in request.call_args_list]
        self.assertEqual(paths.count("/api/v1/auth/login"), 1)


if __name__ == "__main__":
    unittest.main()
