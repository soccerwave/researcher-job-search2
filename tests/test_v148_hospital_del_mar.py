from jobbot.availability import assess_availability
from jobbot.production import SOURCE_ORDER, selected_sources
from sources import hospital_del_mar

BOARD_FIXTURE = '''
<html><body><main><ul>
<li><span>28-08-2026</span><h4><a href="en_detall-oferta-temporals.html?id=3419">Research Technician (Bachelor's degree in Health Sciences/Sciences or equivalent qualification.)</a></h4><p>Ref.: FIMIM3311-FERRÀ</p><p>Applied clinical research in hematological malignances research group.</p></li>
<li><span>21-08-2026</span><h4><a href="/ofertes/en_detall-oferta-temporals.html?id=3405">Researcher (PhD in neuroimaging or related field.)</a></h4><p>Ref.: FIMIM3307-VILARROYA</p></li>
</ul></main></body></html>
'''

DETAIL_FIXTURE = '''
<html><body><main><h1>Temporary calls</h1><p>28-08-2026</p>
<h3>Research Technician (Bachelor's degree in Health Sciences/Sciences or equivalent qualification.)</h3>
<p>Ref.: FIMIM3311-FERRÀ</p><p>Institution: FUNDACIÓ IMIM</p><p>Project title: Research line in hematology clinical trials</p>
<p>Task: Coordination of clinical trials and Data Manager, preparation of start visits, monitoring, audit, CRF data entry, SAE communication, participant visits, sample and image management.</p>
<p>Formation: Degree in Health Sciences or equivalent. Training in clinical trials will be valued.</p>
<p>Experience: Previous experience in the tasks mentioned previously.</p><p>Knowledge: Adequate level of English.</p>
''' + ('Clinical research coordination trial data management research support. ' * 20) + '''</main></body></html>
'''


def test_hospital_del_mar_board_parser_reads_job_specific_calls_without_treating_posted_date_as_deadline():
    rows = hospital_del_mar.parse_board_html(BOARD_FIXTURE)
    assert len(rows) == 2
    assert rows[0]["id"] == "FIMIM3311-FERRÀ"
    assert rows[0]["posted_date"] == "28-08-2026"
    assert rows[0]["date"] == ""
    assert rows[0]["url"].endswith("en_detall-oferta-temporals.html?id=3419")


def test_hospital_del_mar_posting_date_does_not_close_job_via_existing_availability_parser():
    row = hospital_del_mar.parse_board_html(BOARD_FIXTURE)[0]
    result = assess_availability(row, "2026-08-29")
    assert result["application_status"] == "UNKNOWN"
    assert result["application_deadline"] == ""


def test_hospital_del_mar_is_production_source():
    assert "hospitaldelmar" in SOURCE_ORDER
    assert selected_sources("hospitaldelmar") == ["hospitaldelmar"]
    assert "hospitaldelmar" in selected_sources("all")


def test_hospital_del_mar_collect_uses_vacancy_specific_page_as_full_jd(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, *args, **kwargs):
            return Response(BOARD_FIXTURE, url)
        def close(self):
            return None

    monkeypatch.setattr(hospital_del_mar, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(hospital_del_mar, "fetch_url_text", lambda url, **kwargs: (DETAIL_FIXTURE, "OK_HTML"))
    diag = {}
    rows = hospital_del_mar.collect(diagnostics=diag)
    assert len(rows) == 2
    assert diag["board_fetch"] == "OK"
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 0
    assert diag["coverage_complete"] is True
    assert all(r["detail_status"] == "OK_HTML" for r in rows)
    assert all(r["trusted_full_detail_source"] == hospital_del_mar.SOURCE_NAME for r in rows)
