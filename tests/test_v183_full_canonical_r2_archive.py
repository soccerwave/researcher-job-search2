import gzip
import json
from pathlib import Path

from jobbot.production import PRODUCTION_VERSION
from scripts import r2_store


def test_v183_production_version():
    assert PRODUCTION_VERSION == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"


def test_publish_run_archives_complete_canonical_snapshot_as_gzip(tmp_path, monkeypatch):
    out = tmp_path / "live_output"
    out.mkdir()
    state_file = tmp_path / "seen_jobs.json"
    state_file.write_text(json.dumps({
        "state_version": "V1.39_SEEN_HISTORY_V2",
        "updated_at": "2026-08-30",
        "jobs": {"job_1": {}},
    }), encoding="utf-8")
    (out / "run_summary.json").write_text(json.dumps({
        "seen_state_enabled": True,
        "seen_state_jobs": 1,
        "availability_as_of": "2026-08-30",
    }), encoding="utf-8")
    canonical = out / "all_canonical.csv"
    canonical.write_text(
        "recommendation,application_status,title\n"
        "SKIP,CLOSED,Old role\n"
        "APPLY,OPEN,Good role\n",
        encoding="utf-8",
    )
    report = out / "job_search_report.xlsx"
    report.write_bytes(b"fake-xlsx")

    uploads = []

    class FakeS3:
        def upload_file(self, filename, bucket, key, ExtraArgs=None):
            uploads.append((Path(filename), key, ExtraArgs or {}))

    monkeypatch.setattr(r2_store, "_client", lambda: FakeS3())
    monkeypatch.setattr(r2_store, "_bucket", lambda: "test-bucket")

    manifest = r2_store.publish_run(state_file, out, report, "123-1")

    run_key = "runs/2026-08-30/123-1/all_canonical.csv.gz"
    latest_key = "latest/all_canonical.csv.gz"
    keys = [key for _, key, _ in uploads]
    assert run_key in keys
    assert latest_key in keys
    archive_path = next(path for path, key, _ in uploads if key == run_key)
    with gzip.open(archive_path, "rt", encoding="utf-8") as f:
        archived = f.read()
    assert "SKIP,CLOSED,Old role" in archived
    assert "APPLY,OPEN,Good role" in archived
    assert manifest["canonical_archive_key"] == run_key
    assert manifest["latest_canonical_archive_key"] == latest_key
    assert manifest["canonical_archive_gzip_bytes"] > 0
    assert manifest["canonical_archive_gzip_bytes"] <= manifest["canonical_archive_raw_bytes"] + 100


def test_telegram_workflow_does_not_attach_full_canonical_archive():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "production-job-search.yml").read_text(encoding="utf-8")
    # all_canonical is deliberately archived in R2 only; Telegram still receives the compact Excel report.
    notify_block = workflow.split("- name: Notify Telegram on success", 1)[1]
    assert "all_canonical" not in notify_block
    assert "--report runtime/live_output/job_search_report.xlsx" in notify_block
