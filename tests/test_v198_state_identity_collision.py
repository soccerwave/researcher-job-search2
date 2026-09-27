import json

from jobbot.state import apply_seen_state, load_state


def _job(job_id: str, url: str):
    return {
        "source": "Institutions",
        "id": job_id,
        "title": "VHIR-MSCA Predoctoral Fellowship",
        "company": "VHIR",
        "location": "Barcelona, Spain",
        "url": url,
        "trusted_full_detail_url": url,
        "application_status": "OPEN",
        "application_deadline": "2026-10-15",
        "recommendation": "SKIP",
        "score": 0,
        "detail_status": "OK",
        "full_detail": ("Predoctoral fellowship biomedical research training requirements. " * 30),
    }


def test_v198_distinct_stable_ids_with_same_ctl_do_not_merge(tmp_path):
    state = tmp_path / "seen.json"
    a = _job("8353742", "https://jobs.vhir.org/jobs/8353742-vhir-msca-predoctoral-fellowship")
    b = _job("8353614", "https://jobs.vhir.org/jobs/8353614-vhir-msca-predoctoral-fellowship")

    stats = apply_seen_state([a, b], state, "2026-09-27")

    assert a["state_id"] != b["state_id"]
    assert a["seen_status"] == "NEW"
    assert b["seen_status"] == "NEW"
    assert stats["NEW"] == 2
    assert stats["IDENTITY_SPLIT_REPAIRS"] == 0


def test_v198_legacy_polluted_state_self_heals_without_false_new(tmp_path):
    state = tmp_path / "seen.json"
    a = _job("8353742", "https://jobs.vhir.org/jobs/8353742-vhir-msca-predoctoral-fellowship")
    b = _job("8353614", "https://jobs.vhir.org/jobs/8353614-vhir-msca-predoctoral-fellowship")

    # Create a valid state for A first.
    apply_seen_state([a], state, "2026-09-20")
    data = load_state(state)
    old_state_id = a["state_id"]
    entry = data["jobs"][old_state_id]

    # Simulate legacy corruption: B's strong aliases were appended to A's state record
    # because older logic matched only on company/title/location.
    entry["aliases"].extend([
        "source_id:institutions:8353614",
        "url:https://jobs.vhir.org/jobs/8353614-vhir-msca-predoctoral-fellowship",
    ])
    state.write_text(json.dumps(data), encoding="utf-8")

    a2 = _job("8353742", "https://jobs.vhir.org/jobs/8353742-vhir-msca-predoctoral-fellowship")
    b2 = _job("8353614", "https://jobs.vhir.org/jobs/8353614-vhir-msca-predoctoral-fellowship")
    stats = apply_seen_state([a2, b2], state, "2026-09-27")

    assert a2["state_id"] != b2["state_id"]
    assert a2["seen_status"] == "SEEN"
    assert b2["seen_status"] == "SEEN"
    assert stats["IDENTITY_SPLIT_REPAIRS"] == 1

    repaired = load_state(state)
    assert len(repaired["jobs"]) == 2

    a_aliases = repaired["jobs"][a2["state_id"]]["aliases"]
    b_aliases = repaired["jobs"][b2["state_id"]]["aliases"]
    assert "source_id:institutions:8353742" in a_aliases
    assert "source_id:institutions:8353614" not in a_aliases
    assert "source_id:institutions:8353614" in b_aliases


def test_v198_weak_identity_fallback_still_works_when_no_stable_identity(tmp_path):
    state = tmp_path / "seen.json"
    row1 = {
        "source": "Legacy Board",
        "id": "",
        "title": "Research Coordinator",
        "company": "Example Institute",
        "location": "Madrid, Spain",
        "url": "https://example.org/jobs",
        "application_status": "OPEN",
        "recommendation": "REVIEW",
        "score": 70,
        "detail_status": "OK",
        "full_detail": ("Research coordination role. " * 30),
    }
    apply_seen_state([row1], state, "2026-09-20")

    row2 = dict(row1)
    stats = apply_seen_state([row2], state, "2026-09-27")

    assert row2["seen_status"] == "SEEN"
    assert stats["SEEN"] == 1
