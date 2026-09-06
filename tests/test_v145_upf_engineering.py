from jobbot.availability import assess_availability
from sources import upf_engineering

BOARD_FIXTURE = '''
<html><body><main>
<div class="asset-card">
  <a href="/en/web/enginyeria/convocatories-pdi/-/asset_publisher/8Ms83m4xhP9x/content/postdoc-cancer/maximized">
    Postdoctoral position – Physics-informed deep learning for cancer imaging, diagnosis and treatment (ERC Synergy project Zee-Zoom-Zap) - 2026-8
  </a>
  <p>Call: ENG-INV.INDF-2026-8</p>
  <p>Application deadline: 04/09/2026</p>
  <p>Status: OPEN</p>
</div>
<div class="asset-card">
  <a href="/en/web/enginyeria/convocatories-pdi/-/asset_publisher/8Ms83m4xhP9x/content/santander/maximized">
    Programa de Beques Santander - UPF per a investigadors predoctorals 2026
  </a>
  <p>Call: Beques Santander</p>
  <p>Application deadline: 01/10/2026</p>
  <p>Status: OPEN</p>
</div>
</main></body></html>
'''

DETAIL_FIXTURE = '''
<html><body><main>
<h1>Postdoctoral position – Physics-informed deep learning for cancer imaging, diagnosis and treatment</h1>
<ul>
<li>Call: ENG-INV.INDF-2026-8</li>
<li>Application deadline: 04/09/2026</li>
<li>Status: OPEN</li>
</ul>
<a href="/documents/10193/9999/Bases_ENG-INV-INDF-2026-8.pdf">Bases de la convocatòria</a>
<a href="/documents/10193/9999/admesos.pdf">Llista provisional d'admesos i exclosos</a>
</main></body></html>
'''


def test_upf_board_parser_extracts_official_offer_metadata():
    jobs = upf_engineering.parse_board_html(BOARD_FIXTURE)
    assert len(jobs) == 2
    first = jobs[0]
    assert first["company"] == "Universitat Pompeu Fabra (UPF)"
    assert first["location"] == "Barcelona, Spain"
    assert first["date"] == "04/09/2026"
    assert first["id"] == "ENG-INV.INDF-2026-8"
    assert first["portal_status"] == "OPEN"
    assert "/web/enginyeria/convocatories-pdi/-/asset_publisher/" in first["url"]


def test_upf_deadline_metadata_uses_existing_availability_logic():
    job = upf_engineering.parse_board_html(BOARD_FIXTURE)[0]
    result = assess_availability(job, "2026-08-28")
    assert result["application_status"] == "OPEN"
    assert result["application_deadline"] == "2026-09-04"


def test_upf_detail_parser_prefers_bases_and_ignores_later_process_docs():
    meta = upf_engineering.parse_detail_html(DETAIL_FIXTURE, "https://www.upf.edu/en/web/enginyeria/convocatories-pdi/x")
    assert meta["deadline"] == "04/09/2026"
    assert meta["call_reference"] == "ENG-INV.INDF-2026-8"
    assert len(meta["bases_urls"]) == 1
    assert meta["bases_urls"][0].endswith("Bases_ENG-INV-INDF-2026-8.pdf")



def test_upf_collect_resolves_official_bases(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, *args, **kwargs):
            if url == upf_engineering.BOARD_URL:
                return Response(BOARD_FIXTURE, upf_engineering.BOARD_URL)
            return Response(DETAIL_FIXTURE, url)
        def close(self):
            return None

    monkeypatch.setattr(upf_engineering, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(
        upf_engineering,
        "fetch_url_text",
        lambda url, **kwargs: ("Official vacancy bases with duties requirements qualifications " * 40, "OK_PDF"),
    )
    diag = {}
    jobs = upf_engineering.collect(diagnostics=diag)
    assert len(jobs) == 2
    assert diag["board_fetch"] == "OK"
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 0
    assert diag["bases_links_found"] == 2
    assert all(j["detail_status"] == "OK_PDF_ATTACHMENT" for j in jobs)
    assert all(j.get("trusted_full_detail_source") == upf_engineering.SOURCE_NAME for j in jobs)
