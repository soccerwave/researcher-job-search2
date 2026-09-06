from argparse import Namespace

from jobbot.production import SOURCE_ORDER, selected_sources
from sources import csic_sede


PAGE0 = """
<html><body><main>
<div class="view-row"><span>30/07/2026</span>
<a href="/tramites/convocatorias-de-personal/convocatoria/38221">Predoctoral Santiago Grisolía 2026 (Ref.38221)</a></div>
<div class="view-row"><span>09/07/2026</span>
<a href="https://sede.csic.gob.es/tramites/convocatorias-de-personal/convocatoria/38218">PERSONAL LABORAL FIJO - ACCESO LIBRE (Ref.38218)</a></div>
<a href="/tramites/convocatorias-de-personal?page=1">››</a>
</main></body></html>
"""

PAGE1 = """
<html><body><main>
<div class="view-row"><span>10/04/2026</span>
<a href="/tramites/convocatorias-de-personal/convocatoria/38198">Provisión de puestos de trabajo por libre designación (Ref.38198)</a></div>
</main></body></html>
"""


def test_csic_parser_extracts_official_detail_links_ids_and_publication_dates():
    jobs = csic_sede.parse_board_html(PAGE0)
    assert len(jobs) == 2
    assert jobs[0]["id"] == "38221"
    assert jobs[0]["date"] == "30/07/2026"
    assert jobs[0]["company"] == "CSIC"
    assert jobs[0]["url"].endswith("/convocatoria/38221")
    assert jobs[1]["id"] == "38218"


def test_csic_is_production_source_and_all_includes_it():
    assert "csic" in SOURCE_ORDER
    assert "csic" in selected_sources("all")
    assert selected_sources("csic") == ["csic"]


def test_csic_collects_requested_newest_pages_and_enriches_detail(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, **kwargs):
            return Response(PAGE1 if "page=1" in url else PAGE0, url)
        def close(self):
            return None

    monkeypatch.setattr(csic_sede, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(csic_sede, "fetch_url_text", lambda url, **kwargs: ("Full CSIC job description " * 80, "OK_HTML"))
    diag = {}
    jobs = csic_sede.collect(max_pages=2, diagnostics=diag)
    assert len(jobs) == 3
    assert diag["pages_fetched"] == 2
    assert diag["page_errors"] == []
    assert diag["detail_success"] == 3
    assert diag["detail_failed"] == 0
    assert diag["coverage_complete"] is True
    assert diag["portal_full_coverage"] is False


def test_csic_first_page_failure_is_reported_as_incomplete(monkeypatch):
    class Session:
        def get(self, *args, **kwargs):
            raise RuntimeError("offline")
        def close(self):
            return None

    monkeypatch.setattr(csic_sede, "make_retry_session", lambda **kwargs: Session())
    diag = {}
    jobs = csic_sede.collect(max_pages=2, diagnostics=diag)
    assert jobs == []
    assert diag["pages_fetched"] == 0
    assert len(diag["page_errors"]) == 1
    assert diag["coverage_complete"] is False
