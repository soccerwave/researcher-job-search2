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


def _hospital_job(title: str, detail_id: str, *, job_id: str = "FIMIM3317-DOPAZO") -> dict:
    url = f"https://researchmar.net/ofertes/en_detall-oferta-temporals.html?id={detail_id}"
    return {
        "source": "Hospital del Mar Research Institute",
        "id": job_id,
        "title": title,
        "company": "Hospital del Mar Research Institute",
        "location": "Barcelona, Spain",
        "url": url,
        "trusted_full_detail_url": url,
        "application_status": "OPEN",
        "application_deadline": "",
        "recommendation": "REVIEW",
        "score": 70,
        "detail_status": "OK_HTML",
        "full_detail": ((title + " biomedical research project responsibilities. ") * 30),
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


def test_issue_b_hospital_reused_source_id_with_new_url_and_title_gets_new_state(tmp_path):
    state = tmp_path / "seen.json"
    old = _hospital_job(
        "Research Technician (Degree in Biomedical Sciences.)",
        "3390",
    )
    apply_seen_state([old], state, "2026-09-01")

    # This is the deterministic state ID produced by the reused source-ID alias that
    # caused the production collision reported for FIMIM3317-DOPAZO.
    assert old["state_id"] == "job_44f809ec70f4392a9a92"

    current = _hospital_job(
        "Researcher (PhD in Bioinformatics, Computational Biology, Life Sciences, Data Science, Mathematics, Computer Science or related disciplines).",
        "3412",
    )
    stats = apply_seen_state([current], state, "2026-10-04")

    assert current["state_id"] != old["state_id"]
    assert current["seen_status"] == "NEW"
    assert stats["NEW"] == 1
    assert stats["state_jobs"] == 2

    persisted = load_state(state)
    aliases = [set(entry.get("aliases") or []) for entry in persisted["jobs"].values()]
    assert any("url:https://researchmar.net/ofertes/en_detall-oferta-temporals.html?id=3390" in item for item in aliases)
    assert any("url:https://researchmar.net/ofertes/en_detall-oferta-temporals.html?id=3412" in item for item in aliases)


def test_issue_b_same_vacancy_keeps_state_across_tracking_and_minor_title_format_changes(tmp_path):
    state = tmp_path / "seen.json"
    first = _hospital_job(
        "Researcher (PhD in Bioinformatics, Computational Biology or related disciplines).",
        "3412",
    )
    apply_seen_state([first], state, "2026-10-03")

    second = _hospital_job(
        "Researcher [PhD in Bioinformatics and related disciplines]",
        "3412",
    )
    second["url"] += "&utm_source=weekly-feed"
    second["trusted_full_detail_url"] = second["url"]
    stats = apply_seen_state([second], state, "2026-10-04")

    assert second["state_id"] == first["state_id"]
    assert stats["state_jobs"] == 1
    assert second["seen_status"] in {"SEEN", "MATERIALLY_CHANGED"}


def test_issue_b_polluted_reused_source_id_self_heals_when_both_vacancies_are_seen(tmp_path):
    state = tmp_path / "seen.json"
    old = _hospital_job("Research Technician (Degree in Biomedical Sciences.)", "3390")
    apply_seen_state([old], state, "2026-09-01")

    data = load_state(state)
    polluted_id = old["state_id"]
    entry = data["jobs"][polluted_id]
    shared_source_alias = "source_id:hospital_del_mar_research_institute:fimim3317-dopazo"
    new_url_alias = "url:https://researchmar.net/ofertes/en_detall-oferta-temporals.html?id=3412"
    entry["aliases"].append(new_url_alias)
    state.write_text(json.dumps(data), encoding="utf-8")

    old_again = _hospital_job("Research Technician (Degree in Biomedical Sciences.)", "3390")
    current = _hospital_job(
        "Researcher (PhD in Bioinformatics, Computational Biology, Life Sciences, Data Science, Mathematics, Computer Science or related disciplines).",
        "3412",
    )
    stats = apply_seen_state([old_again, current], state, "2026-10-04")

    assert old_again["state_id"] != current["state_id"]
    assert old_again["seen_status"] == "SEEN"
    assert current["seen_status"] == "SEEN"
    assert stats["IDENTITY_SPLIT_REPAIRS"] == 1
    assert stats["state_jobs"] == 2

    repaired = load_state(state)
    old_aliases = repaired["jobs"][old_again["state_id"]]["aliases"]
    current_aliases = repaired["jobs"][current["state_id"]]["aliases"]
    assert shared_source_alias in old_aliases
    assert shared_source_alias in current_aliases
    assert new_url_alias not in old_aliases
    assert new_url_alias in current_aliases


def test_issue_b_reused_source_id_remains_disambiguated_on_next_run(tmp_path):
    state = tmp_path / "seen.json"
    old = _hospital_job("Research Technician (Degree in Biomedical Sciences.)", "3390")
    current = _hospital_job(
        "Researcher (PhD in Bioinformatics, Computational Biology, Life Sciences, Data Science, Mathematics, Computer Science or related disciplines).",
        "3412",
    )
    apply_seen_state([old], state, "2026-09-01")
    apply_seen_state([current], state, "2026-10-04")

    old_id = old["state_id"]
    current_id = current["state_id"]
    assert old_id != current_id

    old_next = _hospital_job("Research Technician (Degree in Biomedical Sciences.)", "3390")
    current_next = _hospital_job(
        "Researcher (PhD in Bioinformatics, Computational Biology, Life Sciences, Data Science, Mathematics, Computer Science or related disciplines).",
        "3412",
    )
    stats = apply_seen_state([old_next, current_next], state, "2026-10-05")

    assert old_next["state_id"] == old_id
    assert current_next["state_id"] == current_id
    assert old_next["seen_status"] == "SEEN"
    assert current_next["seen_status"] == "SEEN"
    assert stats["state_jobs"] == 2
