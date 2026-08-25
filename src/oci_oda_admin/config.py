"""OCI SDK configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import oci


def load_oci_config(config_file: str | None = None, profile: str | None = None) -> dict:
    """Load and validate an OCI SDK configuration file."""
    resolved_file = config_file or os.getenv("OCI_CONFIG_FILE") or "~/.oci/config"
    resolved_profile = profile or os.getenv("OCI_CONFIG_PROFILE") or "DEFAULT"
    return oci.config.from_file(file_location=str(Path(resolved_file).expanduser()), profile_name=resolved_profile)
