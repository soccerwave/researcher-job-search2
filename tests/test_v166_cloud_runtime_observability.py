from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cloud_job_timeout_is_120_minutes():
    text = (ROOT / ".github" / "workflows" / "production-job-search.yml").read_text(encoding="utf-8")
    assert "timeout-minutes: 120" in text
    assert "timeout-minutes: 60" not in text


def test_source_collection_emits_progress_and_timings():
    text = (ROOT / "jobbot" / "production.py").read_text(encoding="utf-8")
    assert "[collector:start]" in text
    assert "[collector:done]" in text
    assert '"elapsed_seconds": elapsed_seconds' in text
