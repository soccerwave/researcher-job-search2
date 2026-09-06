import csv
import json
import zipfile
from pathlib import Path

from jobbot.production import PRODUCTION_VERSION
from scripts.build_cloud_report import build_report
from scripts.r2_store import STATE_KEY, validate_state
from scripts.telegram_notify import format_summary

ROOT = Path(__file__).resolve().parents[1]


def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0].keys()) if rows else ["source", "title"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def test_v164_production_version():
    assert PRODUCTION_VERSION == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"


def test_github_workflow_uses_external_scheduler_and_single_execution_path():
    text = (ROOT / ".github" / "workflows" / "production-job-search.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "group: production-job-search" in text
    assert "cancel-in-progress: false" in text
    assert "python scripts/r2_store.py download-state" in text
    assert "python run_live_sample.py" in text
    assert "--source all" in text
    assert "python scripts/r2_store.py publish-run" in text


def test_cloudflare_worker_is_private_telegram_control_plane():
    worker = (ROOT / "cloudflare-worker" / "src" / "index.js").read_text(encoding="utf-8")
    config = (ROOT / "cloudflare-worker" / "wrangler.toml").read_text(encoding="utf-8")
    assert 'crons = ["17 3 * * *"]' in config
    assert 'binding = "REPORTS"' in config
    assert "TELEGRAM_ALLOWED_USER_IDS" in worker
    assert 'chat.type !== "private"' in worker
    assert "X-Telegram-Bot-Api-Secret-Token" in worker
    assert "workflow_dispatch" not in worker  # REST endpoint dispatch is used, not a second scheduler.
    assert '"/dispatches"' in worker
    assert 'callback_data: "run"' in worker
    assert 'callback_data: "file"' in worker


def test_r2_state_validation_and_key(tmp_path):
    path = tmp_path / "seen_jobs.json"
    path.write_text(json.dumps({"state_version": "V1.39_SEEN_HISTORY_V2", "updated_at": "2026-08-29", "jobs": {"job_1": {}}}), encoding="utf-8")
    data = validate_state(path)
    assert len(data["jobs"]) == 1
    assert STATE_KEY == "state/current/seen_jobs.json"


def test_cloud_report_smoke(tmp_path):
    out = tmp_path / "live_output"
    out.mkdir()
    summary = {
        "production_version": PRODUCTION_VERSION,
        "availability_as_of": "2026-08-29",
        "configured_sources": ["linkedin", "euraxess"],
        "raw": 3,
        "unique": 3,
        "current_actionable": 2,
        "daily_actionable": 1,
        "new_actionable": 1,
        "changed_or_reopened_actionable": 0,
        "needs_detail_review": 0,
        "seen_state_jobs": 530,
        "errors": [],
        "warnings": [],
        "recommendations": {"STRONG_APPLY": 0, "APPLY": 1, "REVIEW": 0, "LOW_PRIORITY": 1, "SKIP": 1},
        "source_runs": {
            "linkedin": {"status": "OK"},
            "euraxess": {"status": "PARTIAL"},
        },
    }
    (out / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    job = {
        "recommendation": "APPLY", "score": "85", "title": "Project Manager", "company": "Institute",
        "location": "Barcelona", "application_deadline": "2026-09-10", "application_status": "OPEN",
        "source": "EURAXESS", "seen_status": "NEW", "url": "https://example.org/job/1",
    }
    for name, rows in {
        "actionable.csv": [job],
        "daily_actionable.csv": [job],
        "actionable_primary.csv": [job],
        "actionable_low.csv": [],
        "needs_detail_review.csv": [],
        "source_summary.csv": [{"source_key": "euraxess", "source": "EURAXESS", "status": "PARTIAL", "canonical_jobs": "1", "actionable": "1", "detail_success": "1", "detail_failed": "0", "coverage_complete": "True", "error": "", "warnings": ""}],
    }.items():
        _write_csv(out / name, rows)

    report = build_report(out, out / "job_search_report.xlsx")
    assert report.exists() and report.stat().st_size > 1000
    with zipfile.ZipFile(report) as zf:
        workbook_xml = zf.read("xl/workbook.xml").decode("utf-8")
        for sheet in ("SUMMARY", "TODAY_ACTIONABLE", "CURRENT_ACTIONABLE", "SOURCES"):
            assert sheet in workbook_xml


def test_telegram_summary_contains_operational_counts():
    text = format_summary({
        "availability_as_of": "2026-08-29",
        "current_actionable": 40,
        "daily_actionable": 2,
        "new_actionable": 1,
        "changed_or_reopened_actionable": 1,
        "recommendations": {"APPLY": 2, "REVIEW": 8, "LOW_PRIORITY": 34},
        "source_runs": {"a": {"status": "OK"}, "b": {"status": "PARTIAL"}},
    })
    assert "Current actionable: 40" in text
    assert "New actionable: 1" in text
    assert "Sources: ✅ 1 | ⚠️ 1 | ❌ 0" in text
