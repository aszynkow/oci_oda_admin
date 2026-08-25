from oci_oda_admin.rest import normalize_endpoint, signed_request


def test_signed_request_builds_normalized_url(monkeypatch):
    captured = {}

    class Response:
        content = b'{"ok": true}'

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    monkeypatch.setattr("oci_oda_admin.rest.oci.signer.Signer", lambda **kwargs: "signer")
    monkeypatch.setattr(
        "oci_oda_admin.rest.requests.request",
        lambda method, url, **kwargs: captured.update(method=method, url=url, **kwargs) or Response(),
    )
    config = {"tenancy": "t", "user": "u", "fingerprint": "f", "key_file": "/key"}

    assert signed_request(config, "https://oda.example/", "get", "/api/v1/ping") == {"ok": True}
    assert captured["url"] == "https://oda.example/api/v1/ping"
    assert captured["auth"] == "signer"


def test_normalize_endpoint_accepts_oda_browser_url():
    assert normalize_endpoint("https://oda.example/botsui/home") == "https://oda.example"
