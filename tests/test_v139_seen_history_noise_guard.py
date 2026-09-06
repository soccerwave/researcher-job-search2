import csv
import json
from pathlib import Path
from types import SimpleNamespace

from jobbot.state import apply_seen_state, load_state


def _detail_text(seed="exercise"):
    return " ".join(([seed, "physiology", "human", "intervention", "research", "coordination", "data", "analysis"] * 20))


def _job(**overrides):
    row = {
        "source": "Biocat",
        "id": "",
        "title": "Earth data strategist (RE2)",
        "company": "Barcelona Supercomputing Center",
        "location": "Barcelona",
        "url": "https://www.bsc.es/join-us/job-opportunities/38726eseddre2",
        "application_status": "OPEN",
        "application_deadline": "2026-08-31",
        "recommendation": "SKIP",
        "score": 25,
        "detail_status": "OK_HTML",
        "full_detail": _detail_text("earth"),
        "source_provenance": [{
            "source": "Biocat", "id": "",
            "url": "https://www.bsc.es/join-us/job-opportunities/38726eseddre2",
            "detail_status": "OK_HTML",
        }],
    }
    row.update(overrides)
    return row


def _unresolved(**overrides):
    row = _job(
        recommendation="NEEDS_DETAIL_REVIEW",
        score="",
        detail_status="FETCH_FAILED_TLS",
        full_detail="",
    )
    row.update(overrides)
    return row


def test_v139_unresolved_to_resolved_is_quality_event_not_material_change(tmp_path):
    state = tmp_path / "state.json"
    first = [_unresolved()]
    apply_seen_state(first, state, "2026-08-28")
    assert first[0]["seen_status"] == "NEW"

    second = [_job()]
    stats = apply_seen_state(second, state, "2026-08-29")
    assert second[0]["seen_status"] == "SEEN"
    assert second[0]["change_reasons"] == []
    assert second[0]["state_events"] == ["DETAIL_RESOLVED"]
    assert stats["MATERIALLY_CHANGED"] == 0
    assert stats["DETAIL_RESOLVED"] == 1


def test_v139_transient_unresolved_does_not_erase_last_good_detail(tmp_path):
    state = tmp_path / "state.json"
    first = [_job()]
    apply_seen_state(first, state, "2026-08-28")

    failed = [_unresolved()]
    apply_seen_state(failed, state, "2026-08-29")
    assert failed[0]["seen_status"] == "SEEN"
    assert failed[0]["state_events"] == ["DETAIL_UNRESOLVED"]

    persisted = load_state(state)
    snapshot = next(iter(persisted["jobs"].values()))["last_snapshot"]
    assert snapshot["recommendation"] == "SKIP"
    assert snapshot["detail_status"] == "OK_HTML"
    assert snapshot["detail_words"] > 0

    recovered = [_job()]
    stats = apply_seen_state(recovered, state, "2026-08-30")
    assert recovered[0]["seen_status"] == "SEEN"
    assert recovered[0]["change_reasons"] == []
    assert recovered[0]["state_events"] == []
    assert stats["MATERIALLY_CHANGED"] == 0


def test_v139_real_full_detail_change_still_material(tmp_path):
    state = tmp_path / "state.json"
    apply_seen_state([_job()], state, "2026-08-28")
    changed = [_job(full_detail=_detail_text("completelydifferent"), recommendation="REVIEW", score=70)]
    apply_seen_state(changed, state, "2026-08-29")
    assert changed[0]["seen_status"] == "MATERIALLY_CHANGED"
    assert "recommendation" in changed[0]["change_reasons"]


def test_v139_v138_state_migrates_without_reseed(tmp_path):
    state = tmp_path / "state.json"
    first = [_job()]
    apply_seen_state(first, state, "2026-08-28")
    data = json.loads(state.read_text(encoding="utf-8"))
    data["state_version"] = "V1.38_SEEN_HISTORY_V1"
    state.write_text(json.dumps(data), encoding="utf-8")

    second = [_job()]
    stats = apply_seen_state(second, state, "2026-08-29")
    assert second[0]["seen_status"] == "SEEN"
    assert stats["NEW"] == 0
    migrated = json.loads(state.read_text(encoding="utf-8"))
    assert migrated["state_version"] == "V1.39_SEEN_HISTORY_V2"


def _args(out="out", state_file="state/seen_jobs.json"):
    return SimpleNamespace(
        source="all", history_days=None, history_max_pages=40, history_max_candidates=250,
        euraxess_pages=8, euraxess_max_candidates=80, detail_delay=None, as_of="2026-08-28",
        bist_max_pages=5, bist_max_jobs=100, institution_max_pages=4, institution_max_jobs_per_board=100,
        madrid_pages=10, madrid_max_jobs=100, fisabio_max_jobs=50, fps_max_jobs=50,
        iislafe_pages=3, iislafe_max_jobs=30, out=out, state_file=state_file, no_state=False,
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


def test_v139_newly_resolved_actionable_surfaces_daily_without_material_label(tmp_path, monkeypatch):
    import run_live_sample as cli

    current = {"job": _unresolved(
        title="Exercise Researcher", company="Example Institute",
        url="https://example.org/jobs/exercise-researcher",
        source_provenance=[{"source": "Biocat", "id": "", "url": "https://example.org/jobs/exercise-researcher", "detail_status": "FETCH_FAILED"}],
    )}
    monkeypatch.setattr(cli, "collect_sources", lambda args, out_dir: _fake_collection(current["job"]))
    monkeypatch.setattr(cli, "assert_scoring_freeze", lambda root: {"ok": True, "mismatches": []})
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    # Keep this test focused on state routing, not scoring calibration.
    monkeypatch.setattr(cli, "evaluate_job", lambda job: {
        "score": 74, "recommendation": "REVIEW", "domain_category": "CORE", "job_family": "research",
        "fit_signals": [], "partial_matches": [], "missing_requirements": [], "blockers": [], "reason": "test",
    })

    args = _args()
    first = cli.run(args)
    assert first["new_canonical"] == 1

    current["job"] = _job(
        title="Exercise Researcher", company="Example Institute",
        url="https://example.org/jobs/exercise-researcher",
        source_provenance=[{"source": "Biocat", "id": "", "url": "https://example.org/jobs/exercise-researcher", "detail_status": "OK_HTML"}],
        recommendation="REVIEW", score=74, full_detail=_detail_text("exercise"), detail_status="OK_HTML",
    )
    second = cli.run(args)
    assert second["materially_changed"] == 0
    assert second["detail_resolved"] == 1
    assert second["detail_resolved_actionable"] == 1
    assert second["daily_actionable"] == 1
    rows = list(csv.DictReader((tmp_path / "out" / "daily_actionable.csv").open(encoding="utf-8-sig")))
    assert rows[0]["seen_status"] == "SEEN"
    assert "DETAIL_RESOLVED" in rows[0]["state_events"]
