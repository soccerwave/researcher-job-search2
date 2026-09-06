import json
from pathlib import Path

from jobbot.availability import assess_availability
from jobbot.production import SOURCE_ORDER
from sources import upf_melis


BOARD_FIXTURE = '''
<html><body><main>
<h2>2026</h2>
<ul>
  <li>
    <a href="/documents/d/biomed/01-oferta-scientist-melis-psr-indf-2026-29">
      Scientist (MELIS-PSR-INDF-2026-29) 07/08/2026
    </a>
  </li>
  <li>
    Investigador/a postdoctoral en l'àmbit de Neurofarmacologia (MELIS-ACCES-2026-09)
    <ul>
      <li><a href="/documents/d/biomed/bases-melis-acces-2026-09">Bases de la Convocatòria, 14/07/2026</a></li>
      <li><a href="/documents/d/biomed/admesos-melis-acces-2026-09">Llista provisional d'admesos i exclosos, 23/07/2026</a></li>
    </ul>
  </li>
  <li>
    Research Technician in Mouse Physiology and Molecular Biology (ref. MELIS-PSR-INDF-2026-12), 21/05/2026
    <ul><li><a href="/documents/d/biomed/oferta-melis-psr-indf-2026-12">Job offer</a></li></ul>
  </li>
</ul>
<h2>2025</h2>
<ul><li>Old postdoctoral role (MELIS-INV-INDF-2025-01), 02/01/2025</li></ul>
</main></body></html>
'''

DETAIL_TEXT = '''
Convocatòria: MELIS-PSR-INDF-2026-29
Línia de recerca: neurobiology and physiology.
Functions: research, analysis and scientific reporting.
Requirements: university degree and relevant research experience.
Termini de presentació de sol·licituds: 18/09/2026
'''


def test_v177_parser_uses_latest_year_and_preserves_publication_date_separately():
    jobs = upf_melis.parse_board_html(BOARD_FIXTURE)
    assert len(jobs) == 3
    assert all(j["listing_year"] == 2026 for j in jobs)
    assert all("2025-01" not in j["id"] for j in jobs)
    first = jobs[0]
    assert first["title"] == "Scientist"
    assert first["id"] == "MELIS-PSR-INDF-2026-29"
    assert first["publication_date"] == "07/08/2026"
    assert first["date"] == ""  # publication date must never become the deadline
    assert first["company"] == "Universitat Pompeu Fabra (UPF) - MELIS"
    assert first["location"] == "Barcelona, Spain"


def test_v177_parser_uses_process_paperwork_only_as_closed_evidence_not_full_detail():
    jobs = upf_melis.parse_board_html(BOARD_FIXTURE)
    neuro = next(j for j in jobs if j["id"] == "MELIS-ACCES-2026-09")
    assert neuro["portal_status"] == "CLOSED"
    assert len(neuro["detail_candidates"]) == 1
    assert "bases-melis-acces" in neuro["detail_candidates"][0]
    assert all("admesos" not in u for u in neuro["detail_candidates"])
    availability = assess_availability(neuro, "2026-08-30")
    assert availability["application_status"] == "CLOSED"


def test_v177_no_pre_scoring_relevance_filter_keeps_physio_and_other_melis_roles():
    titles = [j["title"] for j in upf_melis.parse_board_html(BOARD_FIXTURE)]
    assert "Scientist" in titles
    assert any("Neurofarmacologia" in t for t in titles)
    assert any("Mouse Physiology" in t for t in titles)


def test_v177_detail_deadline_uses_existing_availability_logic():
    assert upf_melis.extract_deadline(DETAIL_TEXT) == "18/09/2026"
    job = upf_melis.parse_board_html(BOARD_FIXTURE)[0]
    deadline = upf_melis.extract_deadline(DETAIL_TEXT)
    job["date"] = deadline
    job["description"] += f" Application deadline: {deadline}."
    result = assess_availability(job, "2026-08-30")
    assert result["application_status"] == "OPEN"
    assert result["application_deadline"] == "2026-09-18"


def test_v177_collect_resolves_official_vacancy_document(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, **kwargs):
            assert url == upf_melis.BOARD_URL
            return Response(BOARD_FIXTURE, url)
        def close(self):
            return None

    monkeypatch.setattr(upf_melis, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(
        upf_melis,
        "fetch_url_text",
        lambda url, **kwargs: (DETAIL_TEXT + (" duties requirements qualifications" * 50), "OK_PDF"),
    )
    diag = {}
    jobs = upf_melis.collect(diagnostics=diag)
    assert len(jobs) == 3
    assert diag["board_fetch"] == "OK"
    assert diag["latest_year"] == 2026
    assert diag["detail_success"] == 3
    assert diag["detail_failed"] == 0
    assert all(j["detail_status"] == "OK_PDF_ATTACHMENT" for j in jobs)
    assert all(j["date"] == "18/09/2026" for j in jobs)
    assert all(j.get("trusted_full_detail_source") == upf_melis.SOURCE_NAME for j in jobs)



def test_v177_upf_melis_collector_is_retained_only_as_historical_module():
    assert "upf" not in SOURCE_ORDER
    assert len(SOURCE_ORDER) == 22
