"""A transparent signed-REST deployment adapter for a compiled ODA plan.

ODA development REST paths vary by service release.  The paths are therefore
provided in the YAML spec, rather than hidden in Python or inferred from UI.
"""

from __future__ import annotations

from typing import Any


def lifecycle_requests(spec: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the REST requests declared in `deployment.operations`."""
    operations = spec.get("deployment", {}).get("operations", [])
    context = {
        "skill_name": plan["skill"]["name"],
        "skill_version": plan["skill"]["version"],
        "assistant_name": plan["assistant"]["name"],
        "assistant_version": str(plan["assistant"]["version"]),
        "channel_id": plan.get("channel", {}).get("id", ""),
    }
    requests: list[dict[str, Any]] = []
    for operation in operations:
        payload = plan if operation.get("body") == "plan" else operation.get("body")
        requests.append(
            {
                "name": operation["name"],
                "method": operation["method"].upper(),
                "path": operation["path"].format(**context),
                "body": payload,
            }
        )
    return requests


def apply_requests(config: dict[str, Any], endpoint: str, requests: list[dict[str, Any]]) -> list[Any]:
    """Execute the declared lifecycle requests in order."""
    from .rest import signed_request

    return [signed_request(config, endpoint, item["method"], item["path"], item["body"]) for item in requests]
