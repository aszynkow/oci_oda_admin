"""Repair exported ODA Visual Flow Designer bundles from the YAML source."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import yaml


def _flow_yaml(name: str, text: str) -> str:
    flow = {
        "name": name,
        "trackingId": str(uuid.uuid4()),
        "type": "task",
        "version": "2.0",
        "interface": {},
        "defaultTransitions": {"actions": {"system.startTaskFlow": "sendMessage"}},
        "states": {
            "sendMessage": {
                "component": "System.CommonResponse",
                "properties": {
                    "metadata": {"responseItems": [{"text": text, "type": "text"}], "keepTurn": False}
                },
                "transitions": {"return": "done"},
                "metadata": {"virtualComponent": "Virtual.Output"},
            }
        },
    }
    return yaml.safe_dump(flow, sort_keys=False, allow_unicode=True)


def repair_bundle(source: Path, output: Path, spec: dict, skill_version: str) -> list[str]:
    """Generate executable flow YAML for each configured intent in an export ZIP."""
    with ZipFile(source) as archive:
        files = {info.filename: archive.read(info.filename) for info in archive.infolist()}

    bot = json.loads(files["bot.json"])
    bot["version"] = skill_version
    files["bot.json"] = (json.dumps(bot, indent=2) + "\n").encode()

    main = yaml.safe_load(files["dialogs/System.MainFlow.yaml"])
    unresolved = [item for item in main.get("eventMappings", []) if item["eventName"] == "system.intent.unresolvedIntent"]
    mappings = unresolved
    written: list[str] = []
    for intent in spec["skill"]["intents"]:
        flow_name = f"Intent_{intent['name']}"
        text = intent["flow"]["steps"][0]["text"]
        file_name = f"dialogs/{flow_name}.yaml"
        files[file_name] = _flow_yaml(flow_name, text).encode()
        mappings.append({"eventName": f"system.intent.{intent['name']}", "flowName": flow_name, "trackingId": str(uuid.uuid4())})
        written.append(file_name)
    main["eventMappings"] = mappings
    files["dialogs/System.MainFlow.yaml"] = yaml.safe_dump(main, sort_keys=False, allow_unicode=True).encode()

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            if name == "dialogs/Help_Response.yaml":
                continue
            archive.writestr(name, content)
    return written


def repair_assistant_bundle(
    source: Path,
    repaired_skill: Path,
    output: Path,
    assistant_version: str,
    skill_version: str,
) -> list[str]:
    """Embed a repaired skill bundle and point an exported assistant at its version."""
    with ZipFile(source) as archive:
        files = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    with ZipFile(repaired_skill) as archive:
        skill_files = {info.filename: archive.read(info.filename) for info in archive.infolist()}

    bot = json.loads(files["bot.json"])
    bot["version"] = assistant_version
    files["bot.json"] = (json.dumps(bot, indent=2) + "\n").encode()

    # An assistant export contains the full referenced skill below this prefix.
    # Replacing it makes the import self-contained and avoids a stale VFD flow.
    skill_prefix = "skillBots/oci_admin/"
    for filename in list(files):
        if filename.startswith(skill_prefix):
            del files[filename]
    for filename, content in skill_files.items():
        files[f"{skill_prefix}{filename}"] = content

    detail_name = "botDetails/en-oci_admin.json"
    details = json.loads(files[detail_name])
    details["skillBotVersion"] = skill_version
    files[detail_name] = (json.dumps(details, indent=2) + "\n").encode()

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return sorted(name for name in files if name.startswith(skill_prefix + "dialogs/Intent_"))
