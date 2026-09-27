from pathlib import Path

import run_live_sample
from jobbot.state import apply_seen_state, load_state


def _api_job():
    return {
        "source": "Fundación Progreso y Salud",
        "id": "junta-999999",
        "title": "Técnico/a de Investigación",
        "company": "Fundación Pública Andaluza Progreso y Salud",
        "location": "Sevilla, Spain",
        "url": "https://www.juntadeandalucia.es/example/999999.html",
        "application_status": "OPEN",
        "application_deadline": "2026-10-15",
        "recommendation": "REVIEW",
        "score": 68,
        "detail_status": "OK_API",
        "full_detail": (
            "Oferta de empleo Técnico/a de Investigación. "
            "Funciones gestión y coordinación de proyectos de investigación, "
            "apoyo a convocatorias competitivas, reporting científico y seguimiento. "
        ) * 8,
    }


def test_v197_ok_api_is_full_detail_for_scoring():
    assert run_live_sample._has_full_detail(_api_job()) is True


def test_v197_ok_api_is_resolved_for_state(tmp_path):
    state_path = tmp_path / "seen.json"
    row = _api_job()
    stats = apply_seen_state([row], state_path, "2026-09-27")

    assert stats["DETAIL_UNRESOLVED"] == 0
    assert row["seen_status"] == "NEW"

    state = load_state(state_path)
    snapshot = next(iter(state["jobs"].values()))["last_snapshot"]
    assert snapshot["detail_status"] == "OK_API"
    assert snapshot["detail_words"] > 0
