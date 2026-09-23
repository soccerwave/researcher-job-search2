from datetime import date, timedelta

from sources.fps_andalucia import (
    BOARD_URL,
    OPEN_DATA_SEARCH_URL,
    FPS_ORGANISM_SLUG,
    collect,
    parse_board_html,
)


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


def _api_row(record_id: str, title: str, deadline: str) -> dict:
    return {
        "id": record_id,
        "job_name": title,
        "job_official_degree_requirements": "Grado Universitario",
        "job_specific_degree_requirements": "<p>Ciencias de la Salud</p>",
        "organisms": [{"organism": FPS_ORGANISM_SLUG}],
        "announcement_type": "Oferta de empleo",
        "announcement_status": "En curso",
        "functions": "<ul><li>Gestión de proyectos de investigación</li></ul>",
        "job_agreement": "Indefinido",
        "job_location": [{
            "locality": "Sevilla",
            "field_lugar_provincia": [{"provinces": "Sevilla"}],
        }],
        "job_code": "44-2026",
        "publish_date": "2026-09-15",
        "job_number_places": "1",
        "job_other_requirements": "<p>Experiencia en investigación clínica</p>",
        "deadline_application": deadline,
    }


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.url = OPEN_DATA_SEARCH_URL

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, *args, **kwargs):
        self.calls.append((url, kwargs))
        assert url == OPEN_DATA_SEARCH_URL
        return _Resp(self.payload)

    def close(self):
        pass


def test_collect_fps_uses_official_api_and_builds_full_detail(monkeypatch):
    future = (date.today() + timedelta(days=10)).isoformat()
    payload = {
        "hits": 1,
        "total_hits": 1,
        "results": [_api_row("683584", "Técnico/a de Investigación 44-2026", future)],
    }
    session = _Session(payload)
    monkeypatch.setattr("sources.fps_andalucia.make_retry_session", lambda **kwargs: session)

    diag = {}
    rows = collect(diagnostics=diag)

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "junta-683584"
    assert row["detail_status"] == "OK_API"
    assert row["application_window_end"] == future
    assert "Gestión de proyectos de investigación" in row["full_detail"]
    assert "Experiencia en investigación clínica" in row["full_detail"]
    assert row["location"].startswith("Sevilla")
    assert diag["feed_mode"] == "official_junta_open_data_api_deadline_filtered"
    assert diag["detail_success"] == 1
    assert diag["detail_failed"] == 0
    assert diag["coverage_complete"] is True

    _, kwargs = session.calls[0]
    assert kwargs["params"]["organism"] == FPS_ORGANISM_SLUG
    assert kwargs["params"]["announcement_status"] == "En curso"


def test_collect_fps_filters_stale_en_curso_rows_by_deadline(monkeypatch):
    future = (date.today() + timedelta(days=5)).isoformat()
    past = (date.today() - timedelta(days=5)).isoformat()
    payload = {
        "hits": 2,
        "total_hits": 2,
        "results": [
            _api_row("new", "Current FPS role", future),
            _api_row("old", "Stale FPS role", past),
        ],
    }
    monkeypatch.setattr(
        "sources.fps_andalucia.make_retry_session",
        lambda **kwargs: _Session(payload),
    )

    diag = {}
    rows = collect(diagnostics=diag)
    assert [r["id"] for r in rows] == ["junta-new"]
    assert diag["api_stale_filtered"] == 1
    assert diag["coverage_complete"] is True


def test_collect_fps_truthfully_flags_incomplete_api_response(monkeypatch):
    future = (date.today() + timedelta(days=5)).isoformat()
    payload = {
        "hits": 1,
        "total_hits": 2,
        "results": [_api_row("683584", "Técnico/a de Investigación 44-2026", future)],
    }
    monkeypatch.setattr(
        "sources.fps_andalucia.make_retry_session",
        lambda **kwargs: _Session(payload),
    )

    diag = {}
    rows = collect(diagnostics=diag)
    assert len(rows) == 1
    assert diag["coverage_complete"] is False
    assert "API response incomplete" in diag["coverage_warning"]
