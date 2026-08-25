"""Small, intentional wrapper around the OCI ODA Management API."""

from __future__ import annotations

from typing import Any

import oci

from .config import load_oci_config


class OdaAdmin:
    """Administer ODA instances, digital assistants, skills, and channels."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.instances = oci.oda.OdaClient(config)
        self.management = oci.oda.ManagementClient(config)

    @classmethod
    def from_file(cls, config_file: str | None = None, profile: str | None = None) -> OdaAdmin:
        return cls(load_oci_config(config_file, profile))

    def list_instances(self, compartment_id: str) -> list[dict[str, Any]]:
        response = oci.pagination.list_call_get_all_results(
            self.instances.list_oda_instances, compartment_id=compartment_id
        )
        return [oci.util.to_dict(item) for item in response.data]

    def list_bots(self, oda_instance_id: str) -> list[dict[str, Any]]:
        """Backward-compatible alias for listing digital assistants."""
        response = oci.pagination.list_call_get_all_results(
            self.management.list_digital_assistants, oda_instance_id=oda_instance_id
        )
        return [oci.util.to_dict(item) for item in response.data]

    def list_skills(self, oda_instance_id: str) -> list[dict[str, Any]]:
        response = oci.pagination.list_call_get_all_results(
            self.management.list_skills, oda_instance_id=oda_instance_id
        )
        return [oci.util.to_dict(item) for item in response.data]

    def list_channels(self, oda_instance_id: str) -> list[dict[str, Any]]:
        response = oci.pagination.list_call_get_all_results(
            self.management.list_channels, oda_instance_id=oda_instance_id
        )
        return [oci.util.to_dict(item) for item in response.data]

    def get_channel(self, oda_instance_id: str, channel_id: str) -> dict[str, Any]:
        return oci.util.to_dict(self.management.get_channel(oda_instance_id, channel_id).data)

    def get_assistant(self, oda_instance_id: str, assistant_id: str) -> dict[str, Any]:
        return oci.util.to_dict(self.management.get_digital_assistant(oda_instance_id, assistant_id).data)

    def route_web_channel(self, oda_instance_id: str, channel_id: str, assistant_id: str) -> None:
        """Route an existing Web channel to a published digital assistant version."""
        details = oci.oda.models.UpdateWebChannelDetails(bot_id=assistant_id)
        self.management.update_channel(oda_instance_id, channel_id, details)

    def create_skill(self, oda_instance_id: str, details: dict[str, Any]) -> dict[str, Any]:
        """Create a skill from a JSON-compatible CreateSkillDetails payload."""
        payload = oci.oda.models.CreateSkillDetails(**details)
        response = self.management.create_skill(oda_instance_id, payload)
        return oci.util.to_dict(response.data)

    def start_channel(self, oda_instance_id: str, channel_id: str) -> None:
        self.management.start_channel(oda_instance_id, channel_id)

    def train_skill(self, oda_instance_id: str, skill_id: str) -> None:
        details = oci.oda.models.TrainSkillDetails(
            items=[oci.oda.models.TrainSkillQueryEntityParameter(type="QUERY_ENTITY")]
        )
        self.management.train_skill(oda_instance_id, skill_id, details)

    def publish_skill(self, oda_instance_id: str, skill_id: str) -> None:
        self.management.publish_skill(oda_instance_id, skill_id)

    def publish_assistant(self, oda_instance_id: str, assistant_id: str) -> None:
        self.management.publish_digital_assistant(oda_instance_id, assistant_id)

    def export_skill(self, oda_instance_id: str, skill_id: str, target: dict[str, str]) -> None:
        location = oci.oda.models.StorageLocation(**target)
        self.management.export_skill(oda_instance_id, skill_id, oci.oda.models.ExportSkillDetails(target=location))

    def import_skill(self, oda_instance_id: str, source: dict[str, str]) -> dict[str, Any]:
        return self.import_bundle(oda_instance_id, source)

    def import_assistant(self, oda_instance_id: str, source: dict[str, str]) -> dict[str, Any]:
        return self.import_bundle(oda_instance_id, source)

    def import_bundle(self, oda_instance_id: str, source: dict[str, str]) -> dict[str, Any]:
        location = oci.oda.models.StorageLocation(**source)
        response = self.management.import_bot(oda_instance_id, oci.oda.models.ImportBotDetails(source=location))
        return oci.util.to_dict(response.data)

    def export_assistant(self, oda_instance_id: str, assistant_id: str, target: dict[str, str]) -> None:
        location = oci.oda.models.StorageLocation(**target)
        self.management.export_digital_assistant(
            oda_instance_id, assistant_id, oci.oda.models.ExportDigitalAssistantDetails(target=location)
        )
