"""Command-line interface for ODA administration."""

from __future__ import annotations

import json
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Annotated

import requests
import typer

from .bundle import repair_assistant_bundle, repair_bundle
from .deploy import apply_requests, lifecycle_requests
from .insights import (
    artifact_manifest,
    consolidate_archives,
    extract_csvs,
    insight_paths,
    write_manifest,
)
from .local_web import serve as serve_local_web
from .logs import archive_name, build_log_archive, upload_archive
from .spec import (
    deployment_plan,
    load_spec,
    local_match,
    local_test_suite,
    runtime_checks,
    validate_spec,
)

app = typer.Typer(help="Administer Oracle Digital Assistant through the OCI Python SDK.")


def _admin(config_file: str | None, profile: str | None):
    """Load the OCI SDK only for commands that contact OCI."""
    from .client import OdaAdmin

    return OdaAdmin.from_file(config_file, profile)


def _print(value: object) -> None:
    typer.echo(json.dumps(value, indent=2, default=str))


@app.command("validate")
def validate(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
) -> None:
    """Validate the declarative ODA skill/assistant/channel source file."""
    errors = validate_spec(load_spec(spec_file))
    if errors:
        for error in errors:
            typer.echo(f"ERROR: {error}")
        raise typer.Exit(code=1)
    typer.echo(f"Valid: {spec_file}")


@app.command("render")
def render(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    output: Annotated[Path, typer.Option()] = Path("generated/oci-admin-plan.json"),
) -> None:
    """Generate a portable JSON deployment plan from the YAML source."""
    spec = load_spec(spec_file)
    errors = validate_spec(spec)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(deployment_plan(spec), indent=2) + "\n")
    typer.echo(f"Wrote {output}")


@app.command("local-run")
def local_run(
    message: Annotated[str, typer.Argument()],
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
) -> None:
    """Run the intent matcher and configured response locally without OCI access."""
    spec = load_spec(spec_file)
    errors = validate_spec(spec)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    match = local_match(spec, message)
    if match is None:
        _print({"intent": None, "response": "I couldn't match that OCI admin request."})
        raise typer.Exit(code=2)
    _print({"intent": match.intent, "confidence": round(match.confidence, 3), "response": match.answer})


@app.command("serve-local-html")
def serve_local_html(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8080,
    assistant_id: Annotated[str | None, typer.Option(help="Published assistant ID; must match the YAML when set.")] = None,
    credentials_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/local-web.credentials.json"),
) -> None:
    """Run the real Oracle Web SDK tester bound to the configured assistant."""
    serve_local_web(spec_file, host, port, assistant_id, credentials_file)


