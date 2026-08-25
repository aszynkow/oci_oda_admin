from oci_oda_admin.cli import app


def test_discover_command_is_registered():
    assert any(command.name == "discover" for command in app.registered_commands)
