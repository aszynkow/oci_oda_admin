"""Signed requests for ODA REST operations not exposed by a typed SDK method."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import oci
import requests


def normalize_endpoint(endpoint: str) -> str:
    """Convert an ODA browser URL (for example `/botsui/home`) to its host."""
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("ODA endpoint must be an absolute https URL.")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def signed_request(
    config: dict[str, Any], endpoint: str, method: str, path: str, body: dict[str, Any] | None = None
) -> Any:
    """Call an ODA REST endpoint using the same OCI API-key credentials as the SDK."""
    url = urljoin(normalize_endpoint(endpoint).rstrip("/") + "/", path.lstrip("/"))
    signer = oci.signer.Signer(
        tenancy=config["tenancy"], user=config["user"], fingerprint=config["fingerprint"],
        private_key_file_location=config["key_file"], pass_phrase=config.get("pass_phrase"),
    )
    response = requests.request(method.upper(), url, json=body, auth=signer, timeout=(10, 60))
    response.raise_for_status()
    return response.json() if response.content else None


def signed_download(config: dict[str, Any], endpoint: str, path: str) -> bytes:
    """Download a binary ODA REST resource using OCI API-key signing."""
    url = urljoin(normalize_endpoint(endpoint).rstrip("/") + "/", path.lstrip("/"))
    signer = oci.signer.Signer(
        tenancy=config["tenancy"], user=config["user"], fingerprint=config["fingerprint"],
        private_key_file_location=config["key_file"], pass_phrase=config.get("pass_phrase"),
    )
    response = requests.get(url, auth=signer, timeout=(10, 180))
    response.raise_for_status()
    return response.content