@app.command("test")
def test(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    output: Annotated[Path, typer.Option()] = Path("logs/local-test-results.json"),
) -> None:
    """Run every configured utterance plus visual-flow runtime guards locally."""
    spec = load_spec(spec_file)
    guards = runtime_checks(spec)
    results = local_test_suite(spec)
    report = {"runtime_checks": guards, "tests": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    _print(report)
    if any(item["status"] == "failed" for item in guards + results):
        raise typer.Exit(code=1)


@app.command("train-publish")
def train_publish(
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    skill_id: Annotated[str | None, typer.Option(help="OCI ODA skill ID to train and publish")] = None,
    assistant_id: Annotated[str | None, typer.Option(help="OCI ODA digital-assistant ID to publish")] = None,
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    apply: Annotated[bool, typer.Option("--apply", help="Train and publish after all checks pass.")] = False,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Guard, then train skill, publish skill, and publish the assistant via OCI SDK."""
    spec = load_spec(spec_file)
    resources = spec.get("resources", {})
    resolved_instance = oda_instance_id or resources.get("oda_instance_id")
    resolved_skill = skill_id or resources.get("skill_id")
    resolved_assistant = assistant_id or resources.get("assistant_id")
    if not all([resolved_instance, resolved_skill, resolved_assistant]):
        raise typer.BadParameter("Set lifecycle IDs by option or in resources in the YAML.")
    failures = [item for item in runtime_checks(spec) if item["status"] == "failed"]
    if failures:
        _print({"published": False, "runtime_failures": failures})
        raise typer.Exit(code=1)
    if not apply:
        _print({"dry_run": True, "steps": ["train_skill", "publish_skill", "publish_assistant"]})
        return
    admin = _admin(config_file, profile)
    admin.train_skill(resolved_instance, resolved_skill)
    admin.publish_skill(resolved_instance, resolved_skill)
    admin.publish_assistant(resolved_instance, resolved_assistant)
    _print({"trained": resolved_skill, "published_skill": resolved_skill, "published_assistant": resolved_assistant})


@app.command("export-skill")
def export_skill(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    object_name: Annotated[str, typer.Option()] = "oda-admin/bundles/oci-admin-v1.2.zip",
    apply: Annotated[bool, typer.Option("--apply", help="Export the ODA skill bundle to Object Storage.")] = False,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Export the actual ODA skill bundle for local flow inspection and repair."""
    spec = load_spec(spec_file)
    resources = spec.get("resources", {})
    export_store = spec.get("bundles", {}).get("object_storage", {})
    required = [resources.get("oda_instance_id"), resources.get("skill_id"), export_store.get("namespace"), export_store.get("bucket"), export_store.get("compartment_id")]
    if not all(required):
        raise typer.BadParameter("Set resources IDs and bundles.object_storage values in the YAML.")
    target = {
        "region_id": export_store.get("region", "ap-sydney-1"),
        "compartment_id": export_store["compartment_id"],
        "namespace_name": export_store["namespace"],
        "bucket_name": export_store["bucket"],
        "object_name": object_name,
    }
    if not apply:
        _print({"dry_run": True, "export_skill_id": resources["skill_id"], "target": target})
        return
    _admin(config_file, profile).export_skill(resources["oda_instance_id"], resources["skill_id"], target)
    _print({"export_requested": True, "target": target})


@app.command("export-assistant")
def export_assistant(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    object_name: Annotated[str, typer.Option()] = "oda-admin/bundles/test-v1.2.zip",
    apply: Annotated[bool, typer.Option("--apply", help="Export the ODA assistant bundle to Object Storage.")] = False,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Export the current assistant bundle before creating its new version."""
    spec = load_spec(spec_file)
    resources = spec.get("resources", {})
    store = spec.get("bundles", {}).get("object_storage", {})
    required = [resources.get("oda_instance_id"), resources.get("assistant_id"), store.get("namespace"), store.get("bucket"), store.get("compartment_id")]
    if not all(required):
        raise typer.BadParameter("Set resources IDs and bundles.object_storage values in the YAML.")
    target = {"region_id": store.get("region", "ap-sydney-1"), "compartment_id": store["compartment_id"], "namespace_name": store["namespace"], "bucket_name": store["bucket"], "object_name": object_name}
    if not apply:
        _print({"dry_run": True, "export_assistant_id": resources["assistant_id"], "target": target})
        return
    _admin(config_file, profile).export_assistant(resources["oda_instance_id"], resources["assistant_id"], target)
    _print({"export_requested": True, "target": target})


@app.command("download-bundle")
def download_bundle(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    object_name: Annotated[str, typer.Option()] = "oda-admin/bundles/oci-admin-v1.2.zip",
    output: Annotated[Path, typer.Option()] = Path("exports/oci-admin-v1.2.zip"),
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Download an approved ODA skill bundle from its configured Object Storage bucket."""
    spec = load_spec(spec_file)
    store = spec.get("bundles", {}).get("object_storage", {})
    if not store.get("namespace") or not store.get("bucket"):
        raise typer.BadParameter("Set bundles.object_storage.namespace and bucket in the YAML.")
    import oci

    from .config import load_oci_config

    client = oci.object_storage.ObjectStorageClient(load_oci_config(config_file, profile))
    response = client.get_object(store["namespace"], store["bucket"], object_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as destination:
        shutil.copyfileobj(response.data.raw, destination)
    _print({"object": object_name, "output": str(output), "bytes": output.stat().st_size})


@app.command("repair-bundle")
def repair_bundle_command(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    source: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("exports/oci-admin-v1.2.zip"),
    output: Annotated[Path, typer.Option()] = Path("exports/oci-admin-v1.3-repaired.zip"),
    skill_version: Annotated[str, typer.Option()] = "1.3",
) -> None:
    """Generate executable VFD flows for every YAML intent in an exported skill bundle."""
    spec = load_spec(spec_file)
    errors = validate_spec(spec)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    written = repair_bundle(source, output, spec, skill_version)
    _print({"output": str(output), "skill_version": skill_version, "flows": written})


@app.command("upload-bundle")
def upload_bundle(
    bundle: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("exports/oci-admin-v1.3-repaired.zip"),
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    object_name: Annotated[str, typer.Option()] = "oda-admin/bundles/oci-admin-v1.3-repaired.zip",
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Upload a repaired skill bundle to the configured Object Storage bucket."""
    spec = load_spec(spec_file)
    store = spec.get("bundles", {}).get("object_storage", {})
    if not store.get("namespace") or not store.get("bucket"):
        raise typer.BadParameter("Set bundles.object_storage.namespace and bucket in the YAML.")
    import oci

    from .config import load_oci_config

    with bundle.open("rb") as content:
        response = oci.object_storage.ObjectStorageClient(load_oci_config(config_file, profile)).put_object(
            store["namespace"], store["bucket"], object_name, content
        )
    _print({"object": object_name, "bytes": bundle.stat().st_size, "etag": response.headers.get("etag")})


@app.command("import-skill")
def import_skill(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    object_name: Annotated[str, typer.Option()] = "oda-admin/bundles/oci-admin-v1.3-repaired.zip",
    apply: Annotated[bool, typer.Option("--apply", help="Import the repaired bundle as a new ODA skill version.")] = False,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Import the repaired bundle from Object Storage; export/import is the supported VFD update path."""
    spec = load_spec(spec_file)
    resources = spec.get("resources", {})
    store = spec.get("bundles", {}).get("object_storage", {})
    if not resources.get("oda_instance_id") or not all(store.get(key) for key in ("namespace", "bucket", "compartment_id")):
        raise typer.BadParameter("Set resources.oda_instance_id and bundles.object_storage in the YAML.")
    source = {
        "region_id": store.get("region", "ap-sydney-1"),
        "compartment_id": store["compartment_id"],
        "namespace_name": store["namespace"],
        "bucket_name": store["bucket"],
        "object_name": object_name,
    }
    if not apply:
        _print({"dry_run": True, "source": source})
        return
    _print(_admin(config_file, profile).import_skill(resources["oda_instance_id"], source))


@app.command("repair-assistant-bundle")
def repair_assistant_bundle_command(
    source: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("exports/test-v1.2.zip"),
    repaired_skill: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("exports/oci-admin-v1.3-repaired.zip"),
    output: Annotated[Path, typer.Option()] = Path("exports/test-v1.3-repaired.zip"),
    assistant_version: Annotated[str, typer.Option()] = "1.3",
    skill_version: Annotated[str, typer.Option()] = "1.3",
) -> None:
    """Create a self-contained assistant archive with the repaired skill embedded."""
    flows = repair_assistant_bundle(source, repaired_skill, output, assistant_version, skill_version)
    _print({"output": str(output), "assistant_version": assistant_version, "skill_version": skill_version, "flows": flows})


@app.command("import-assistant")
def import_assistant(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    object_name: Annotated[str, typer.Option()] = "oda-admin/bundles/test-v1.3-repaired.zip",
    apply: Annotated[bool, typer.Option("--apply", help="Import the repaired bundle as a new ODA assistant version.")] = False,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Import an assistant archive from Object Storage using the OCI SDK."""
    spec = load_spec(spec_file)
    resources = spec.get("resources", {})
    store = spec.get("bundles", {}).get("object_storage", {})
    if not resources.get("oda_instance_id") or not all(store.get(key) for key in ("namespace", "bucket", "compartment_id")):
        raise typer.BadParameter("Set resources.oda_instance_id and bundles.object_storage in the YAML.")
    source = {
        "region_id": store.get("region", "ap-sydney-1"),
        "compartment_id": store["compartment_id"],
        "namespace_name": store["namespace"],
        "bucket_name": store["bucket"],
        "object_name": object_name,
    }
    if not apply:
        _print({"dry_run": True, "source": source})
        return
    _print(_admin(config_file, profile).import_assistant(resources["oda_instance_id"], source))


@app.command("deploy")
def deploy(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    endpoint: Annotated[
        str | None, typer.Option("--endpoint", "--oda-endpoint", envvar="ODA_REST_ENDPOINT")
    ] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Execute the declared signed REST operations.")] = False,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Print, or explicitly execute, the ODA lifecycle REST request plan."""
    spec = load_spec(spec_file)
    errors = validate_spec(spec)
    if errors:
        raise typer.BadParameter("; ".join(errors))
    requests = lifecycle_requests(spec, deployment_plan(spec))
    resolved_endpoint = endpoint or spec.get("oda", {}).get("endpoint")
    if not apply:
        _print({"dry_run": True, "requests": requests})
        return
    if not resolved_endpoint:
        raise typer.BadParameter("Set --endpoint or ODA_REST_ENDPOINT before --apply.")
    if not requests:
        raise typer.BadParameter("deployment.operations is empty; add verified ODA REST paths first.")
    from .config import load_oci_config

    _print(apply_requests(load_oci_config(config_file, profile), resolved_endpoint, requests))


@app.command("discover")
def discover(
    assistant_id: Annotated[str, typer.Option(help="ODA digital-assistant ID to inspect")],
    endpoint: Annotated[
        str | None, typer.Option("--endpoint", "--oda-endpoint", envvar="ODA_REST_ENDPOINT")
    ] = None,
    path: Annotated[
        list[str] | None,
        typer.Option(
            "--path",
            help="Read-only API path. Repeat for assistant, skills, intents, flows, channels, and versions.",
        ),
    ] = None,
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Discover ODA assistant components using only signed GET requests.

    Paths may use `{assistant_id}` and `{channel_id}` placeholders. If paths
    aren't passed on the command line, `discovery.paths` in the YAML is used.
    """
    spec = load_spec(spec_file)
    resolved_endpoint = endpoint or spec.get("oda", {}).get("endpoint")
    if not resolved_endpoint:
        raise typer.BadParameter("Set --oda-endpoint, ODA_REST_ENDPOINT, or oda.endpoint in the YAML.")
    configured_paths = spec.get("discovery", {}).get("paths", [])
    selected_paths = path or configured_paths
    if not selected_paths:
        raise typer.BadParameter("Provide one or more --path values or configure discovery.paths.")

    from .config import load_oci_config
    from .rest import signed_request

    context = {"assistant_id": assistant_id, "channel_id": spec.get("channel", {}).get("id", "")}
    results: dict[str, object] = {}
    for template in selected_paths:
        resolved = template.format(**context)
        try:
            results[resolved] = signed_request(
                load_oci_config(config_file, profile), resolved_endpoint, "GET", resolved
            )
        except requests.HTTPError as error:
            results[resolved] = {
                "error": str(error),
                "status_code": error.response.status_code if error.response is not None else None,
            }
    _print({"assistant_id": assistant_id, "components": results})


@app.command("discover-sdk")
def discover_sdk(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """List skills, assistants, and channels using the supported OCI SDK."""
    spec = load_spec(spec_file)
    instance_id = oda_instance_id or spec.get("resources", {}).get("oda_instance_id")
    if not instance_id:
        raise typer.BadParameter("Set --oda-instance-id, ODA_INSTANCE_ID, or resources.oda_instance_id.")
    admin = _admin(config_file, profile)
    _print(
        {
            "oda_instance_id": instance_id,
            "skills": admin.list_skills(instance_id),
            "assistants": admin.list_bots(instance_id),
            "channels": admin.list_channels(instance_id),
        }
    )


@app.command("export-logs")
def export_logs(
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    log_dir: Annotated[Path, typer.Option()] = Path("logs"),
    output: Annotated[Path, typer.Option()] = Path("exports/oda-admin-logs.zip"),
    upload: Annotated[bool, typer.Option("--upload", help="Upload the archive to OCI Object Storage.")] = False,
    namespace: Annotated[str | None, typer.Option()] = None,
    bucket: Annotated[str | None, typer.Option()] = None,
    object_name: Annotated[str | None, typer.Option()] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Archive local logs; upload only when `--upload` is explicitly supplied."""
    archive = build_log_archive(log_dir, output)
    result: dict[str, object] = {"archive": str(archive), "uploaded": False}
    if not upload:
        _print(result)
        return

    spec = load_spec(spec_file)
    object_store = spec.get("logging", {}).get("object_storage", {})
    resolved_namespace = namespace or object_store.get("namespace")
    resolved_bucket = bucket or object_store.get("bucket")
    if not resolved_namespace or not resolved_bucket:
        raise typer.BadParameter("Set --namespace/--bucket or logging.object_storage in the YAML.")
    from .config import load_oci_config

    object_key = object_name or archive_name(object_store.get("prefix", "oda-admin/logs"))
    result["object_storage"] = upload_archive(
        load_oci_config(config_file, profile), resolved_namespace, resolved_bucket, object_key, archive
    )
    result["uploaded"] = True
    _print(result)


@app.command("export-insights")
def export_insights(
    begin: Annotated[str, typer.Option(help="First UTC date to export (YYYY-MM-DD).")],
    end: Annotated[str, typer.Option(help="Last UTC date to export (YYYY-MM-DD).")],
    assistant_id: Annotated[str | None, typer.Option(help="Assistant ID; defaults to YAML resources.assistant_id.")] = None,
    bucket: Annotated[str | None, typer.Option(help="Existing Object Storage bucket; defaults to YAML.")] = None,
    name: Annotated[str | None, typer.Option(help="ODA export job name.")] = None,
    output_dir: Annotated[Path, typer.Option()] = Path("exports/insights"),
    poll_seconds: Annotated[int, typer.Option(min=1, max=60)] = 5,
    max_wait_seconds: Annotated[int, typer.Option(min=5, max=3600)] = 600,
    apply: Annotated[bool, typer.Option("--apply", help="Start ODA export and upload artifacts to Object Storage.")] = False,
    spec_file: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("configs/oci-admin.yaml"),
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Export ODA Insights ZIP/CSVs to an existing Object Storage bucket for OAC."""
    try:
        begin_date = date.fromisoformat(begin)
        end_date = date.fromisoformat(end)
    except ValueError as error:
        raise typer.BadParameter("--begin and --end must use YYYY-MM-DD.") from error
    if end_date < begin_date:
        raise typer.BadParameter("--end must be on or after --begin.")
    spec = load_spec(spec_file)
    insights = spec.get("insights", {})
    store = insights.get("object_storage", {})
    selected_assistant = assistant_id or spec.get("resources", {}).get("assistant_id")
    selected_bucket = bucket or store.get("bucket")
    namespace = store.get("namespace") or spec.get("bundles", {}).get("object_storage", {}).get("namespace")
    endpoint = spec.get("oda", {}).get("endpoint")
    if not all([selected_assistant, selected_bucket, namespace, endpoint]):
        raise typer.BadParameter("Set assistant ID, ODA endpoint, namespace, and existing bucket in YAML or options.")
    job_name = name or f"oda_insights_{begin_date.strftime('%Y%m%d')}"
    base_path = "/api/v1/bots/insights/dataExports"
    plan = {
        "assistant_id": selected_assistant,
        "range": {"begin": begin_date.isoformat(), "end": end_date.isoformat()},
        "bucket": selected_bucket,
        "namespace": namespace,
        "prefix": store.get("prefix", "oda-insights"),
        "job_name": job_name,
    }
    if not apply:
        _print({"dry_run": True, **plan})
        return

    from .config import load_oci_config
    from .logs import upload_archive
    from .rest import signed_download, signed_request

    oci_config = load_oci_config(config_file, profile)
    start_path = (
        f"{base_path}?odaId={selected_assistant}&maxFileLength="
        f"{insights.get('max_file_length', 100000000)}&since={begin_date.isoformat()}&until={end_date.isoformat()}"
    )
    started = signed_request(
        oci_config, endpoint, "POST", start_path,
        {"insightsDataExport": True, "taskType": "EXPORT", "name": job_name},
    ) or {}
    job = started.get("result", started)
    job_id = job.get("jobId") or job.get("resourceId")
    if not job_id:
        raise RuntimeError(f"ODA Insights export did not return a job ID: {started}")

    deadline = time.monotonic() + max_wait_seconds
    status: dict[str, object] = {}
    while time.monotonic() < deadline:
        status = signed_request(oci_config, endpoint, "GET", f"{base_path}/{job_id}") or {}
        details = status.get("result", status)
        state = str(details.get("status", "")).upper()
        if state in {"SUCCESS", "EXPORT_SUCCEEDED"}:
            break
        if state in {"FAILED", "EXPORT_FAILED", "NO_DATA"}:
            raise RuntimeError(f"ODA Insights export {job_id} ended with {state}: {details}")
        time.sleep(poll_seconds)
    else:
        raise TimeoutError(f"ODA Insights export {job_id} did not finish within {max_wait_seconds} seconds.")

    details = status.get("result", status)
    filenames = details.get("filenames", [])
    if not filenames:
        raise RuntimeError(f"ODA Insights export {job_id} completed without files: {details}")
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for filename in filenames:
        target = output_dir / Path(str(filename)).name
        target.write_bytes(signed_download(oci_config, endpoint, f"{base_path}/{job_id}/files/{filename}"))
        downloaded.append(target)
    archive = consolidate_archives(downloaded, output_dir / f"oda-insights-{begin_date.isoformat()}.zip")
    csvs: list[Path] = []
    for downloaded_archive in downloaded:
        csvs.extend(extract_csvs(downloaded_archive, output_dir / "analytics"))
    objects = insight_paths(begin_date, [csv.name for csv in csvs], store.get("prefix", "oda-insights"))
    uploaded = [upload_archive(oci_config, namespace, selected_bucket, objects["archive"], archive)]
    for csv in csvs:
        uploaded.append(upload_archive(oci_config, namespace, selected_bucket, objects[csv.name], csv))
    manifest = write_manifest(artifact_manifest(archive, csvs, objects, begin_date), output_dir / "manifest.json")
    uploaded.append(upload_archive(oci_config, namespace, selected_bucket, objects["manifest"], manifest))
    _print({"job_id": job_id, "status": details.get("status"), "uploads": uploaded})


@app.command("instances")
def instances(
    compartment_id: Annotated[str, typer.Option(envvar="OCI_COMPARTMENT_ID")],
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    _print(_admin(config_file, profile).list_instances(compartment_id))


@app.command("bots")
def bots(
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    if not oda_instance_id:
        raise typer.BadParameter("Set --oda-instance-id or ODA_INSTANCE_ID.")
    _print(_admin(config_file, profile).list_bots(oda_instance_id))


@app.command("skills")
def skills(
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    if not oda_instance_id:
        raise typer.BadParameter("Set --oda-instance-id or ODA_INSTANCE_ID.")
    _print(_admin(config_file, profile).list_skills(oda_instance_id))


@app.command("channels")
def channels(
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    if not oda_instance_id:
        raise typer.BadParameter("Set --oda-instance-id or ODA_INSTANCE_ID.")
    _print(_admin(config_file, profile).list_channels(oda_instance_id))


@app.command("channel-details")
def channel_details(
    channel_id: Annotated[str, typer.Argument()],
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Show the full channel configuration, including its routed assistant."""
    if not oda_instance_id:
        raise typer.BadParameter("Set --oda-instance-id or ODA_INSTANCE_ID.")
    _print(_admin(config_file, profile).get_channel(oda_instance_id, channel_id))


@app.command("route-web-channel")
def route_web_channel(
    channel_id: Annotated[str, typer.Argument()],
    assistant_id: Annotated[str, typer.Argument()],
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Update the live Web channel route.")] = False,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Preview or change the published assistant served by a Web channel."""
    if not oda_instance_id:
        raise typer.BadParameter("Set --oda-instance-id or ODA_INSTANCE_ID.")
    if not apply:
        _print({"dry_run": True, "channel_id": channel_id, "assistant_id": assistant_id})
        return
    _admin(config_file, profile).route_web_channel(oda_instance_id, channel_id, assistant_id)
    _print({"updated_channel": channel_id, "assistant_id": assistant_id})


@app.command("create-skill")
def create_skill(
    details_file: Annotated[Path, typer.Option(exists=True, readable=True)],
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    if not oda_instance_id:
        raise typer.BadParameter("Set --oda-instance-id or ODA_INSTANCE_ID.")
    _print(_admin(config_file, profile).create_skill(oda_instance_id, json.loads(details_file.read_text())))


@app.command("start-channel")
def start_channel(
    channel_id: Annotated[str, typer.Argument()],
    oda_instance_id: Annotated[str | None, typer.Option(envvar="ODA_INSTANCE_ID")] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    if not oda_instance_id:
        raise typer.BadParameter("Set --oda-instance-id or ODA_INSTANCE_ID.")
    _admin(config_file, profile).start_channel(oda_instance_id, channel_id)
    typer.echo("Channel start requested.")


@app.command("rest")
def rest(
    method: Annotated[str, typer.Argument()],
    path: Annotated[str, typer.Argument()],
    endpoint: Annotated[
        str | None, typer.Option("--endpoint", "--oda-endpoint", envvar="ODA_REST_ENDPOINT")
    ] = None,
    body_file: Annotated[Path | None, typer.Option(exists=True, readable=True)] = None,
    config_file: Annotated[str | None, typer.Option()] = None,
    profile: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Send a signed ODA REST request, e.g. for dynamic entities or insights APIs."""
    if not endpoint:
        raise typer.BadParameter("Set --endpoint or ODA_REST_ENDPOINT.")
    body = json.loads(body_file.read_text()) if body_file else None
    from .config import load_oci_config
    from .rest import signed_request

    _print(signed_request(load_oci_config(config_file, profile), endpoint, method, path, body))


if __name__ == "__main__":  # pragma: no cover
    app()
