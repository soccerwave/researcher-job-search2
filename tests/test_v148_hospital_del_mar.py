from jobbot.availability import assess_availability
from jobbot.production import SOURCE_ORDER, selected_sources
from sources import hospital_del_mar

BOARD_FIXTURE = '''
<html><body><main><ul>
<li><span>28-08-2026</span><h4><a href="en_detall-oferta-temporals.html?id=3419">Research Technician (Bachelor's degree in Health Sciences/Sciences or equivalent qualification.)</a></h4><p>Ref.: FIMIM3311-FERRÀ</p><p>Applied clinical research in hematological malignances research group.</p></li>
<li><span>21-08-2026</span><h4><a href="/ofertes/en_detall-oferta-temporals.html?id=3405">Researcher (PhD in neuroimaging or related field.)</a></h4><p>Ref.: FIMIM3307-VILARROYA</p></li>
</ul></main></body></html>
'''

BLANK_REF_SIBLING_FIXTURE = '''
<html><body><main><ul>
<li><span>15-09-2026</span><h4><a href="/ofertes/en_detall-oferta-temporals.html?id=3412">Researcher (PhD in Bioinformatics, Computational Biology, Life Sciences, Data Science, Mathematics, Computer Science or related disciplines).</a></h4><p>Ref.: FIMIM3317-DOPAZO</p></li>
<li><span>14-09-2026</span><h4><a href="/ofertes/en_detall-oferta-temporals.html?id=3433">-</a></h4><p>Ref.:</p><p>Systems neurology and neurotherapeutics group.</p></li>
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


def test_hospital_del_mar_blank_ref_does_not_inherit_neighbouring_fimim_reference():
    rows = hospital_del_mar.parse_board_html(BLANK_REF_SIBLING_FIXTURE)
    assert len(rows) == 2
    dopazo, blank_ref = rows
    assert dopazo["id"] == "FIMIM3317-DOPAZO"
    assert dopazo["url"].endswith("?id=3412")
    # The real id=3433 page has a blank official Ref field. The vacancy-specific query
    # ID is the safe fallback identity; it must never inherit FIMIM3317-DOPAZO above.
    assert blank_ref["id"] == "3433"
    assert blank_ref["posted_date"] == "14-09-2026"
    assert blank_ref["url"].endswith("?id=3433")
    assert "FIMIM3317-DOPAZO" not in blank_ref["description"]


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
