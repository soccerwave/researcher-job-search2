from sources.fps_andalucia import BOARD_URL, collect, parse_board_html


def test_parse_fps_current_board_all_rows_no_relevance_filter():
    html = '''
    <html><body><div>3 recursos disponibles</div><table><tbody>
      <tr><td><a href="/organismos/fps/estructura/transparencia/empleo-publico/ofertas-empleo/detalle/679828.html">Investigador/a en Formación - 2467</a></td><td>Indefinido</td><td>En curso</td><td>Fundación Pública Andaluza Progreso y Salud, M.P.</td></tr>
      <tr><td><a href="/organismos/fps/estructura/transparencia/empleo-publico/ofertas-empleo/detalle/679900.html">Técnico/a de Comunicación -2468</a></td><td>Indefinido</td><td>En curso</td><td>Fundación Pública Andaluza Progreso y Salud, M.P.</td></tr>
      <tr><td><a href="/organismos/fps/estructura/transparencia/empleo-publico/ofertas-empleo/detalle/679901.html">2 Técnicos/as Auxiliares de Soluciones Digitales - 2465</a></td><td>Indefinido</td><td>En curso</td><td>Fundación Pública Andaluza Progreso y Salud, M.P.</td></tr>
    </tbody></table></body></html>
    '''
    rows, total = parse_board_html(html)
    assert total == 3
    assert len(rows) == 3
    assert {r["job_code"] for r in rows} == {"2467", "2468", "2465"}
    assert all(r["source"] == "Fundación Progreso y Salud" for r in rows)
    assert all(r["source_listing_active"] is True for r in rows)


def test_parse_fps_deduplicates_detail_links_and_ignores_other_links():
    html = '''
    <html><body><div>1 recurso disponible</div>
      <a href="/contacto">Contacto</a>
      <table><tr><td>
        <a href="/organismos/fps/estructura/transparencia/empleo-publico/ofertas-empleo/detalle/679828.html">Investigador/a en Formación - 2467</a>
        <a href="/organismos/fps/estructura/transparencia/empleo-publico/ofertas-empleo/detalle/679828.html#x">duplicado</a>
      </td><td>Indefinido</td><td>En curso</td></tr></table>
    </body></html>
    '''
    rows, total = parse_board_html(html)
    assert total == 1
    assert len(rows) == 1
    assert rows[0]["id"] == "junta-679828"


def test_collect_fps_resolves_full_detail_and_extracts_deadline(monkeypatch):
    board_html = '''
    <html><body><div>1 recurso disponible</div><table><tr>
      <td><a href="/organismos/fps/estructura/transparencia/empleo-publico/ofertas-empleo/detalle/679828.html">Investigador/a en Formación - 2467</a></td>
      <td>Indefinido</td><td>En curso</td><td>Fundación Pública Andaluza Progreso y Salud, M.P.</td>
    </tr></table></body></html>
    '''
    class Resp:
        def __init__(self):
            self.url = BOARD_URL
            self.text = board_html
        def raise_for_status(self):
            return None
    class Session:
        def get(self, url, *args, **kwargs):
            assert url == BOARD_URL
            return Resp()
        def close(self):
            pass
    monkeypatch.setattr("sources.fps_andalucia.make_retry_session", lambda **kwargs: Session())
    detail = (
        "Oferta de empleo Investigador/a en Formación - 2467 Información general "
        "Plazo de solicitud 11/08/2026 - 31/08/2026 Lugar de trabajo Granada (Granada) "
        "Tipo de contrato Indefinido Titulación oficial requerida Grado Universitario "
        "Otros requisitos Requerimientos mínimos investigación biomédica laboratorio "
        "Funciones desarrollo de terapias celulares avanzadas. " * 8
    )
    monkeypatch.setattr("sources.fps_andalucia.fetch_url_text", lambda *args, **kwargs: (detail, "OK_HTML"))
    diag = {}
    rows = collect(diagnostics=diag)
    assert len(rows) == 1
    assert rows[0]["detail_status"] == "OK_HTML"
    assert rows[0]["application_window_end"] == "31/08/2026"
    assert "Application deadline: 31/08/2026" in rows[0]["description"]
    assert rows[0]["location"].startswith("Granada (Granada)")
    assert diag["detail_success"] == 1
    assert diag["coverage_complete"] is True


def test_collect_fps_truthfully_flags_reported_count_mismatch(monkeypatch):
    board_html = '''
    <html><body><div>2 recursos disponibles</div><table><tr>
      <td><a href="/organismos/fps/estructura/transparencia/empleo-publico/ofertas-empleo/detalle/679828.html">Investigador/a en Formación - 2467</a></td>
      <td>Indefinido</td><td>En curso</td>
    </tr></table></body></html>
    '''
    class Resp:
        url = BOARD_URL
        text = board_html
        def raise_for_status(self): return None
    class Session:
        def get(self, *args, **kwargs): return Resp()
        def close(self): pass
    monkeypatch.setattr("sources.fps_andalucia.make_retry_session", lambda **kwargs: Session())
    diag = {}
    rows = collect(diagnostics=diag, enrich_detail=False)
    assert len(rows) == 1
    assert diag["total_reported"] == 2
    assert diag["coverage_complete"] is False
    assert "reported 2" in diag["coverage_warning"]
