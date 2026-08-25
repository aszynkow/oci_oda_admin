import json
from zipfile import ZipFile

import yaml

from oci_oda_admin.bundle import repair_assistant_bundle, repair_bundle


def test_repair_bundle_creates_executable_intent_flow(tmp_path):
    source = tmp_path / "source.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("bot.json", json.dumps({"version": "1.2"}))
        archive.writestr("dialogs/System.MainFlow.yaml", yaml.safe_dump({"eventMappings": []}))
        archive.writestr("dialogs/Help_Response.yaml", "name: Help_Response\n")
    spec = {"skill": {"intents": [{"name": "help", "flow": {"steps": [{"type": "send_message", "text": "Help text"}]}}]}}
    output = tmp_path / "fixed.zip"
    repair_bundle(source, output, spec, "1.3")
    with ZipFile(output) as archive:
        flow = yaml.safe_load(archive.read("dialogs/Intent_help.yaml"))
    assert flow["states"]["sendMessage"]["component"] == "System.CommonResponse"


def test_repair_assistant_bundle_embeds_repaired_skill(tmp_path):
    skill_source = tmp_path / "skill-source.zip"
    repaired_skill = tmp_path / "skill-repaired.zip"
    assistant_source = tmp_path / "assistant-source.zip"
    output = tmp_path / "assistant-repaired.zip"
    with ZipFile(skill_source, "w") as archive:
        archive.writestr("bot.json", json.dumps({"name": "oci_admin", "version": "1.2"}))
        archive.writestr("dialogs/System.MainFlow.yaml", "eventMappings: []\n")
    repair_bundle(skill_source, repaired_skill, {"skill": {"intents": [{"name": "help", "flow": {"steps": [{"text": "Help"}]}}]}}, "1.3")
    with ZipFile(assistant_source, "w") as archive:
        archive.writestr("bot.json", json.dumps({"name": "test", "version": "1.2"}))
        archive.writestr("botDetails/en-oci_admin.json", json.dumps({"skillBotVersion": "1.2"}))
        archive.writestr("skillBots/oci_admin/bot.json", "old")

    repair_assistant_bundle(assistant_source, repaired_skill, output, "1.3", "1.3")
    with ZipFile(output) as archive:
        assert json.loads(archive.read("bot.json"))["version"] == "1.3"
        assert json.loads(archive.read("botDetails/en-oci_admin.json"))["skillBotVersion"] == "1.3"
        assert json.loads(archive.read("skillBots/oci_admin/bot.json"))["version"] == "1.3"
        assert json.loads(archive.read("bot.json"))["version"] == "1.3"
