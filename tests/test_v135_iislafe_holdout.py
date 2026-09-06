from io import BytesIO

from pypdf import PdfWriter

from sources.iislafe import BOARD_URL, collect, page_url, parse_board_html, parse_detail_html
from sources.fetch_detail import fetch_url_text


def test_iislafe_board_parser_carries_all_roles_and_metadata():
    html = '''
    <html><body>
      <section class="offer">
        <h2><a href="/es/talento/empleo/4165/contratacion-de-facultativo-especialista">Contratación de Facultativo especialista de investigación (T3) - Reumatología Pediátrica</a></h2>
        <div>Abierta</div><div>Número de referencia: 140/2026</div><div>Plazo de presentación: 10/09/2026</div>
        <div>Documentación: <a href="https://remote.iislafe.san.gva.es/ServicioIIS/api/convocatorias/es/4165/ficheros/17402">Bases</a></div>
      </section>
      <section class="offer">
        <h2><a href="/es/talento/empleo/4162/contratacion-de-tecnico-big-data">Contratación de Técnico/a de investigación (T3) - Plataforma de Big Data, IA, Bioinformática y Bioestadística</a></h2>
        <div>Abierta</div><div>Número de referencia: 137/2026</div><div>Plazo de presentación: 09/09/2026</div>
        <a href="https://remote.iislafe.san.gva.es/ServicioIIS/api/convocatorias/es/4162/ficheros/17387">Bases</a>
      </section>
      <a href="/es/talento/empleo/">Empleo</a>
    </body></html>
    '''
    rows = parse_board_html(html)
    assert len(rows) == 2
    assert {r["id"] for r in rows} == {"iislafe-4165", "iislafe-4162"}
    assert {r["job_reference"] for r in rows} == {"140/2026", "137/2026"}
    assert all(r["portal_state"] == "Abierta" for r in rows)
    assert all("Application deadline:" in r["description"] for r in rows)
    assert all(r["bases_url"].startswith("https://remote.iislafe") for r in rows)


def test_iislafe_detail_parser_extracts_official_bases_identity_and_deadline():
    html = '''
      <html><body><main>
        <div>Martes, 25 de agosto de 2026</div>
        <h1>Contratación de Técnico/a de investigación (T3) - Plataforma de Big Data, IA, Bioinformática y Bioestadística</h1>
        <div>Abierta</div>
        <p>Número de referencia: 137/2026</p>
        <p>Plazo de presentación: 09/09/2026</p>
        <div>Documentación: <a href="https://remote.iislafe.san.gva.es/ServicioIIS/api/convocatorias/es/4162/ficheros/17387">Bases</a></div>
      </main></body></html>
    '''
    meta = parse_detail_html(html, "https://www.iislafe.es/es/talento/empleo/4162/x")
    assert meta["reference"] == "137/2026"
    assert meta["deadline"] == "09/09/2026"
    assert meta["portal_state"] == "Abierta"
    assert meta["bases_url"].endswith("/17387")
    assert meta["title"].startswith("Contratación de Técnico/a")


def test_shared_fetcher_accepts_extensionless_octet_stream_pdf(monkeypatch):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = BytesIO(); writer.write(buf)
    payload = buf.getvalue()

    class Resp:
        url = "https://remote.example/api/ficheros/17387"
        content = payload
        text = ""
        headers = {"content-type": "application/octet-stream"}
        def raise_for_status(self): return None
    class Session:
        def get(self, *args, **kwargs): return Resp()
        def close(self): pass
    # Blank PDF has no extractable text; reaching EMPTY_DETAIL proves it was parsed as PDF,
    # not decoded as an HTML/binary gibberish page.
    text, status = fetch_url_text(Resp.url, session=Session(), title_hint="")
    assert text == ""
    assert status == "EMPTY_DETAIL"


def test_iislafe_page_urls_are_stable():
    assert page_url(1) == BOARD_URL
    assert page_url(2).endswith("/es/talento/empleo/page/2")
    assert page_url(3).endswith("/es/talento/empleo/page/3")


