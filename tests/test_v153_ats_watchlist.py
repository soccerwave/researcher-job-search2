from types import SimpleNamespace
from pathlib import Path

from jobbot.production import SOURCE_ORDER, selected_sources, verify_scoring_freeze
from sources import ats_watchlist


def test_v153_source_registered_and_scoring_still_frozen():
    assert "atswatch" in SOURCE_ORDER
    assert selected_sources("atswatch") == ["atswatch"]
    root = Path(__file__).resolve().parents[1]
    assert verify_scoring_freeze(root)["ok"] is True


def test_teamtailor_listing_parser_keeps_distinct_job_ids():
    html = '''
    <main>
      <a href="/en/jobs/8249179-research-culture-officer"><h3>Research Culture Officer</h3></a>
      <a href="/en/jobs/8278426-postdoctoral-researcher"><h3>Postdoctoral Researcher</h3></a>
    </main>'''
    employer = {"name":"VHIO", "default_location":"Barcelona, Spain"}
    rows = ats_watchlist.parse_teamtailor_listing(html, "https://jobs.vhio.net/en/jobs", employer)
    assert [r["id"] for r in rows] == ["8249179", "8278426"]
    assert rows[0]["title"] == "Research Culture Officer"
    assert rows[0]["source"] == ats_watchlist.SOURCE


def test_personio_xml_is_open_feed_and_supplies_full_jd():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
    <workzag-jobs>
      <position>
        <id>2733602</id>
        <office>BADALONA</office>
        <department>CEEISCAT</department>
        <name>2026_99_COORDINADOR/A DE PROJECTES DE RECERCA CEEISCAT</name>
        <jobDescriptions>
          <jobDescription><name>DESCRIPCIÓN</name><value><![CDATA[<p>Research project coordination and data analysis.</p>]]></value></jobDescription>
          <jobDescription><name>PLAZO</name><value><![CDATA[<p>El termini finalitzarà el dia 15 d’agost de 2026.</p>]]></value></jobDescription>
        </jobDescriptions>
        <employmentType>fixed-term</employmentType>
        <schedule>full-time</schedule>
      </position>
      <position>
        <id>111</id><name>RESOLUCIONES DE CONVOCATORIAS 2026</name><office>BADALONA</office>
      </position>
    </workzag-jobs>'''
    employer = {"name":"IGTP", "board_url":"https://igtp.jobs.personio.com/", "language":"en", "default_location":"Badalona, Spain"}
    rows = ats_watchlist.parse_personio_xml(xml, employer)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "2733602"
    assert "Research project coordination" in row["full_detail"]
    assert row["detail_status"] == "OK"
    assert row["source_application_status"] == "OPEN"
    assert row["url"] == "https://igtp.jobs.personio.com/job/2733602?language=en"


def test_watchlist_config_has_high_value_uncovered_employers():
    employers = ats_watchlist._load_watchlist()
    names = {e["name"] for e in employers}
    platforms = {e["platform"] for e in employers}
    assert "Vall d'Hebron Institute of Oncology (VHIO)" in names
    assert "Josep Carreras Leukaemia Research Institute" in names
    assert "Germans Trias i Pujol Research Institute (IGTP)" in names
    assert platforms == {"teamtailor", "personio"}
