import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jobbot.state import apply_seen_state, load_state


def _job(**overrides):
    row = {
        "source": "Example Source",
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
        "source_provenance": [{
            "source": "Example Source", "id": "ABC-123",
            "url": "https://example.org/jobs/abc-123", "detail_status": "OK_HTML",
        }],
    }
    row.update(overrides)
    return row


def test_v138_first_observation_is_new_and_second_is_seen(tmp_path):
    state = tmp_path / "state.json"
    first = [_job()]
    stats1 = apply_seen_state(first, state, "2026-08-28")
    assert first[0]["seen_status"] == "NEW"
    assert stats1["NEW"] == 1
    assert state.exists()

    second = [_job()]
    stats2 = apply_seen_state(second, state, "2026-08-29")
    assert second[0]["seen_status"] == "SEEN"
    assert second[0]["times_seen"] == 2
    assert stats2["SEEN"] == 1
    assert stats2["state_jobs"] == 1


def test_v138_deadline_change_is_material_change(tmp_path):
    state = tmp_path / "state.json"
    apply_seen_state([_job()], state, "2026-08-28")
    changed = [_job(application_deadline="2026-10-15")]
    apply_seen_state(changed, state, "2026-08-29")
    assert changed[0]["seen_status"] == "MATERIALLY_CHANGED"
    assert "application_deadline" in changed[0]["change_reasons"]


def test_v138_closed_to_open_is_reopened(tmp_path):
    state = tmp_path / "state.json"
    apply_seen_state([_job(application_status="CLOSED")], state, "2026-08-28")
    reopened = [_job(application_status="OPEN")]
    apply_seen_state(reopened, state, "2026-08-29")
    assert reopened[0]["seen_status"] == "REOPENED"
    assert "application_status" in reopened[0]["change_reasons"]


def test_v138_stable_job_url_survives_title_change(tmp_path):
    state = tmp_path / "state.json"
    first = [_job(id="", source_provenance=[], title="Researcher")]
    apply_seen_state(first, state, "2026-08-28")
    changed = [_job(id="", source_provenance=[], title="Senior Researcher")]
    apply_seen_state(changed, state, "2026-08-29")
    assert changed[0]["seen_status"] == "MATERIALLY_CHANGED"
    assert "title" in changed[0]["change_reasons"]
    assert changed[0]["state_id"] == first[0]["state_id"]


def test_v138_generic_listing_url_does_not_merge_distinct_titles(tmp_path):
    state = tmp_path / "state.json"
    a = _job(id="", title="Researcher A", url="https://example.org/careers", source_provenance=[])
    b = _job(id="", title="Researcher B", url="https://example.org/careers", source_provenance=[])
    stats = apply_seen_state([a, b], state, "2026-08-28")
    assert stats["NEW"] == 2
    assert stats["state_jobs"] == 2
    assert a["state_id"] != b["state_id"]


def test_v138_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="corrupt"):
        load_state(path)


def _args(source="all", out="live_output", state_file="state/seen_jobs.json"):
    return SimpleNamespace(
        source=source,
        history_days=None,
        history_max_pages=40,
        history_max_candidates=250,
        euraxess_pages=8,
        euraxess_max_candidates=80,
        detail_delay=None,
        as_of="2026-08-28",
        bist_max_pages=5,
        bist_max_jobs=100,
        institution_max_pages=4,
        institution_max_jobs_per_board=100,
        madrid_pages=10,
        madrid_max_jobs=100,
        fisabio_max_jobs=50,
        fps_max_jobs=50,
        iislafe_pages=3,
        iislafe_max_jobs=30,
        out=out,
        state_file=state_file,
        no_state=False,
    )


def _fake_collection(job):
    from jobbot.production import SOURCE_ORDER
    return {
        "jobs": [job], "errors": [], "warnings": [],
        "diagnostics": {key: ({"board_fetch": "OK", "detail_success": 1, "detail_failed": 0} if key == "biocat" else None) for key in SOURCE_ORDER},
        "source_runs": {"biocat": {
            "source": "Biocat", "status": "OK", "jobs_collected": 1,
            "coverage_complete": True, "detail_resolution_complete": True,
            "detail_success": 1, "detail_failed": 0, "truncated": 0,
            "error": "", "warnings": [],
        }},
        "selected_sources": ["biocat"], "euraxess_audit": [],
    }


def test_v138_all_run_persists_state_and_daily_output_only_surfaces_new(tmp_path, monkeypatch):
    import run_live_sample as cli

    job = _job(source="Biocat", source_provenance=[{"source": "Biocat", "id": "ABC-123", "url": "https://example.org/jobs/abc-123", "detail_status": "OK_HTML"}])
    monkeypatch.setattr(cli, "collect_sources", lambda args, out_dir: _fake_collection(job))
    monkeypatch.setattr(cli, "assert_scoring_freeze", lambda root: {"ok": True, "mismatches": []})
    monkeypatch.setattr(cli, "ROOT", tmp_path)

    args = _args(out="out", state_file="state/seen_jobs.json")
    first = cli.run(args)
    assert first["seen_state_enabled"] is True
    assert first["new_canonical"] == 1
    assert first["daily_actionable"] == 1
    assert (tmp_path / "state" / "seen_jobs.json").exists()

    second = cli.run(args)
    assert second["new_canonical"] == 0
    assert second["seen_unchanged"] == 1
    assert second["daily_actionable"] == 0
    rows = list(csv.DictReader((tmp_path / "out" / "all_canonical.csv").open(encoding="utf-8-sig")))
    assert rows[0]["seen_status"] == "SEEN"


def test_v138_source_subset_does_not_mutate_state(tmp_path, monkeypatch):
    import run_live_sample as cli

    job = _job(source="Biocat")
    monkeypatch.setattr(cli, "collect_sources", lambda args, out_dir: _fake_collection(job))
    monkeypatch.setattr(cli, "assert_scoring_freeze", lambda root: {"ok": True, "mismatches": []})
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    args = _args(source="biocat", out="out", state_file="state/seen_jobs.json")
    summary = cli.run(args)
    assert summary["seen_state_enabled"] is False
    assert summary["state_disabled_reason"] == "source_subset_run"
    assert not (tmp_path / "state" / "seen_jobs.json").exists()
