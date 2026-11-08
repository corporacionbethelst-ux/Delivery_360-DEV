#!/usr/bin/env python3
"""Generate digest-pinned release plans. No deployments or migrations are executed."""

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NAMESPACES = {"staging": "delivery360-staging", "production": "delivery360"}


def image_names(repository, revision):
    if (
        not isinstance(repository, str)
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repository
        )
        or repository.split("/")[1] in {".", ".."}
    ):
        raise ValueError("Invalid repository")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A full commit SHA is required")
    return {
        part: f"ghcr.io/{repository.lower()}/{part}:sha-{revision}"
        for part in ("backend", "frontend")
    }


def image_manifest(repository, revision, backend_digest, frontend_digest):
    names = image_names(repository, revision)
    digests = {"backend": backend_digest, "frontend": frontend_digest}
    if any(
        not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
        for value in digests.values()
    ):
        raise ValueError("Both published image digests are required")
    return {
        "schema": 1,
        "repository": repository.lower(),
        "revision": revision,
        "api_base": "/api/v1",
        "images": {
            key: names[key].split(":sha-")[0] + "@" + digests[key] for key in names
        },
    }


def validate_images(data, repository, revision):
    names = image_names(repository, revision)
    if (
        not isinstance(data, dict)
        or set(data) != {"schema", "repository", "revision", "api_base", "images"}
        or data["schema"] != 1
        or data["repository"] != repository.lower()
        or data["revision"] != revision
        or data["api_base"] != "/api/v1"
        or not isinstance(data["images"], dict)
        or set(data["images"]) != set(names)
    ):
        raise ValueError("Artifact does not match the requested release")
    for key, name in names.items():
        expected = re.escape(name.split(":sha-")[0]) + r"@sha256:[0-9a-f]{64}"
        if not isinstance(data["images"][key], str) or not re.fullmatch(
            expected, data["images"][key]
        ):
            raise ValueError("Invalid image reference")


def render(data, repository, revision, environment, host):
    validate_images(data, repository, revision)
    if (
        environment not in NAMESPACES
        or not isinstance(host, str)
        or len(host) > 253
        or not re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
            host,
        )
    ):
        raise ValueError("A known environment and DNS hostname are required")
    if environment == "production" and not host.endswith(".delivery360.com"):
        raise ValueError(
            "Production host must match the current API trusted-host policy"
        )
    replacements = {
        "__NAMESPACE__": NAMESPACES[environment],
        "__ENVIRONMENT__": environment,
        "__HOST__": host,
        "__ORIGIN__": "https://" + host,
        "__CORS__": json.dumps(["https://" + host]),
        "__REPLICAS__": 2 if environment == "production" else 1,
        "__BACKEND_IMAGE__": data["images"]["backend"],
        "__FRONTEND_IMAGE__": data["images"]["frontend"],
    }

    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return replacements.get(value, value) if isinstance(value, str) else value

    result = replace(
        json.loads(
            (ROOT / "infrastructure/kubernetes/manifests/workloads.json").read_text()
        )
    )
    if "__" in json.dumps(result):
        raise ValueError("Unresolved manifest values")
    return result


def select_run(data, repository, revision, environment):
    image_names(repository, revision)
    if environment not in NAMESPACES:
        raise ValueError("Invalid environment")
    branches = {"main"} if environment == "production" else {"main", "develop"}
    candidates = [
        row
        for row in data.get("workflow_runs", [])
        if row.get("head_sha") == revision
        and row.get("event") == "push"
        and row.get("path") == ".github/workflows/ci-cd.yml"
        and row.get("head_branch") in branches
        and row.get("head_repository", {}).get("full_name", "").lower()
        == repository.lower()
    ]
    if not candidates:
        raise ValueError("No matching publication workflow")
    latest = max(candidates, key=lambda row: row["id"])
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError("The latest CI run has not passed")
    return latest["id"]


def kubectl_json(arguments):
    try:
        result = subprocess.run(
            ["kubectl", *arguments, "-o", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError):
        raise ValueError("Cluster prerequisites could not be verified") from None


def preflight(
    environment,
    confirmation,
    expected_context,
    reader=kubectl_json,
    context_reader=None,
):
    if environment not in NAMESPACES:
        raise ValueError("Invalid environment")
    target = NAMESPACES[environment]
    if confirmation != "APPLY " + target or not expected_context:
        raise ValueError(
            "Explicit namespace confirmation and expected context are required"
        )
    if context_reader is None:
        try:
            actual = subprocess.run(
                ["kubectl", "config", "current-context"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        except subprocess.SubprocessError:
            raise ValueError("Cluster context could not be verified") from None
    else:
        actual = context_reader()
    if actual != expected_context:
        raise ValueError("Unexpected cluster context")
    reader(["get", "namespace", target])
    runtime = reader(["get", "secret", "delivery360-runtime", "-n", target])
    if any(
        not runtime.get("data", {}).get(key)
        for key in ("DATABASE_URL", "REDIS_URL", "SECRET_KEY")
    ):
        raise ValueError("Runtime secret is incomplete")
    tls = reader(["get", "secret", "delivery360-tls", "-n", target])
    if tls.get("type") != "kubernetes.io/tls" or any(
        not tls.get("data", {}).get(key) for key in ("tls.crt", "tls.key")
    ):
        raise ValueError("TLS secret is incomplete")
    volume = reader(["get", "pvc", "delivery360-uploads", "-n", target])
    if (
        volume.get("status", {}).get("phase") != "Bound"
        or environment == "production"
        and "ReadWriteMany" not in volume.get("spec", {}).get("accessModes", [])
    ):
        raise ValueError("A Bound volume and production RWX storage are required")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("images", "manifest", "render", "select-run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--repository", required=True)
        cmd.add_argument("--revision", required=True)
        if name == "manifest":
            cmd.add_argument("--backend-digest", required=True)
            cmd.add_argument("--frontend-digest", required=True)
            cmd.add_argument("--output", required=True)
        if name in ("render", "select-run"):
            cmd.add_argument("--environment", choices=NAMESPACES, required=True)
            cmd.add_argument("--input", required=True)
        if name == "render":
            cmd.add_argument("--host", required=True)
            cmd.add_argument("--output", required=True)
    cmd = sub.add_parser("preflight")
    cmd.add_argument("--environment", choices=NAMESPACES, required=True)
    cmd.add_argument("--confirmation", required=True)
    cmd.add_argument("--context", required=True)
    args = parser.parse_args()
    try:
        if args.command == "images":
            print(json.dumps(image_names(args.repository, args.revision)))
        elif args.command == "manifest":
            Path(args.output).write_text(
                json.dumps(
                    image_manifest(
                        args.repository,
                        args.revision,
                        args.backend_digest,
                        args.frontend_digest,
                    ),
                    indent=2,
                )
                + "\n"
            )
        elif args.command == "render":
            Path(args.output).write_text(
                json.dumps(
                    render(
                        json.loads(Path(args.input).read_text()),
                        args.repository,
                        args.revision,
                        args.environment,
                        args.host,
                    ),
                    indent=2,
                )
                + "\n"
            )
        elif args.command == "select-run":
            print(
                select_run(
                    json.loads(Path(args.input).read_text()),
                    args.repository,
                    args.revision,
                    args.environment,
                )
            )
        else:
            print(preflight(args.environment, args.confirmation, args.context))
    except (ValueError, OSError):
        parser.exit(
            1,
            "Release verification failed. Check inputs, CI and documented prerequisites.\n",
        )


if __name__ == "__main__":
    main()
