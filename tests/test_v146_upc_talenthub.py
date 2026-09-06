from jobbot.availability import assess_availability
from jobbot.production import SOURCE_ORDER, selected_sources
from sources import upc_talenthub

BOARD_FIXTURE = '''
<html><body><main>
<h2>Open jobs</h2>
<div class="job"><p>RESOLUCIÓ 001_SP_UCT-2026-5592-286 Tècnic/a de Grau Superior de Suport a la Recerca</p>
<a href="/en/jobs/psr/psr-jobs-folder/power/tecnic-power">Tècnic/a en electrònica de potència. Codi 30269460010</a>
<span>Deadline: Sep 01, 2026</span></div>
<div class="job"><p>RESOLUCIÓ 001_SP_UCT-2026-3989-228 Investigador/a Postdoctoral</p>
<a href="/en/jobs/r3/r3-jobs/digital-twin/digital-twin">Investigador/a per desenvolupar mètodes Digital Twin. Codi 30269450001</a>
<span>Deadline: Sep 07, 2026</span></div>
<h2>Closed jobs</h2>
<div class="job"><a href="/en/jobs/r3/r3-jobs/old/old">Postdoc old vacancy. Codi 30260000001</a><span>Deadline: Jun 01, 2026</span></div>
</main></body></html>
'''

DETAIL_FIXTURE = '''
<html><body><main>
<h1>Tècnic/a en electrònica de potència. Codi 30269460010</h1>
<div>2026-07-31T00:00:00+02:00</div><div>2026-09-01T23:59:59+02:00</div>
<div>Where Barcelona Contact Name Example</div>
<a href="https://tauler.seu-e.cat/detall?idEdicte=1&idEns=12">Bases del concurs</a>
<a href="/en/jobs/psr/psr-jobs-folder/power/fitxa-30269460010.pdf">Perfil Professional</a>
<a href="/apply">Formulari d'inscripció</a>
</main></body></html>
'''


def test_upc_parser_keeps_open_jobs_and_excludes_closed_section():
    rows = upc_talenthub.parse_board_html(BOARD_FIXTURE, upc_talenthub.BOARD_URLS["R3"], "R3")
    assert len(rows) == 2
    assert all(r["portal_status"] == "OPEN" for r in rows)
    assert not any("old vacancy" in r["title"] for r in rows)
    assert rows[0]["date"] == "Sep 01, 2026"


def test_upc_psr_dedicated_open_page_allows_missing_heading_but_not_closed():
    html = '<html><body><div><a href="/en/jobs/psr/x/x">Role. Codi 30260000002</a><span>Deadline: Sep 05, 2026</span></div></body></html>'
    rows = upc_talenthub.parse_board_html(html, upc_talenthub.BOARD_URLS["PSR"], "PSR")
    assert len(rows) == 1


def test_upc_detail_parser_selects_professional_profile_not_generic_bases():
    meta = upc_talenthub.parse_detail_html(DETAIL_FIXTURE, "https://talenthub.upc.edu/en/jobs/psr/x")
    assert meta["deadline"] == "2026-09-01"
    assert meta["location"] == "Barcelona"
    assert len(meta["profile_urls"]) == 1
    assert meta["profile_urls"][0].endswith("fitxa-30269460010.pdf")


def test_upc_deadline_flows_through_existing_availability_logic():
    row = upc_talenthub.parse_board_html(BOARD_FIXTURE, upc_talenthub.BOARD_URLS["R3"], "R3")[0]
    result = assess_availability(row, "2026-08-29")
    assert result["application_status"] == "OPEN"
    assert result["application_deadline"] == "2026-09-01"


def test_upc_is_production_source():
    assert "upc" in SOURCE_ORDER
    assert selected_sources("upc") == ["upc"]
    assert "upc" in selected_sources("all")


def test_upc_collect_resolves_profile_document(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, *args, **kwargs):
            if url in upc_talenthub.BOARD_URLS.values():
                return Response(BOARD_FIXTURE, url)
            return Response(DETAIL_FIXTURE, url)
        def close(self):
            return None

    monkeypatch.setattr(upc_talenthub, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(
        upc_talenthub,
        "fetch_url_text",
        lambda url, **kwargs: ("Vacancy specific functions requirements experience qualifications " * 40, "OK_PDF"),
    )
    diag = {}
    jobs = upc_talenthub.collect(diagnostics=diag, max_jobs=20)
    # PSR accepts both open fixture jobs; R2/R3/R4 each see the two open-section links.
    # URL dedupe across boards leaves the same two canonical source records.
    assert len(jobs) == 2
    assert diag["boards_fetched"] == 4
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 0
    assert diag["profile_links_found"] == 2
    assert all(j["detail_status"] == "OK_PDF_ATTACHMENT" for j in jobs)
    assert all(j["trusted_full_detail_source"] == upc_talenthub.SOURCE_NAME for j in jobs)
