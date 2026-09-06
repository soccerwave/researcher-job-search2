from argparse import Namespace
from pathlib import Path

from jobbot.availability import assess_availability
from jobbot.production import SOURCE_ORDER, selected_sources
from sources import gencat_research


FIXTURE = """
<html><body><main>
<ul>
  <li>
    <a href="https://ibecbarcelona.eu/laboratory-technician-at-the-nanobioengineering-research-group-6/">
      Laboratory Technician at the Nanobioengineering Research Group (IBEC)
    </a>
    <p>Periodo de vigencia: abierta hasta el 31 de agosto de 2026</p>
  </li>
  <li>
    <a href="https://jobs.icfo.eu/?detail=1077">
      Process Engineer or Research Scientist in PIC Packaging (ICFO)
    </a>
    <p>Periodo de vigencia: abierta hasta su cobertura</p>
  </li>
</ul>
<a href="/es/ayuda">Más información</a>
</main></body></html>
"""


def test_gencat_parser_extracts_official_links_deadlines_and_company():
    jobs = gencat_research.parse_board_html(FIXTURE)
    assert len(jobs) == 2
    first = jobs[0]
    assert first["company"] == "IBEC"
    assert first["date"] == "31 de agosto de 2026"
    assert first["url"].startswith("https://ibecbarcelona.eu/")
    assert "Fecha límite" in first["description"]

    second = jobs[1]
    assert second["company"] == "ICFO"
    assert second["date"] == ""
    assert "until the position is filled" in second["description"]


def test_gencat_listing_metadata_drives_existing_availability_logic():
    jobs = gencat_research.parse_board_html(FIXTURE)
    dated = assess_availability(jobs[0], "2026-08-28")
    assert dated["application_status"] == "OPEN"
    assert dated["application_deadline"] == "2026-08-31"
    rolling = assess_availability(jobs[1], "2026-08-28")
    assert rolling["application_status"] == "OPEN_UNTIL_FILLED"


def test_gencat_is_production_source_and_all_includes_it():
    assert "gencat" in SOURCE_ORDER
    assert "gencat" in selected_sources("all")
    assert selected_sources("gencat") == ["gencat"]


def test_gencat_collect_diagnostics_and_detail_enrichment(monkeypatch):
    class Response:
        text = FIXTURE
        url = gencat_research.BOARD_URL
        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()
        def close(self):
            return None

    monkeypatch.setattr(gencat_research, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(
        gencat_research,
        "fetch_url_text",
        lambda url, **kwargs: ("Full job description " * 80, "OK_HTML"),
    )
    diag = {}
    jobs = gencat_research.collect(diagnostics=diag)
    assert len(jobs) == 2
    assert diag["board_fetch"] == "OK"
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 0
    assert diag["truncated"] == 0
