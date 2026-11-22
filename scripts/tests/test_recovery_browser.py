"""Boundary tests for browser acceptance; real images and Chromium run in CI."""

import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from scripts import recovery, recovery_browser as browser


class RestoredFrontendTests(unittest.TestCase):
    def test_only_expected_loopback_origins_are_accepted(self):
        for url in [
            "http://localhost:8088/api/v1/orders",
            "http://127.0.0.1:8088/api/v1/orders",
        ]:
            self.assertTrue(browser.local_target(url, 8088))
        for url in [
            "https://localhost:8088",
            "http://localhost:8089",
            "http://127.0.0.1:8088@evil.test",
            "http://user:secret@localhost:8088",
            "http://localhost.evil:8088",
            "http://[::1]:8088",
            "http://[invalid",
        ]:
            with self.subTest(url=url):
                self.assertFalse(browser.local_target(url, 8088))

    def test_api_mutation_guard_allows_session_but_rejects_order_zone_and_money_writes(
        self,
    ):
        base = "http://localhost:8088/api/v1"
        for path in [
            "/auth/login",
            "/auth/refresh",
            "/auth/logout",
            "/notifications/read",
        ]:
            self.assertTrue(browser.request_policy(base + path, "POST", 8088, 3088))
        for method, path in [
            ("POST", "/orders"),
            ("PATCH", "/orders/id/status"),
            ("PUT", "/zones/id/bonus-factor/exact"),
            ("POST", "/payouts"),
        ]:
            self.assertFalse(browser.request_policy(base + path, method, 8088, 3088))
        self.assertTrue(browser.request_policy(base + "/orders", "OPTIONS", 8088, 3088))

    def test_wrong_baked_api_url_is_blocked_before_credentials_are_sent(self):
        for url in [
            "http://localhost:3088/api/v1/auth/login",
            "https://production.test/api/v1/auth/login",
            "http://localhost:9999/api/v1/auth/login",
        ]:
            self.assertFalse(browser.request_policy(url, "POST", 8088, 3088))
        self.assertTrue(
            browser.request_policy(
                "http://127.0.0.1:3088/_next/static/a.js", "GET", 8088, 3088
            )
        )
        self.assertFalse(browser.request_policy("http://[invalid", "GET", 8088, 3088))

    def test_websocket_policy_can_limit_browser_messages_to_heartbeat(self):
        self.assertTrue(browser.heartbeat('{"type":"ping"}'))
        for message in [
            "ping",
            "{}",
            '{"type":"pay"}',
            '{"type":"ping","amount":10}',
            b"bad",
        ]:
            self.assertFalse(browser.heartbeat(message))
        self.assertTrue(
            browser.local_target(
                "ws://localhost:8088/api/v1/notifications/ws?token=private",
                8088,
                ("ws",),
            )
        )
        self.assertFalse(
            browser.local_target(
                "ws://other.test:8088/api/v1/notifications/ws?token=private",
                8088,
                ("ws",),
            )
        )

    def test_invalid_or_duplicate_ports_do_not_reserve_any_socket(self):
        for ports in [(8088, 8088), (80, 3088), (8088, 65536)]:
            with patch.object(browser.socket, "socket") as sock, self.assertRaises(
                ValueError
            ):
                browser.PortGuards(*ports)
            sock.assert_not_called()

    def test_ipv4_conflict_releases_reserved_socket(self):
        sock = MagicMock()
        sock.bind.side_effect = OSError(errno.EADDRINUSE, "busy")
        with patch.object(
            browser.socket, "socket", return_value=sock
        ), self.assertRaises(ValueError):
            browser.PortGuards(8088, 3088)
        sock.close.assert_called_once()

    def test_ipv6_foreign_service_is_not_silently_ignored(self):
        api, ipv6 = MagicMock(), MagicMock()
        ipv6.bind.side_effect = OSError(errno.EADDRINUSE, "busy")
        with patch.object(browser.socket, "has_ipv6", True), patch.object(
            browser.socket, "socket", side_effect=[api, ipv6]
        ), self.assertRaises(ValueError):
            browser.PortGuards(8088, 3088)
        api.close.assert_called_once()
        ipv6.close.assert_called_once()

    def test_ipv6_reservations_remain_until_browser_is_stopped(self):
        api, api6, web, web6 = [MagicMock() for _ in range(4)]
        with patch.object(browser.socket, "has_ipv6", True), patch.object(
            browser.socket, "socket", side_effect=[api, api6, web, web6]
        ):
            guards = browser.PortGuards(8088, 3088)
            guards.release_ipv4(8088)
            api.close.assert_called_once()
            api6.close.assert_not_called()
            web6.close.assert_not_called()
            guards.close()
        api6.close.assert_called_once()
        web.close.assert_called_once()
        web6.close.assert_called_once()

    def test_missing_ipv6_stack_keeps_ipv4_guards(self):
        api, web = MagicMock(), MagicMock()
        with patch.object(browser.socket, "has_ipv6", True), patch.object(
            browser.socket,
            "socket",
            side_effect=[
                api,
                OSError(errno.EAFNOSUPPORT, "disabled"),
                web,
                OSError(errno.EAFNOSUPPORT, "disabled"),
            ],
        ):
            guards = browser.PortGuards(8088, 3088)
            self.assertEqual(set(guards.ipv4), {8088, 3088})
            guards.close()
        api.close.assert_called_once()
        web.close.assert_called_once()

    def test_published_ports_must_match_owned_container_and_exact_ipv4_binding(self):
        tool = object.__new__(recovery.Recovery)
        tool.state = {"id": "a" * 12}

        def info(label="a" * 12, host="127.0.0.1", port="8088"):
            return json.dumps(
                [
                    {
                        "Config": {"Labels": {recovery.LABEL: label}},
                        "NetworkSettings": {
                            "Ports": {"8000/tcp": [{"HostIp": host, "HostPort": port}]}
                        },
                    }
                ]
            ).encode()

        tool.run = MagicMock(return_value=info())
        tool.verify_binding("owned", 8000, 8088)
        for value in [info(label="b" * 12), info(host="0.0.0.0"), info(port="9999")]:
            tool.run = MagicMock(return_value=value)
            with self.assertRaises(ValueError):
                tool.verify_binding("owned", 8000, 8088)

    def test_unsupported_frontend_options_fail_before_docker_changes(self):
        tool = object.__new__(recovery.Recovery)
        tool.run = MagicMock()
        for options in [
            dict(web_image="web", python="/venv/python"),
            dict(chromium="/chromium"),
            dict(browser_artifacts="/out"),
        ]:
            with self.assertRaises(ValueError):
                tool.restore("a" * 12, **options)
        tool.run.assert_not_called()

    def test_existing_browser_artifacts_are_preserved(self):
        tool = object.__new__(recovery.Recovery)
        tool.run = MagicMock()
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            tool.restore(
                "a" * 12, api_image="api", web_image="web", browser_artifacts=Path(temp)
            )
        tool.run.assert_not_called()

    def test_stop_handles_owned_web_without_removing_any_volumes(self):
        with tempfile.TemporaryDirectory() as temp:
            tool = object.__new__(recovery.Recovery)
            tool.root = Path(temp)
            rid = "a" * 12
            tool.run = MagicMock(
                side_effect=[
                    b"web-id\n",
                    json.dumps(
                        [
                            {
                                "Config": {"Labels": {recovery.LABEL: rid}},
                                "Name": "/delivery360-recovery-" + rid + "-web",
                            }
                        ]
                    ).encode(),
                    b"",
                ]
            )
            tool.stop(rid)
            self.assertEqual(
                tool.run.call_args_list[-1].args[0], ["stop", "-t", "10", "web-id"]
            )


if __name__ == "__main__":
    unittest.main()
