from datetime import date
from zipfile import ZipFile

from oci_oda_admin.insights import consolidate_archives, extract_csvs, insight_paths


def test_insight_paths_keep_each_csv_as_a_separate_oac_object():
    paths = insight_paths(date(2026, 8, 24), ["Conversations.csv", "Intent Metrics.csv"])
    assert paths["archive"] == "oda-insights/archive/2026/08/oda-insights-2026-08-24.zip"
    assert paths["Conversations.csv"].endswith("conversations-2026-08-24.csv")
    assert paths["Intent Metrics.csv"].endswith("intent-metrics-2026-08-24.csv")


def test_extract_csvs_and_consolidate_split_archives(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    with ZipFile(first, "w") as archive:
        archive.writestr("conversations.csv", "id,text\n1,hello\n")
    with ZipFile(second, "w") as archive:
        archive.writestr("intents.csv", "intent,count\nhelp,1\n")

    csvs = extract_csvs(first, tmp_path / "csvs") + extract_csvs(second, tmp_path / "csvs")
    combined = consolidate_archives([first, second], tmp_path / "combined.zip")

    assert [csv.name for csv in csvs] == ["conversations.csv", "intents.csv"]
    with ZipFile(combined) as archive:
        assert sorted(archive.namelist()) == ["first/conversations.csv", "second/intents.csv"]
