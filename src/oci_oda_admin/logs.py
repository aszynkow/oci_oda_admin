"""Export local ODA administration logs and optionally archive them in OCI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build_log_archive(log_dir: Path, output: Path) -> Path:
    """Create a ZIP archive of log files, preserving paths relative to log_dir."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        if log_dir.exists():
            for file in sorted(item for item in log_dir.rglob("*") if item.is_file()):
                archive.write(file, file.relative_to(log_dir))
    return output


def archive_name(prefix: str = "oda-admin") -> str:
    """Return a predictable, UTC-stamped object name."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix.rstrip('/')}/{timestamp}-logs.zip"


def upload_archive(config: dict, namespace: str, bucket: str, object_name: str, archive: Path) -> dict:
    """Upload an archive to OCI Object Storage using the configured API key."""
    import oci

    client = oci.object_storage.ObjectStorageClient(config)
    with archive.open("rb") as content:
        response = client.put_object(namespace, bucket, object_name, content)
    return {"bucket": bucket, "namespace": namespace, "object": object_name, "etag": response.headers.get("etag")}
