import json
from pathlib import Path
from types import SimpleNamespace

from jobbot.state import STATE_VERSION, apply_seen_state
from jobbot.production import PRODUCTION_VERSION
from run_live_sample import bootstrap_durable_state, inspect_state_storage, resolve_state_path


def _state_payload(updated_at: str, jobs: int) -> dict:
    return {
        "state_version": STATE_VERSION,
        "updated_at": updated_at,
        "jobs": {f"job_{i}": {"aliases": [], "last_snapshot": {}} for i in range(jobs)},
    }


def test_default_state_is_user_level_and_not_version_relative(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("JOBBOT_STATE_FILE", raising=False)
    root = tmp_path / "Downloads" / "job-search-bot-v1.62"
    path, meta = resolve_state_path(None, root)
    assert path == home / ".job-search-bot" / "seen_jobs.json"
    assert meta["mode"] == "durable_default"


def test_explicit_relative_state_path_remains_root_relative(tmp_path):
    root = tmp_path / "job-search-bot-v1.62"
    path, meta = resolve_state_path("state/custom.json", root)
    assert path == root / "state" / "custom.json"
    assert meta["mode"] == "explicit"


def test_environment_override_is_honored(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JOBBOT_STATE_FILE", "jobbot-state/prod.json")
    path, meta = resolve_state_path(None, tmp_path / "code")
    assert path == home / "jobbot-state" / "prod.json"
    assert meta["mode"] == "env"


def test_bootstrap_chooses_newest_valid_legacy_state(tmp_path):
    downloads = tmp_path / "Downloads"
    root = downloads / "job-search-bot-v1.62"
    root.mkdir(parents=True)
    old = downloads / "job-search-bot-v1.39" / "state" / "seen_jobs.json"
    newer = downloads / "job-search-bot-v1.55" / "state" / "seen_jobs.json"
    old.parent.mkdir(parents=True)
    newer.parent.mkdir(parents=True)
    old.write_text(json.dumps(_state_payload("2026-08-20", 226)), encoding="utf-8")
    newer.write_text(json.dumps(_state_payload("2026-08-28", 490)), encoding="utf-8")

    target = tmp_path / "home" / ".job-search-bot" / "seen_jobs.json"
    result = bootstrap_durable_state(target, root)
    migrated = json.loads(target.read_text(encoding="utf-8"))
    assert result["migrated"] is True
    assert Path(result["migrated_from"]) == newer
    assert migrated["updated_at"] == "2026-08-28"
    assert len(migrated["jobs"]) == 490
    # Legacy copy is retained as a rollback/audit artifact.
    assert newer.exists()


def test_bootstrap_does_nothing_once_durable_state_exists(tmp_path):
    root = tmp_path / "Downloads" / "job-search-bot-v1.62"
    root.mkdir(parents=True)
    target = tmp_path / "home" / ".job-search-bot" / "seen_jobs.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(_state_payload("2026-08-29", 500)), encoding="utf-8")
    legacy = tmp_path / "Downloads" / "job-search-bot-v1.39" / "state" / "seen_jobs.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps(_state_payload("2026-08-30", 999)), encoding="utf-8")

    result = bootstrap_durable_state(target, root)
    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert result["attempted"] is False
    assert result["migrated"] is False
    assert len(persisted["jobs"]) == 500


def test_durable_state_survives_code_version_change(tmp_path, monkeypatch):
    import run_live_sample as cli

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("JOBBOT_STATE_FILE", raising=False)

    job = {
        "source": "Biocat",
        "id": "ABC-123",
        "title": "Exercise Researcher",
        "company": "Example Institute",
        "location": "Barcelona",
        "url": "https://example.org/jobs/abc-123",
        "application_status": "OPEN",
        "application_deadline": "2026-09-30",
        "recommendation": "REVIEW",
        "score": 74,
        "detail_status": "OK_HTML",
        "full_detail": " ".join(["exercise physiology human intervention research coordination data analysis"] * 20),
        "source_provenance": [{"source": "Biocat", "id": "ABC-123", "url": "https://example.org/jobs/abc-123", "detail_status": "OK_HTML"}],
    }

    def fake_collection(args, out_dir):
        return {
            "jobs": [job], "errors": [], "warnings": [],
            "diagnostics": {key: None for key in cli.SOURCE_ORDER},
            "source_runs": {"biocat": {
                "source": "Biocat", "status": "OK", "jobs_collected": 1,
                "coverage_complete": True, "detail_resolution_complete": True,
                "detail_success": 1, "detail_failed": 0, "truncated": 0,
                "error": "", "warnings": [],
            }},
            "selected_sources": ["biocat"], "euraxess_audit": [],
        }

    monkeypatch.setattr(cli, "collect_sources", fake_collection)
    monkeypatch.setattr(cli, "assert_scoring_freeze", lambda root: {"ok": True, "mismatches": []})

    args = SimpleNamespace(source="all", history_days=None, no_state=False, state_file=None, out="out", as_of="2026-08-28")

    root1 = tmp_path / "Downloads" / "job-search-bot-v1.62"
    root1.mkdir(parents=True)
    monkeypatch.setattr(cli, "ROOT", root1)
    first = cli.run(args)
    assert first["state_storage_mode"] == "durable_default"
    assert first["new_canonical"] == 1

    root2 = tmp_path / "Downloads" / "job-search-bot-v1.63"
    root2.mkdir(parents=True)
    monkeypatch.setattr(cli, "ROOT", root2)
    args.as_of = "2026-08-29"
    second = cli.run(args)
    assert second["new_canonical"] == 0
    assert second["seen_unchanged"] == 1
    assert second["state_file"] == str(home / ".job-search-bot" / "seen_jobs.json")


def test_production_version_advanced_beyond_v162():
    assert PRODUCTION_VERSION != "V1.62_DURABLE_PRODUCTION_STATE"


def test_state_preflight_is_read_only_and_selects_candidate(tmp_path):
    downloads = tmp_path / "Downloads"
    root = downloads / "job-search-bot-v1.62"
    root.mkdir(parents=True)
    legacy = downloads / "job-search-bot-v1.39" / "state" / "seen_jobs.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps(_state_payload("2026-08-21", 226)), encoding="utf-8")
    target = tmp_path / "home" / ".job-search-bot" / "seen_jobs.json"

    # Patch the resolved default target without performing migration.
    import run_live_sample as cli
    original = cli.resolve_state_path
    cli.resolve_state_path = lambda value, root_arg=root: (target, {"mode": "durable_default", "env": ""})
    try:
        report = inspect_state_storage(None, root)
    finally:
        cli.resolve_state_path = original

    assert report["state_exists"] is False
    assert report["would_migrate_from"] == str(legacy)
    assert report["legacy_candidates"][0]["jobs"] == 226
    assert not target.exists()