def test_iislafe_collect_uses_detail_page_then_bases_and_truthful_scope(monkeypatch):
    board1 = '''<html><body><section><h2><a href="/es/talento/empleo/4165/a">Contratación de Facultativo especialista de investigación (T3) - Reumatología</a></h2><div>Abierta</div><div>Número de referencia: 140/2026</div><div>Plazo de presentación: 10/09/2026</div></section></body></html>'''
    board2 = '''<html><body><section><h2><a href="/es/talento/empleo/4158/b">Contratación de Ayudante técnico de gestión de la investigación (M2) - Área de Investigación Clínica</a></h2><div>Cerrada pendiente de evaluar</div><div>Número de referencia: 134/2026</div><div>Plazo de presentación: 19/08/2026</div></section></body></html>'''
    detail_map = {
        "4165": '''<html><main><h1>Contratación de Facultativo especialista de investigación (T3) - Reumatología</h1><div>Abierta</div><div>Número de referencia: 140/2026</div><div>Plazo de presentación: 10/09/2026</div><a href="https://remote.iislafe/a">Bases</a></main></html>''',
        "4158": '''<html><main><h1>Contratación de Ayudante técnico de gestión de la investigación (M2) - Área de Investigación Clínica</h1><div>Cerrada pendiente de evaluar</div><div>Número de referencia: 134/2026</div><div>Plazo de presentación: 19/08/2026</div><a href="https://remote.iislafe/b">Bases</a></main></html>''',
    }
    class Resp:
        def __init__(self, url, text): self.url=url; self.text=text
        def raise_for_status(self): return None
    class Session:
        def get(self, url, *args, **kwargs):
            if url == page_url(1): return Resp(url, board1)
            if url == page_url(2): return Resp(url, board2)
            for k,v in detail_map.items():
                if f"/{k}/" in url: return Resp(url, v)
            raise AssertionError(url)
        def close(self): pass
    monkeypatch.setattr("sources.iislafe.make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr("sources.iislafe.fetch_url_text", lambda url, **kwargs: ("Research vacancy requirements and functions " * 30, "OK_PDF"))
    diag = {}
    rows = collect(diagnostics=diag, max_pages=2, max_jobs=10)
    assert len(rows) == 2
    assert diag["pages_fetched"] == 2
    assert diag["detail_page_success"] == 2
    assert diag["bases_links_found"] == 2
    assert diag["detail_success"] == 2
    assert diag["detail_status_counts"] == {"OK_PDF_ATTACHMENT": 2}
    assert diag["coverage_complete"] is True
    assert diag["portal_full_coverage"] is False
    assert {r["date"] for r in rows} == {"10/09/2026", "19/08/2026"}


def test_iislafe_collect_flags_page_failure_instead_of_claiming_coverage(monkeypatch):
    board1 = '''<html><body><section><h2><a href="/es/talento/empleo/4165/a">Contratación de Facultativo especialista de investigación (T3) - Reumatología</a></h2><div>Abierta</div><div>Número de referencia: 140/2026</div><div>Plazo de presentación: 10/09/2026</div></section></body></html>'''
    class Resp:
        def __init__(self, url, text): self.url=url; self.text=text
        def raise_for_status(self): return None
    class Session:
        def get(self, url, *args, **kwargs):
            if url == page_url(1): return Resp(url, board1)
            raise RuntimeError("page down")
        def close(self): pass
    monkeypatch.setattr("sources.iislafe.make_retry_session", lambda **kwargs: Session())
    diag = {}
    rows = collect(diagnostics=diag, max_pages=2, max_jobs=10, enrich_detail=False)
    assert len(rows) == 1
    assert diag["pages_fetched"] == 1
    assert len(diag["page_errors"]) == 1
    assert diag["coverage_complete"] is False
    assert "incomplete" in diag["coverage_warning"].lower()
