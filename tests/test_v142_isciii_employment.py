from jobbot.availability import assess_availability
from jobbot.production import SOURCE_ORDER, selected_sources
from run_live_sample import _availability_input
from sources import isciii_employment


BOARD = """
<html><body><main>
<div class="card">
<a href="/l/1889817">MPY 280-25-3M3 (IND) Start date: 08/06/2026 Deadline: 19/06/2026 Personnel class: Labour Procedure / Modality: Indefinido (Art. 23 bis LCTI) Processing</a>
</div>
<div class="card">
<a href="https://cnmt.isciii.es/l/1672589">Escala de Técnicos Especializados, TL y PI OEP 23-24-25 Start date: 02/01/2026 Deadline: 30/01/2026 Personnel class: Officer Procedure / Modality: Open access In process</a>
</div>
<a href="/cookies">Cookies</a>
</main></body></html>
"""

BOARD2 = """
<html><body><main>
<div class="card">
<a href="/l/1999999">EPY 999-26-M3 (IND) Start date: 20/08/2026 Deadline: 03/09/2026 Personnel class: Labour Procedure / Modality: Indefinido (Art. 23 bis LCTI) Initial</a>
</div>
</main></body></html>
"""

DETAIL = """
<html><body><main>
<h1>Convocatoria de empleo</h1>
<h2>Convocatoria MPY 280-25-3M3 (IND)</h2>
<div>Procedimiento/Modalidad Indefinido (Art. 23 bis LCTI)</div>
<div>Estado En tramitación</div>
<section class="document-card">
<h3>Convocatoria</h3>
<p>Observaciones: Resolución por la que se convoca proceso selectivo para contratación de tres plazas.</p>
<p>Plazo: Plazo de presentación de solicitudes del 8 al 19 de junio de 2026 (ambos inclusive)</p>
<a href="/documents/20121/112491/convocatoria-mpy280.pdf?download=true">Descargar</a>
</section>
<section class="document-card">
<h3>Convocatoria</h3><p>Observaciones: ANEXO III SOLICITUD</p>
<a href="/documents/20121/112491/anexo-iii.pdf?download=true">Descargar</a>
</section>
<section class="document-card">
<h3>Listas provisionales de admitidos y excluidos</h3>
<a href="/documents/20121/112491/listas.pdf?download=true">Descargar</a>
</section>
</main></body></html>
"""


def test_isciii_parser_extracts_official_records_deadlines_and_ids():
    jobs = isciii_employment.parse_board_html(BOARD)
    assert len(jobs) == 2
    assert jobs[0]["id"] == "isciii-1889817"
    assert jobs[0]["title"] == "MPY 280-25-3M3 (IND)"
    assert jobs[0]["date"] == "19/06/2026"
    assert jobs[0]["company"].startswith("Instituto de Salud Carlos III")
    assert jobs[1]["url"].startswith("https://cnmt.isciii.es/l/")


def test_isciii_listing_deadline_uses_existing_availability_logic():
    job = isciii_employment.parse_board_html(BOARD)[0]
    av = assess_availability(job, "2026-06-15")
    assert av["application_status"] == "OPEN"
    assert av["application_deadline"] == "2026-06-19"


def test_isciii_detail_selects_initial_call_not_application_form_or_later_documents():
    meta = isciii_employment.parse_detail_html(DETAIL, "https://www.isciii.es/l/1889817")
    assert meta["title"] == "MPY 280-25-3M3 (IND)"
    assert meta["deadline"] == "19 de junio de 2026"
    assert meta["document_urls"]
    assert "convocatoria-mpy280.pdf" in meta["document_urls"][0]
    assert all("listas.pdf" not in u for u in meta["document_urls"])


def test_isciii_is_production_source_and_all_includes_it():
    assert "isciii" in SOURCE_ORDER
    assert "isciii" in selected_sources("all")
    assert selected_sources("isciii") == ["isciii"]


def test_isciii_collects_requested_pages_and_resolves_official_call_pdf(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, **kwargs):
            if "/l/" in url:
                return Response(DETAIL, url)
            if "start=2" in url:
                return Response(BOARD2, url)
            return Response(BOARD, url)
        def close(self):
            return None

    monkeypatch.setattr(isciii_employment, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(
        isciii_employment,
        "fetch_url_text",
        lambda url, **kwargs: ("Official ISCIII call with job duties and requirements " * 80, "OK_PDF"),
    )
    diag = {}
    jobs = isciii_employment.collect(max_pages=2, max_jobs=10, diagnostics=diag)
    assert len(jobs) == 3
    assert diag["pages_fetched"] == 2
    assert diag["unique_jobs"] == 3
    assert diag["detail_success"] == 3
    assert diag["detail_failed"] == 0
    assert diag["call_documents_found"] == 3
    assert diag["coverage_complete"] is True
    assert diag["repeated_page_detected"] is False
    assert all(j["detail_status"] == "OK_PDF_ATTACHMENT" for j in jobs)


def test_isciii_first_page_failure_is_truthful_and_incomplete(monkeypatch):
    class Session:
        def get(self, *args, **kwargs):
            raise RuntimeError("offline")
        def close(self):
            return None

    monkeypatch.setattr(isciii_employment, "make_retry_session", lambda **kwargs: Session())
    diag = {}
    jobs = isciii_employment.collect(max_pages=3, diagnostics=diag)
    assert jobs == []
    assert diag["pages_fetched"] == 0
    assert len(diag["page_errors"]) == 1
    assert diag["coverage_complete"] is False


def test_isciii_page_url_supplies_liferay_delta_for_pagination():
    assert isciii_employment.page_url(1) == isciii_employment.BOARD_URL
    assert isciii_employment.page_url(2).endswith("?delta=15&start=2")


def test_isciii_repeated_page_is_detected_and_not_called_complete(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, **kwargs):
            if "/l/" in url:
                return Response(DETAIL, url)
            return Response(BOARD, url)
        def close(self):
            return None

    monkeypatch.setattr(isciii_employment, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(
        isciii_employment,
        "fetch_url_text",
        lambda url, **kwargs: ("Official ISCIII call with duties and requirements " * 80, "OK_PDF"),
    )
    diag = {}
    jobs = isciii_employment.collect(max_pages=3, diagnostics=diag)
    assert len(jobs) == 2
    assert diag["pages_fetched"] == 2
    assert diag["repeated_page_detected"] is True
    assert diag["repeated_page_number"] == 2
    assert diag["coverage_complete"] is False
    assert "pagination did not advance" in diag["coverage_warning"]


def test_isciii_availability_uses_authoritative_portal_deadline_not_pdf_range_start():
    job = {
        "source": "ISCIII Employment",
        "description": "Official ISCIII employment listing. Fecha límite: 19 de junio de 2026.",
        "full_detail": "Administrative annex. Fecha límite: 08/06/2026. Other procedural material.",
    }
    raw = assess_availability(job, "2026-06-15")
    assert raw["deadline_conflict"] is True  # generic parser sees 8 + 19
    av = assess_availability(_availability_input(job), "2026-06-15")
    assert av["application_deadline"] == "2026-06-19"
    assert av["deadline_conflict"] is False
