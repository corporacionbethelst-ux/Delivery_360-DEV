from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from scripts.recovery_roles import login_with_budget


class RoleLoginBudgetTests(unittest.TestCase):
    def call(self, responses):
        request = Mock()
        request.post.side_effect = responses
        with patch("scripts.recovery_roles.time.sleep") as sleep:
            result = login_with_budget(
                request,
                "http://127.0.0.1:8088/api/v1/auth/login",
                {"email": "synthetic@example.test", "password": "synthetic"},
            )
        return request, sleep, result

    def test_success_does_not_wait_or_follow_redirects(self):
        request, sleep, result = self.call([SimpleNamespace(status=200)])
        self.assertEqual(result.status, 200)
        sleep.assert_not_called()
        self.assertEqual(request.post.call_args.kwargs["max_redirects"], 0)

    def test_invalid_credentials_are_not_retried(self):
        request, sleep, result = self.call([SimpleNamespace(status=401)])
        self.assertEqual(result.status, 401)
        self.assertEqual(request.post.call_count, 1)
        sleep.assert_not_called()

    def test_rate_limit_waits_without_disabling_protection(self):
        request, sleep, result = self.call(
            [
                SimpleNamespace(status=429, headers={"retry-after": "59"}),
                SimpleNamespace(status=200),
            ]
        )
        sleep.assert_called_once_with(59)
        self.assertEqual(request.post.call_count, 2)
        self.assertEqual(result.status, 200)

    def test_bad_retry_headers_and_repeated_limits_are_bounded(self):
        request, sleep, result = self.call(
            [
                SimpleNamespace(status=429, headers={"retry-after": "bad"}),
                SimpleNamespace(status=429, headers={"retry-after": "9999"}),
                SimpleNamespace(status=429, headers={}),
            ]
        )
        self.assertEqual(request.post.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [60, 60])
        self.assertEqual(result.status, 429)
