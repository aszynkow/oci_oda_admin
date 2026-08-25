from oci_oda_admin.deploy import lifecycle_requests
from oci_oda_admin.spec import deployment_plan, local_match, runtime_checks, validate_spec


def sample_spec():
    return {
        "skill": {
            "name": "OCI_Admin",
            "version": "1.2",
            "intents": [
                {
                    "name": "help",
                    "utterances": ["What can you do?"],
                    "flow": {"steps": [{"type": "send_message", "text": "I can help."}]},
                }
            ],
        },
        "assistant": {"name": "test", "version": "1.3", "skill": "OCI_Admin"},
        "channel": {"id": "channel-id"},
    }


def test_valid_spec_compiles_and_matches():
    spec = sample_spec()
    assert validate_spec(spec) == []
    assert deployment_plan(spec)["skill"]["intents"][0]["answer"] == "I can help."
    assert local_match(spec, "What can you do?").intent == "help"


def test_deployment_request_interpolates_context():
    spec = sample_spec()
    spec["deployment"] = {
        "operations": [
            {"name": "publish", "method": "post", "path": "/skills/{skill_name}/{skill_version}", "body": "plan"}
        ]
    }
    request = lifecycle_requests(spec, deployment_plan(spec))[0]
    assert request["path"] == "/skills/OCI_Admin/1.2"
    assert request["method"] == "POST"


def test_runtime_check_rejects_empty_flow():
    spec = sample_spec()
    spec["skill"]["intents"][0]["flow"] = {"steps": []}
    assert runtime_checks(spec)[0]["status"] == "failed"
