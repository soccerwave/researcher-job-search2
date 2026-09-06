import json
from pathlib import Path

from jobbot.state import apply_seen_state, load_state


def _detail(seed="research"):
    return " ".join(([seed, "human", "research", "project", "analysis", "coordination", "health", "data"] * 20))


def _resolved(**overrides):
    row = {
        "source": "Madrid I+D+i",
        "id": "63260",
        "title": "Research Project Coordinator",
        "company": "Example Institute",
        "location": "Pozuelo de Alarcón, Madrid",
        "modality": "onsite",
        "url": "https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/63260",
        "application_status": "CLOSED",
        "application_deadline": "2026-08-28",
        "recommendation": "SKIP",
        "score": 31,
        "detail_status": "OK",
        "full_detail": _detail(),
    }
    row.update(overrides)
    return row


def _degraded(**overrides):
    row = _resolved(
        location="Madrid",
        modality="",
        application_status="OPEN",
        application_deadline="",
        recommendation="NEEDS_DETAIL_REVIEW",
        score="",
        detail_status="POEM_RELAY_HTTP_504",
        full_detail="",
    )
    row.update(overrides)
    return row


def test_v174_degraded_detail_does_not_create_false_change_or_reopen(tmp_path):
    state = tmp_path / "state.json"
    apply_seen_state([_resolved()], state, "2026-08-28")

    current = [_degraded()]
    stats = apply_seen_state(current, state, "2026-08-29")

    assert current[0]["seen_status"] == "SEEN"
    assert current[0]["change_reasons"] == []
    assert current[0]["state_events"] == ["DETAIL_UNRESOLVED"]
    assert stats["MATERIALLY_CHANGED"] == 0
    assert stats["REOPENED"] == 0
    assert stats["DETAIL_UNRESOLVED"] == 1

    snapshot = next(iter(load_state(state)["jobs"].values()))["last_snapshot"]
    assert snapshot["location"] == "pozuelo de alarcon madrid"
    assert snapshot["modality"] == "onsite"
    assert snapshot["application_deadline"] == "2026-08-28"
    assert snapshot["application_status"] == "CLOSED"
    assert snapshot["recommendation"] == "SKIP"
    assert snapshot["detail_status"] == "OK"


def test_v174_recovery_after_degradation_is_clean_seen(tmp_path):
    state = tmp_path / "state.json"
    apply_seen_state([_resolved()], state, "2026-08-28")
    apply_seen_state([_degraded()], state, "2026-08-29")

    recovered = [_resolved()]
    stats = apply_seen_state(recovered, state, "2026-08-30")
    assert recovered[0]["seen_status"] == "SEEN"
    assert recovered[0]["change_reasons"] == []
    assert recovered[0]["state_events"] == []
    assert stats["MATERIALLY_CHANGED"] == 0
    assert stats["REOPENED"] == 0


def test_v174_identity_change_is_still_detected_during_detail_failure(tmp_path):
    state = tmp_path / "state.json"
    apply_seen_state([_resolved()], state, "2026-08-28")

    changed = [_degraded(title="Senior Research Project Coordinator")]
    apply_seen_state(changed, state, "2026-08-29")
    assert changed[0]["seen_status"] == "MATERIALLY_CHANGED"
    assert changed[0]["change_reasons"] == ["title"]
    assert changed[0]["state_events"] == ["DETAIL_UNRESOLVED"]


def test_v174_manifest():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "PRODUCTION_VERSION.json").read_text(encoding="utf-8"))
    assert manifest["production_version"] == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"
    assert manifest["scoring_engine"] == "V1.36_FINAL_SCORING_CLEANUP"


def test_v174_unresolved_degradation_does_not_pollute_daily_actionable(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import run_live_sample as cli
    from jobbot.production import SOURCE_ORDER

    current = {"job": _resolved(application_status="OPEN", application_deadline="2026-09-15")}

    def fake_collection(args, out_dir):
        job = current["job"]
        return {
            "jobs": [job], "errors": [], "warnings": [],
            "diagnostics": {key: ({"detail_success": int(job["detail_status"] == "OK"), "detail_failed": int(job["detail_status"] != "OK")} if key == "madrid" else None) for key in SOURCE_ORDER},
            "source_runs": {"madrid": {
                "source": "Madrid I+D+i", "status": "OK", "jobs_collected": 1,
                "coverage_complete": True, "detail_resolution_complete": job["detail_status"] == "OK",
                "detail_success": int(job["detail_status"] == "OK"),
                "detail_failed": int(job["detail_status"] != "OK"), "truncated": 0,
                "error": "", "warnings": [],
            }},
            "selected_sources": ["madrid"], "euraxess_audit": [],
        }

    monkeypatch.setattr(cli, "collect_sources", fake_collection)
    monkeypatch.setattr(cli, "assert_scoring_freeze", lambda root: {"ok": True, "mismatches": []})
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "evaluate_job", lambda job: {
        "score": 55, "recommendation": "LOW_PRIORITY", "domain_category": "CORE", "job_family": "research",
        "fit_signals": [], "partial_matches": [], "missing_requirements": [], "blockers": [], "reason": "test",
    })

    args = SimpleNamespace(
        source="all", history_days=None, history_max_pages=40, history_max_candidates=250,
        euraxess_pages=8, euraxess_max_candidates=80, detail_delay=None, as_of="2026-08-28",
        bist_max_pages=5, bist_max_jobs=100, institution_max_pages=4, institution_max_jobs_per_board=100,
        madrid_pages=10, madrid_max_jobs=100, fisabio_max_jobs=50, fps_max_jobs=50,
        iislafe_pages=3, iislafe_max_jobs=30, out="out", state_file="state/seen.json", no_state=False,
    )
    first = cli.run(args)
    assert first["new_actionable"] == 1

    current["job"] = _degraded(application_status="OPEN", application_deadline="")
    args.as_of = "2026-08-29"
    second = cli.run(args)
    assert second["materially_changed"] == 0
    assert second["reopened"] == 0
    assert second["detail_unresolved"] == 1
    assert second["daily_actionable"] == 0
    assert second["changed_or_reopened_actionable"] == 0
