from sources.madrid_idi import parse_listing_page


def test_parse_madrid_official_result_cards_and_poem_ids():
    html = '''
    <html><body>
      <div>Mostrando 1-10 de 1365 ofertas activas encontradas</div>
      <div class="view-content">
        <div class="views-row">
          <h3><a href="https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/64001">Scientific Project Manager</a></h3>
          <div class="empresa">Hospital Research Foundation</div>
          <p>Coordination of European research projects and consortium activities.</p>
          <div class="localidad">Madrid</div><div>26/08/2026</div>
        </div>
        <div class="views-row">
          <h3><a href="https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/64002">Postdoctoral Researcher</a></h3>
          <div class="empresa">University</div>
          <p>Specialist laboratory role.</p><div>Madrid</div><div>25/08/2026</div>
        </div>
      </div>
    </body></html>
    '''
    rows, diag = parse_listing_page(html)
    assert diag["total_active"] == 1365
    assert len(rows) == 2
    assert rows[0]["id"] == "64001"
    assert rows[0]["url"].endswith("/ver-oferta/64001")
    assert rows[0]["title"] == "Scientific Project Manager"
    assert "Madrid" in rows[0]["location"]
    assert rows[0]["full_detail"] if "full_detail" in rows[0] else True


def test_parse_madrid_does_not_treat_result_snippet_as_full_jd():
    html = '''
      <div>Mostrando 1-1 de 1 ofertas activas encontradas</div>
      <div class="views-row">
        <h3><a href="https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/65000">Research Coordinator</a></h3>
        <p>Short public search snippet only.</p><span>Madrid</span>
      </div>
    '''
    rows, _ = parse_listing_page(html)
    assert len(rows) == 1
    assert "full_detail" not in rows[0]
    assert rows[0]["description"] == "Research Coordinator Short public search snippet only. Madrid"


def test_parse_current_madrid_job_item_markup_with_empty_overlay_link():
    html = '''
    <html><body>
      <div class="view-header">Mostrando 1-2 de <strong>1365</strong> ofertas activas encontradas</div>
      <div class="view-content">
        <div class="job-item">
          <a href="https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/63661" class="job-link"></a>
          <h3 class="job-title">It project manager - research support 2026</h3>
          <p class="job-organization">FUNDACION IMDEA NETWORKS</p>
          <div class="job-location"><span>Madrid</span></div>
          <span class="job-time"><div>20/08/2026</div></span>
        </div>
        <div class="job-item">
          <a href="https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/63762" class="job-link"></a>
          <h3 class="job-title">Investigador/a</h3>
          <p class="job-organization">Hospital Research Foundation</p>
          <p class="job-description">Human macrophage laboratory work.</p>
          <div class="job-location"><span>Madrid</span></div>
          <span class="job-time"><div>20/08/2026</div></span>
        </div>
      </div>
    </body></html>
    '''
    rows, diag = parse_listing_page(html)
    assert diag["total_active"] == 1365
    assert diag["shown_start"] == 1
    assert diag["shown_end"] == 2
    assert diag["expected_cards"] == 2
    assert len(rows) == 2
    assert rows[0]["id"] == "63661"
    assert rows[0]["title"] == "It project manager - research support 2026"
    assert rows[0]["company"] == "FUNDACION IMDEA NETWORKS"
    assert rows[0]["location"] == "Madrid"
    assert rows[0]["date"] == "20/08/2026"


def test_parse_current_madrid_card_keeps_search_description_as_snippet_only():
    html = '''
      <div>Mostrando 1-1 de 1 ofertas activas encontradas</div>
      <div class="job-item">
        <a class="job-link" href="https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/63762"></a>
        <h3 class="job-title">Investigador/a</h3>
        <p class="job-organization">FIBHGM</p>
        <p class="job-description">Estudiar el efecto de fármacos inmunomoduladores.</p>
        <div class="job-location">Madrid</div>
        <span class="job-time">20/08/2026</span>
      </div>
    '''
    rows, _ = parse_listing_page(html)
    assert len(rows) == 1
    assert "full_detail" not in rows[0]
    assert "fármacos inmunomoduladores" in rows[0]["description"]


class _MadridFakeResponse:
    def __init__(self, text, url="https://www.comunidad.madrid/info/servicios/educacion/ciencia-e-investigacion/buscador-empleo-idi"):
        self.text = text
        self.url = url
        self.status_code = 200
    def raise_for_status(self):
        return None


class _MadridFakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
    def get(self, url, params=None, **kwargs):
        page = int((params or {}).get("page", 0))
        self.calls.append(page)
        return _MadridFakeResponse(self.pages[page], url)
    def close(self):
        pass


def test_collect_marks_parser_mismatch_incomplete_instead_of_silent_success(monkeypatch):
    import sources.madrid_idi as madrid
    html = '''
      <div>Mostrando 1-10 de 1365 ofertas activas encontradas</div>
      <div class="view-content"><div>This intentionally contains no parseable offer cards.</div></div>
    '''
    fake = _MadridFakeSession({0: html})
    monkeypatch.setattr(madrid, "make_retry_session", lambda **kwargs: fake)
    diag = {}
    jobs = madrid.collect(diagnostics=diag, max_pages=10, enrich_detail=False)
    assert jobs == []
    assert diag["total_active_reported"] == 1365
    assert diag["coverage_complete"] is False
    assert diag["first_page_parse_guard_triggered"] is True
    assert diag["card_count_mismatches"] == [{
        "page": 0, "expected": 10, "parsed": 0, "shown_start": 1, "shown_end": 10,
    }]
    assert "parser coverage mismatch" in diag["coverage_warning"]


def test_collect_accepts_current_job_item_page_when_expected_count_matches(monkeypatch):
    import sources.madrid_idi as madrid
    html = '''
      <div>Mostrando 1-2 de 2 ofertas activas encontradas</div>
      <div class="view-content">
        <div class="job-item"><a class="job-link" href="https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/1"></a><h3 class="job-title">Project Manager</h3><p class="job-organization">Research Institute</p><div class="job-location">Madrid</div><span class="job-time">20/08/2026</span></div>
        <div class="job-item"><a class="job-link" href="https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/2"></a><h3 class="job-title">Quantum Engineer</h3><p class="job-organization">Physics Institute</p><div class="job-location">Madrid</div><span class="job-time">20/08/2026</span></div>
      </div>
    '''
    # The next page is a natural empty page with no visible-result header.
    fake = _MadridFakeSession({0: html, 1: "<html><body>No more results</body></html>"})
    monkeypatch.setattr(madrid, "make_retry_session", lambda **kwargs: fake)
    diag = {}
    jobs = madrid.collect(diagnostics=diag, max_pages=2, enrich_detail=False)
    assert [j["id"] for j in jobs] == ["1", "2"]
    assert diag["coverage_complete"] is True
    assert diag["parsed_cards"] == 2
    assert diag["unique_cards"] == 2
    assert diag["page_card_counts"] == [2, 0]
