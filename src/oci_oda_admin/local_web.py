"""Local Oracle Web SDK host with server-side JWT generation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .spec import load_spec, validate_spec


def _jwt(secret: str, channel_id: str, user_id: str) -> str:
    """Create the short-lived HS256 JWT required by an authenticated Web channel."""
    def encode(value: dict[str, object]) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")

    now = int(time.time())
    signing_input = b".".join(
        [
            encode({"typ": "JWT", "alg": "HS256"}),
            encode({"iat": now, "exp": now + 1800, "channelId": channel_id, "userId": user_id}),
        ]
    )
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()).rstrip(b"=")
    return b".".join([signing_input, signature]).decode()


def _page(assistant_id: str, channel_id: str, server_uri: str, user_id: str) -> bytes:
    settings = json.dumps(
        {
            "URI": server_uri,
            "channelId": channel_id,
            "userId": user_id,
            "clientAuthEnabled": True,
        }
    )
    return """<!doctype html>
<html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>OCI Admin</title>
<style>body{font:16px system-ui;margin:3rem;max-width:720px;color:#252525}.note{color:#555}</style>
<h1>OCI Admin</h1><p>Oracle Digital Assistant Web channel is ready.</p><p class=\"note\">Assistant <code>__ASSISTANT_ID__</code> · channel <code>__CHANNEL_ID__</code></p>
<script>
const chatSettings=__SETTINGS__;
async function generateToken(){const response=await fetch('/api/token');if(!response.ok)throw new Error('Token request failed');return response.text();}
function initSDK(){const Bots=new WebSDK(chatSettings,generateToken);window.Bots=Bots;let firstOpen=true;Bots.on(WebSDK.EVENT.WIDGET_OPENED,async()=>{if(firstOpen){await Bots.connect();firstOpen=false;}});}
</script>
<script src=\"https://static.oracle.com/cdn/oda/25.8.0/web-sdk.js\" onload=\"initSDK()\" defer></script>
</html>""".replace("__ASSISTANT_ID__", assistant_id).replace("__CHANNEL_ID__", channel_id).replace("__SETTINGS__", settings).encode()


def serve(
    spec_file: Path,
    host: str,
    port: int,
    assistant_id: str | None = None,
    credentials_file: Path = Path("configs/local-web.credentials.json"),
) -> None:
    """Serve the real Oracle Web SDK widget and its local token endpoint."""
    spec = load_spec(spec_file)
    errors = validate_spec(spec)
    if errors:
        raise ValueError("; ".join(errors))
    configured_assistant_id = spec.get("resources", {}).get("assistant_id")
    selected_assistant_id = assistant_id or configured_assistant_id
    if not selected_assistant_id:
        raise ValueError("Set resources.assistant_id or pass --assistant-id.")
    if assistant_id and configured_assistant_id and assistant_id != configured_assistant_id:
        raise ValueError("--assistant-id does not match resources.assistant_id in the YAML.")
    credentials = json.loads(credentials_file.read_text())
    channel_secret = credentials.get("channel_secret")
    if not isinstance(channel_secret, str) or not channel_secret:
        raise ValueError("credentials file must include channel_secret.")
    channel_id = spec.get("channel", {}).get("id")
    endpoint = spec.get("oda", {}).get("endpoint")
    parsed = urlparse(endpoint or "")
    if not channel_id or not parsed.scheme or not parsed.netloc:
        raise ValueError("Set oda.endpoint and channel.id in the YAML.")
    server_uri = f"{parsed.scheme}://{parsed.netloc}"
    user_id = f"local-{uuid.uuid4()}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/api/token":
                token = _jwt(channel_secret, channel_id, user_id).encode()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(token)))
                self.end_headers()
                self.wfile.write(token)
                return
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            page = _page(selected_assistant_id, channel_id, server_uri, user_id)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Oracle Web SDK tester running at http://{host}:{port}/")
    server.serve_forever()
