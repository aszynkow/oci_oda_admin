"""Export ODA Insights, retain raw ZIPs, and prepare CSVs for Oracle Analytics."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def insight_paths(export_date: date, csv_names: list[str], prefix: str = "oda-insights") -> dict[str, str]:
    """Return deterministic Object Storage paths for raw and analytics artifacts."""
    base = f"{prefix.rstrip('/')}/"
    year, month, day = export_date.strftime("%Y"), export_date.strftime("%m"), export_date.isoformat()
    paths = {
        "archive": f"{base}archive/{year}/{month}/oda-insights-{day}.zip",
        "manifest": f"{base}analytics/manifests/{year}/{month}/oda-insights-{day}.json",
    }
    for name in csv_names:
        stem = re.sub(r"[^a-z0-9_-]+", "-", Path(name).stem.lower()).strip("-") or "insights"
        paths[name] = f"{base}analytics/{stem}/{year}/{month}/{stem}-{day}.csv"
    return paths


def extract_csvs(archive: Path, output_dir: Path) -> list[Path]:
    """Extract CSV files only, preventing path traversal from an external archive."""
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with ZipFile(archive) as zip_file:
        for item in zip_file.infolist():
            member = Path(item.filename)
            if member.suffix.lower() != ".csv" or member.is_absolute() or ".." in member.parts:
                continue
            target = output_dir / member.name
            if target.exists():
                target = output_dir / f"{member.stem}-{len(extracted) + 1}{member.suffix}"
            target.write_bytes(zip_file.read(item))
            extracted.append(target)
    return extracted


def consolidate_archives(archives: list[Path], output: Path) -> Path:
    """Keep a single raw archive even when ODA splits a large export into ZIPs."""
    if len(archives) == 1:
        return archives[0]
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as combined:
        for archive in archives:
            with ZipFile(archive) as source:
                for member in source.infolist():
                    if member.is_dir():
                        continue
                    combined.writestr(f"{archive.stem}/{Path(member.filename).name}", source.read(member))
    return output


def artifact_manifest(archive: Path, csvs: list[Path], objects: dict[str, str], export_date: date) -> dict[str, object]:
    """Create an OAC-oriented inventory without loading the CSV data into memory."""
    def record(path: Path) -> dict[str, object]:
        return {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "object": objects.get(path.name),
        }

    return {
        "export_date": export_date.isoformat(),
        "archive": {**record(archive), "object": objects["archive"]},
        "csv_files": [record(csv) for csv in csvs],
    }


def write_manifest(manifest: dict[str, object], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n")
    return output
