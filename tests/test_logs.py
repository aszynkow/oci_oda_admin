from zipfile import ZipFile

from oci_oda_admin.logs import archive_name, build_log_archive


def test_build_log_archive(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run.json").write_text('{"ok": true}')
    archive = build_log_archive(logs, tmp_path / "out" / "logs.zip")

    with ZipFile(archive) as zip_file:
        assert zip_file.namelist() == ["run.json"]


def test_archive_name_uses_prefix():
    assert archive_name("oda/test").startswith("oda/test/")
