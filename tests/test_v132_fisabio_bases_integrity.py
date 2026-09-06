from sources.fisabio import _find_bases_url, collect


def test_find_bases_url_prefers_stable_download_route():
    html = '''
    <html><body>
      <a href="/convocatoriaspropias/es/Convocatorias/DescargarDocumentoBases/871">Bases de la Convocatoria</a>
      <a href="/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871">volver</a>
    </body></html>
    '''
    url = _find_bases_url(
        html,
        "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871",
    )
    assert url.endswith("/Convocatorias/DescargarDocumentoBases/871")


def test_collect_fisabio_scores_only_bases_not_long_application_shell(monkeypatch):
    board_url = "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/DetalleTipoConvocatoria/EMPLEO?Estado=A"
    detail_url = "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871"
    bases_url = "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/DescargarDocumentoBases/871"

    class Resp:
        def __init__(self, url, text):
            self.status_code = 200
            self.url = url
            self.text = text
        def raise_for_status(self):
            return None

    board_html = '''<table><tr><td><a href="/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871">2026/58 UN/A TÉCNICO/A DE GESTIÓN DE LA INVESTIGACIÓN (M3)</a></td><td>17/08/2026</td><td>01/09/2026</td></tr></table>'''
    shell_html = ('''<html><body><h1>Información de la Convocatoria</h1>'''
                  '''<p>RECOMENDACIONES A TENER EN CUENTA ANTES DE INICIAR LA INSCRIPCION.</p>''' * 80 +
                  '''<a href="/convocatoriaspropias/es/Convocatorias/DescargarDocumentoBases/871">Bases de la Convocatoria</a></body></html>''')

    class Session:
        def get(self, url, *args, **kwargs):
            if url == board_url:
                return Resp(board_url, board_html)
            if url == detail_url:
                return Resp(detail_url, shell_html)
            raise AssertionError(f"unexpected session.get {url}")
        def close(self):
            pass

    monkeypatch.setattr("sources.fisabio.make_retry_session", lambda **kwargs: Session())
    seen = {}
    def fake_fetch(url, **kwargs):
        seen["url"] = url
        return ("REQUISITOS NECESARIOS FUNCIONES EXPERIENCIA GESTION PROYECTOS EUROPEOS " * 20, "OK_PDF")
    monkeypatch.setattr("sources.fisabio.fetch_url_text", fake_fetch)

    diag = {}
    rows = collect(diagnostics=diag)
    assert len(rows) == 1
    assert seen["url"] == bases_url
    assert rows[0]["detail_status"] == "OK_PDF_ATTACHMENT"
    assert "RECOMENDACIONES A TENER" not in rows[0]["full_detail"]
    assert rows[0]["bases_url"] == bases_url
    assert diag["bases_links_found"] == 1
    assert diag["bases_fetch_success"] == 1
    assert diag["detail_success"] == 1


def test_collect_fisabio_does_not_score_shell_when_bases_missing(monkeypatch):
    board_url = "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/DetalleTipoConvocatoria/EMPLEO?Estado=A"
    detail_url = "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871"

    class Resp:
        def __init__(self, url, text):
            self.status_code = 200
            self.url = url
            self.text = text
        def raise_for_status(self):
            return None

    board_html = '''<table><tr><td><a href="/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871">2026/58 UN/A TÉCNICO/A</a></td><td>17/08/2026</td><td>01/09/2026</td></tr></table>'''
    shell_html = "<html><body>" + ("generic application instructions " * 200) + "</body></html>"

    class Session:
        def get(self, url, *args, **kwargs):
            if url == board_url:
                return Resp(board_url, board_html)
            if url == detail_url:
                return Resp(detail_url, shell_html)
            raise AssertionError(url)
        def close(self):
            pass

    monkeypatch.setattr("sources.fisabio.make_retry_session", lambda **kwargs: Session())
    diag = {}
    rows = collect(diagnostics=diag)
    assert rows[0]["full_detail"] == ""
    assert rows[0]["detail_status"] == "FISABIO_BASES_LINK_NOT_FOUND"
    assert diag["detail_failed"] == 1
    assert diag["bases_fetch_failed"] == 1
