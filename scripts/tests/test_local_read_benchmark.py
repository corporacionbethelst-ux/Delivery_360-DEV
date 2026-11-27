"""Boundaries, failure evidence and concurrent metrics without user data or Docker."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from scripts import local_read_benchmark as bench


class BenchmarkTests(unittest.TestCase):
    def tool(self, *, port=8088, marker="a" * 16):
        tool = Mock(
            source={"instance": "a" * 16, "api_port": port},
            docker=["docker"],
            compose=["docker", "compose"],
        )

        def execute(args):
            if "ps" in args:
                return b"bbbbbbbbbbbb\n"
            template = args[args.index("--format") + 1]
            return {
                "{{json .Config.Labels}}": json.dumps(
                    {
                        "com.docker.compose.project": "delivery360-local-test-"
                        + "a" * 16,
                        "com.docker.compose.service": "api",
                    }
                ),
                "{{.State.Running}}": "true",
                "{{json .NetworkSettings.Ports}}": json.dumps(
                    {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}
                ),
                "{{.Image}}": "sha256:" + "c" * 64,
            }[template].encode()

        tool.run.side_effect = execute
        tool.source_sql.return_value = marker
        tool.source_tables.return_value = {
            name: {"rows": 1, "sha256": "digest"}
            for name in bench.recovery.FINANCIAL_TABLES
        }
        return tool

    def test_target_requires_owned_container_exact_port_and_database_marker(self):
        tool = self.tool()
        self.assertEqual(bench.verify_target(tool), "sha256:" + "c" * 64)
        tool.source_sql.return_value = "different"
        with self.assertRaises(ValueError):
            bench.verify_target(tool)

    def test_foreign_service_and_public_port_are_rejected_before_http(self):
        for template, value in [
            (
                "{{json .Config.Labels}}",
                json.dumps(
                    {
                        "com.docker.compose.project": "other",
                        "com.docker.compose.service": "api",
                    }
                ).encode(),
            ),
            (
                "{{json .NetworkSettings.Ports}}",
                b'{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8088"}]}',
            ),
            ("{{.State.Running}}", b"false"),
        ]:
            with self.subTest(template=template):
                tool = self.tool()
                original = tool.run.side_effect
                tool.run.side_effect = lambda args: (
                    value if template in args else original(args)
                )
                with patch.object(bench, "Client") as client, self.assertRaises(
                    ValueError
                ):
                    bench.run(tool)
                client.assert_not_called()

    def test_multiple_or_missing_containers_are_rejected(self):
        for ids in (b"", b"bbbbbbbbbbbb cccccccccccc", b"not-a-container"):
            tool = self.tool()
            tool.run.side_effect = None
            tool.run.return_value = ids
            with self.assertRaises(ValueError):
                bench.verify_target(tool)

    def test_samples_and_workers_are_bounded_before_docker(self):
        for samples, workers in [
            (0, 4),
            (25, 4),
            (4, 4),
            (True, 4),
            (12, 1),
            (12, 5),
            (12, True),
        ]:
            tool = self.tool()
            with self.subTest(samples=samples, workers=workers), self.assertRaises(
                ValueError
            ):
                bench.run(tool, samples, workers)
            tool.run.assert_not_called()

    def test_existing_report_is_never_overwritten_or_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "report.json"
            output.write_text("preserved")
            with patch(
                "sys.argv", ["benchmark", "--output", str(output)]
            ), patch.object(bench.recovery, "Recovery") as tool:
                with self.assertRaises(ValueError):
                    bench.main()
                tool.assert_not_called()
            self.assertEqual(output.read_text(), "preserved")

    def test_request_allowlist_forbids_external_paths_and_business_posts(self):
        client = bench.Client(8088)
        with patch.object(bench, "build_opener") as opener:
            for path, body in [
                ("https://other.test", None),
                ("//other.test", None),
                ("/api/v1/orders", {}),
                (bench.PATHS["orders"], {}),
            ]:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    client.request(path, body)
            opener.assert_not_called()

    def response(self, raw, code=200):
        response = Mock(code=code)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = raw
        return response

    def test_read_requests_use_loopback_get_and_bypass_proxies(self):
        client = bench.Client(8088)
        client.token = "private-token"
        opener = Mock()
        opener.open.return_value = self.response(b"[]")
        with patch.object(bench, "build_opener", return_value=opener) as build:
            status, data, error = client.request(bench.PATHS["orders"])
        request = opener.open.call_args.args[0]
        self.assertEqual(
            request.full_url, "http://127.0.0.1:8088" + bench.PATHS["orders"]
        )
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsNone(error)
        self.assertEqual((status, data), (200, []))

    def test_redirects_are_blocked_even_within_the_same_host(self):
        handler = bench.recovery_probe.NoRedirect()
        for target in ("http://127.0.0.1:8088/else", "https://foreign.test"):
            with self.assertRaises(ValueError):
                handler.redirect_request(
                    Request("http://127.0.0.1:8088"), None, 302, "", {}, target
                )

    def test_bad_payloads_and_http_errors_are_sanitized(self):
        for raw, expected in [
            (b"private-exception", "invalid_json"),
            (b"null", "unexpected_shape"),
            (b"x" * (bench.MAX_BODY + 1), "response_too_large"),
        ]:
            opener = Mock()
            opener.open.return_value = self.response(raw)
            with patch.object(bench, "build_opener", return_value=opener):
                result = bench.Client(8088).sample("orders")
            self.assertEqual(result["error"], expected)
            self.assertNotIn("private-exception", json.dumps(result))
        opener.open.side_effect = HTTPError(
            "http://127.0.0.1:8088", 429, "private", {}, io.BytesIO(b"private-body")
        )
        with patch.object(bench, "build_opener", return_value=opener):
            result = bench.Client(8088).sample("orders")
        self.assertEqual((result["status"], result["error"]), (429, "http_status"))
        self.assertNotIn("private", json.dumps(result))

    def test_transport_failure_preserves_no_exception_text_or_token(self):
        client = bench.Client(8088)
        client.token = "private-token"
        with patch.object(client, "request", side_effect=RuntimeError("private-token")):
            result = client.sample("zones")
        self.assertEqual(result["error"], "transport")
        self.assertNotIn("private-token", json.dumps(result))

    def test_percentiles_include_only_success_and_keep_failure_denominator(self):
        samples = [{"error": None, "milliseconds": value} for value in range(1, 21)] + [
            {"error": "http_status", "milliseconds": 999}
        ]
        result = bench.summarize(samples, 2)
        self.assertEqual(
            (result["requests"], result["succeeded"], result["failed"]), (21, 20, 1)
        )
        self.assertEqual(result["completed_requests_per_second"], 10.5)
        self.assertEqual(
            result["successful_latency_ms"],
            {"p50": 10, "p95": 19, "p99": 20, "max": 20},
        )
        self.assertIsNone(bench.summarize(samples[-1:], 2)["successful_latency_ms"])

    def exercise(self, *, mutation=False, errors=False):
        tool = self.tool()
        before = tool.source_tables.return_value
        if mutation:
            after = {**before, "orders": {"rows": 2, "sha256": "changed"}}
            tool.source_tables.side_effect = [before, after]
        active = peak = 0
        lock = threading.Lock()

        def sample(name):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.005)
            with lock:
                active -= 1
            return {
                "endpoint": name,
                "status": 429 if errors else 200,
                "error": "http_status" if errors else None,
                "milliseconds": 5,
            }

        client = Mock()
        client.request.side_effect = [
            (200, {"checks": {"database": True, "redis": True}}, None),
            (200, {"access_token": "private-token"}, None),
            (200, {"role": "SUPERADMIN"}, None),
        ]
        client.sample.side_effect = sample
        with tempfile.TemporaryDirectory() as temp:
            account = Path(temp) / "credentials.json"
            account.write_text(
                json.dumps(
                    {
                        "SUPERADMIN": {
                            "email": "private-user",
                            "password": "private-password",
                        }
                    }
                )
            )
            with patch.object(bench.local_test, "ACCOUNTS", account), patch.object(
                bench, "Client", return_value=client
            ):
                result = bench.run(tool)
        return result, client, peak

    def test_real_thread_pool_is_bounded_and_report_has_no_credentials(self):
        result, client, peak = self.exercise()
        self.assertTrue(result["passed"])
        self.assertLessEqual(peak, 4)
        self.assertGreater(peak, 1)
        self.assertEqual(client.sample.call_count, 24)
        self.assertEqual([stage["requests"] for stage in result["stages"]], [12, 12])
        self.assertFalse(result["production_capacity_verified"])
        for private in ("private-token", "private-password", "private-user"):
            self.assertNotIn(private, json.dumps(result))

    def test_changed_financial_snapshot_fails_even_when_http_succeeds(self):
        result, _, _ = self.exercise(mutation=True)
        self.assertFalse(result["passed"])
        self.assertFalse(result["protected_data_unchanged"])

    def test_http_failures_remain_in_report_and_fail_acceptance(self):
        result, client, _ = self.exercise(errors=True)
        self.assertFalse(result["passed"])
        self.assertTrue(result["protected_data_unchanged"])
        self.assertEqual(client.sample.call_count, 24)
        self.assertEqual(sum(stage["failed"] for stage in result["stages"]), 24)


if __name__ == "__main__":
    unittest.main()
