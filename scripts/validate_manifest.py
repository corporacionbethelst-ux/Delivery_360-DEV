"""Offline Kubernetes schema validation; never opens a cluster connection."""

import json
from pathlib import Path
import sys
from kubernetes_validate import validate


def validate_plan(path):
    data = json.loads(Path(path).read_text())
    if (
        data.get("apiVersion") != "v1"
        or data.get("kind") != "List"
        or not data.get("items")
    ):
        raise ValueError("Expected a Kubernetes resource list")
    for item in data["items"]:
        validate(item, desired_version="1.34.0", strict=True)
    return len(data["items"])


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print(f"{path}: {validate_plan(path)} resources validated")
