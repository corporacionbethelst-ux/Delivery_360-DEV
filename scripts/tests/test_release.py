"""Immutable image selection, plan generation and fail-closed deployment checks."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from scripts import release
import yaml

REPOSITORY = "corporacionbethelst-ux/Delivery_360-DEV"
SHA = "a" * 40
BACKEND = "sha256:" + "b" * 64
FRONTEND = "sha256:" + "c" * 64


class ReleaseTests(unittest.TestCase):
    def metadata(self):
        return release.image_manifest(REPOSITORY, SHA, BACKEND, FRONTEND)

    def run_record(self, **changes):
        return {
            "id": 1,
            "head_sha": SHA,
            "head_branch": "main",
            "event": "push",
            "path": ".github/workflows/ci-cd.yml",
            "head_repository": {"full_name": REPOSITORY},
            "status": "completed",
            "conclusion": "success",
            **changes,
        }

    def reader(self, overrides=None):
        data = {
            "namespace": {},
            "delivery360-runtime": {
                "data": {
                    key: "synthetic-base64"
                    for key in ("DATABASE_URL", "REDIS_URL", "SECRET_KEY")
                }
            },
            "delivery360-tls": {
                "type": "kubernetes.io/tls",
                "data": {"tls.crt": "synthetic", "tls.key": "synthetic"},
            },
            "delivery360-uploads": {
                "status": {"phase": "Bound"},
                "spec": {"accessModes": ["ReadWriteMany"]},
            },
        }
        data.update(overrides or {})
        return lambda arguments: data[
            "namespace" if arguments[1] == "namespace" else arguments[2]
        ]

    def test_full_sha_and_lowercase_repository_make_consistent_tags(self):
        names = release.image_names(REPOSITORY, SHA)
        self.assertEqual(
            names["backend"],
            "ghcr.io/corporacionbethelst-ux/delivery_360-dev/backend:sha-" + SHA,
        )
        for repository in (
            "bad",
            "../repo",
            "owner/..",
            "owner/repo;touch",
            "owner/repo\n",
        ):
            with self.subTest(repository=repository), self.assertRaises(ValueError):
                release.image_names(repository, SHA)
        for sha in ("abc1234", "z" * 40, "a" * 40 + ";id", "a" * 40 + "\n"):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                release.image_names(REPOSITORY, sha)

    def test_artifact_requires_both_digests(self):
        for value in ("latest", "sha256:1234", "sha256:" + "z" * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.image_manifest(REPOSITORY, SHA, value, FRONTEND)
        data = self.metadata()
        for changes in (
            {"revision": "d" * 40},
            {"repository": "foreign/repo"},
            {"api_base": "https://other.invalid"},
            {"extra": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                release.validate_images({**data, **changes}, REPOSITORY, SHA)
        for reference in (
            "ghcr.io/foreign/repo/backend@" + BACKEND,
            "ghcr.io/corporacionbethelst-ux/delivery_360-dev/backend:latest",
        ):
            invalid = deepcopy(data)
            invalid["images"]["backend"] = reference
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                release.validate_images(invalid, REPOSITORY, SHA)

    def test_rendered_resources_share_namespace_and_exact_digests(self):
        for environment, namespace, count in (
            ("staging", "delivery360-staging", 1),
            ("production", "delivery360", 2),
        ):
            with self.subTest(environment=environment):
                plan = release.render(
                    self.metadata(), REPOSITORY, SHA, environment, "app.delivery360.com"
                )
                self.assertEqual(len(plan["items"]), 5)
                self.assertTrue(
                    all(
                        item["metadata"]["namespace"] == namespace
                        for item in plan["items"]
                    )
                )
                for item in plan["items"]:
                    if item["kind"] == "Deployment":
                        self.assertEqual(item["spec"]["replicas"], count)
                        pod = item["spec"]["template"]["spec"]
                        self.assertFalse(pod["automountServiceAccountToken"])
                        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
                        container = pod["containers"][0]
                        self.assertIn("@sha256:", container["image"])
                        self.assertFalse(
                            container["securityContext"]["allowPrivilegeEscalation"]
                        )
                backend = next(
                    item
                    for item in plan["items"]
                    if item["kind"] == "Deployment"
                    and item["metadata"]["name"] == "backend"
                )
                self.assertEqual(
                    backend["spec"]["template"]["spec"]["containers"][0][
                        "readinessProbe"
                    ]["httpGet"]["path"],
                    "/health/ready",
                )
                self.assertNotIn("__", json.dumps(plan))

    def test_render_rejects_host_and_environment_injection(self):
        for host in (
            "localhost",
            "127.0.0.1",
            "https://app.test",
            "app.test:443",
            "a.test/x",
            "a.test\nvalue",
            "*.test",
        ):
            with self.subTest(host=host), self.assertRaises(ValueError):
                release.render(self.metadata(), REPOSITORY, SHA, "staging", host)
        with self.assertRaises(ValueError):
            release.render(
                self.metadata(), REPOSITORY, SHA, "prod", "app.example.invalid"
            )

    def test_latest_ci_run_must_pass_and_come_from_the_expected_workflow(self):
        self.assertEqual(
            release.select_run(
                {"workflow_runs": [self.run_record()]}, REPOSITORY, SHA, "production"
            ),
            1,
        )
        for changes in (
            {"event": "pull_request"},
            {"head_sha": "d" * 40},
            {"path": "other.yml"},
            {"head_branch": "develop"},
            {"head_repository": {"full_name": "foreign/repo"}},
            {"conclusion": "failure"},
            {"conclusion": None, "status": "in_progress"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                release.select_run(
                    {"workflow_runs": [self.run_record(**changes)]},
                    REPOSITORY,
                    SHA,
                    "production",
                )
        with self.assertRaises(ValueError):
            release.select_run(
                {
                    "workflow_runs": [
                        self.run_record(),
                        self.run_record(id=2, conclusion="failure"),
                    ]
                },
                REPOSITORY,
                SHA,
                "staging",
            )
        self.assertEqual(
            release.select_run(
                {"workflow_runs": [self.run_record(head_branch="develop")]},
                REPOSITORY,
                SHA,
                "staging",
            ),
            1,
        )

    def test_preflight_checks_confirmation_context_secrets_and_persistent_storage(self):
        self.assertEqual(
            release.preflight(
                "production",
                "APPLY delivery360",
                "expected",
                self.reader(),
                lambda: "expected",
            ),
            "delivery360",
        )
        for confirmation, context in (
            ("APPLY delivery360-staging", "expected"),
            ("", "expected"),
            ("APPLY delivery360", "other"),
        ):
            with self.subTest(
                confirmation=confirmation, context=context
            ), self.assertRaises(ValueError):
                release.preflight(
                    "production",
                    confirmation,
                    "expected",
                    self.reader(),
                    lambda: context,
                )
        for changes in (
            {"delivery360-runtime": {"data": {}}},
            {"delivery360-tls": {"type": "Opaque", "data": {}}},
            {"delivery360-uploads": {"status": {"phase": "Pending"}}},
            {
                "delivery360-uploads": {
                    "status": {"phase": "Bound"},
                    "spec": {"accessModes": ["ReadWriteOnce"]},
                }
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                release.preflight(
                    "production",
                    "APPLY delivery360",
                    "expected",
                    self.reader(changes),
                    lambda: "expected",
                )

    def test_registry_publication_waits_for_all_quality_and_security_checks(self):
        workflow = yaml.load(
            (release.ROOT / ".github/workflows/ci-cd.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        jobs = workflow["jobs"]
        self.assertEqual(
            set(jobs["release-readiness"]["needs"]),
            {
                "backend-test",
                "frontend-test",
                "frontend-security",
                "backend-security",
                "backend-container",
                "release-contract",
                "frontend-container",
                "local-functional-test",
                "security-scan",
            },
        )
        for name in ("build-backend", "build-frontend"):
            self.assertEqual(jobs[name]["needs"], "release-readiness")
            self.assertEqual(jobs[name]["if"], "github.event_name == 'push'")
        deployment = yaml.load(
            (release.ROOT / ".github/workflows/deploy.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(set(deployment["on"]), {"workflow_dispatch"})
        self.assertEqual(
            deployment["on"]["workflow_dispatch"]["inputs"]["apply"]["default"], "false"
        )
        self.assertEqual(deployment["jobs"]["apply"]["needs"], "plan")

    def test_main_rules_require_the_aggregate_release_check(self):
        data = json.loads((release.ROOT / ".github/rulesets/main.json").read_text())
        rule = next(
            item for item in data["rules"] if item["type"] == "required_status_checks"
        )
        self.assertEqual(
            rule["parameters"]["required_status_checks"],
            [{"context": "release-readiness"}],
        )
        workflow = (release.ROOT / ".github/workflows/ci-cd.yml").read_text()
        self.assertIn("  release-readiness:", workflow)
        self.assertNotIn("deploy-production:", workflow)
        self.assertIn("npm audit --omit=dev --audit-level=moderate", workflow)
        self.assertIn("exit-code: '1'", workflow)


if __name__ == "__main__":
    unittest.main()
