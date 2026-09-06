from run_live_sample import _assess_job_availability
from sources import hospital_del_mar

OPEN_DETAIL = '''
Temporary calls 28-08-2026 Research Technician Ref.: FIMIM3311-FERRÀ
Institution: FUNDACIÓ IMIM Project title: Research line in hematology clinical trials
Task: Coordination of clinical trials and Data Manager with participant visits and research documentation.
Formation: Degree in Health Sciences. Experience: Previous experience in the tasks mentioned previously.
Knowledge: Adequate level of English. Contract: Indefinit d’activitats cientifico-tècniques 12p.
Full time. Hire date September 2026.
''' * 8

CLOSED_DETAIL = OPEN_DETAIL + " Aquest procés de selecció ha finalitzat en data 26-08-2026."
SPANISH_CLOSED = OPEN_DETAIL + " Este proceso de selección ha finalizado en fecha 27-08-2026."
ENGLISH_CLOSED = OPEN_DETAIL + " This selection process has ended on 28-08-2026."


def test_hospital_del_mar_status_classifier_detects_official_closed_marker_and_date():
    status, evidence, closed_date = hospital_del_mar.classify_selection_status(CLOSED_DETAIL, "OK_HTML")
    assert status == "CLOSED"
    assert "finalitzat" in evidence.lower()
    assert closed_date == "26-08-2026"


def test_hospital_del_mar_status_classifier_accepts_locale_variants():
    assert hospital_del_mar.classify_selection_status(SPANISH_CLOSED, "OK_HTML")[0] == "CLOSED"
    assert hospital_del_mar.classify_selection_status(ENGLISH_CLOSED, "OK_HTML")[0] == "CLOSED"


def test_hospital_del_mar_resolved_detail_without_ended_marker_is_open():
    status, evidence, closed_date = hospital_del_mar.classify_selection_status(OPEN_DETAIL, "OK_HTML")
    assert status == "OPEN"
    assert "no selection-process-ended marker" in evidence
    assert closed_date == ""


def test_hospital_del_mar_unresolved_detail_remains_unknown():
    assert hospital_del_mar.classify_selection_status("", "FETCH_FAILED") == ("", "", "")


def test_source_authoritative_status_only_fills_generic_unknown():
    job = {
        "source": hospital_del_mar.SOURCE_NAME,
        "description": "Official temporary call.",
        "full_detail": OPEN_DETAIL,
        "source_application_status": "OPEN",
        "source_status_evidence": "Official page has no ended marker",
    }
    out = _assess_job_availability(job, "2026-08-29")
    assert out["application_status"] == "OPEN"
    assert out["application_deadline"] == ""
    assert out["deadline_evidence"] == "Official page has no ended marker"


def test_generic_explicit_deadline_keeps_precedence_over_source_marker():
    job = {
        "source": "Example Source",
        "description": "Application deadline: 31-08-2026",
        "full_detail": "",
        "source_application_status": "CLOSED",
        "source_status_evidence": "source marker",
    }
    out = _assess_job_availability(job, "2026-08-29")
    assert out["application_status"] == "OPEN"
    assert out["application_deadline"] == "2026-08-31"


def test_collect_records_source_status_and_diagnostics(monkeypatch):
    board = '''
    <html><body><main><ul>
      <li><span>28-08-2026</span><h4><a href="en_detall-oferta-temporals.html?id=3419">Research Technician Health Sciences</a></h4><p>Ref.: FIMIM3311-FERRÀ</p></li>
      <li><span>18-08-2026</span><h4><a href="en_detall-oferta-temporals.html?id=3410">Research Technician Biomedical Sciences</a></h4><p>Ref.: FIMIM3306-SELENT</p></li>
    </ul></main></body></html>
    '''

    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, *args, **kwargs):
            return Response(board, url)
        def close(self):
            return None

    def fake_detail(url, **kwargs):
        if "id=3410" in url:
            return CLOSED_DETAIL, "OK_HTML"
        return OPEN_DETAIL, "OK_HTML"

    monkeypatch.setattr(hospital_del_mar, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(hospital_del_mar, "fetch_url_text", fake_detail)
    diag = {}
    rows = hospital_del_mar.collect(diagnostics=diag)
    statuses = {row["id"]: row["source_application_status"] for row in rows}
    assert statuses["FIMIM3311-FERRÀ"] == "OPEN"
    assert statuses["FIMIM3306-SELENT"] == "CLOSED"
    assert diag["source_status_open"] == 1
    assert diag["source_status_closed"] == 1
    assert diag["source_status_unknown"] == 0
