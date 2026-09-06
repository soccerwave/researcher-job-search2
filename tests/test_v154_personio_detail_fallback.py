from pathlib import Path
from types import SimpleNamespace

from jobbot.production import verify_scoring_freeze
from sources import ats_watchlist


class FakeResponse:
    def __init__(self, text, url="https://igtp.jobs.personio.com/xml?language=en"):
        self.text = text
        self.url = url
    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, xml):
        self.xml = xml
    def get(self, url, **kwargs):
        assert "/xml?language=en" in url
        return FakeResponse(self.xml, url)
    def close(self):
        pass


def _xml_one_empty_one_full():
    return '''<?xml version="1.0" encoding="UTF-8"?>
    <workzag-jobs>
      <position>
        <id>100</id><office>BADALONA</office><department>Research</department>
        <name>Research Project Coordinator</name>
        <jobDescriptions></jobDescriptions>
      </position>
      <position>
        <id>200</id><office>BADALONA</office><department>Research</department>
        <name>Postdoctoral Researcher</name>
        <jobDescriptions>
          <jobDescription><name>JOB DESCRIPTION</name><value><![CDATA[<p>Complete XML detail.</p>]]></value></jobDescription>
        </jobDescriptions>
      </position>
    </workzag-jobs>'''


def test_personio_empty_xml_detail_falls_back_to_public_job_page(monkeypatch, tmp_path):
    cfg = tmp_path / "ats.json"
    cfg.write_text('''{"employers":[{"name":"IGTP","platform":"personio","board_url":"https://igtp.jobs.personio.com/","language":"en","default_location":"Badalona, Spain"}]}''')
    monkeypatch.setattr(ats_watchlist, "make_retry_session", lambda **kwargs: FakeSession(_xml_one_empty_one_full()))

    calls = []
    def fake_fetch(url, **kwargs):
        calls.append(url)
        return ("Full public Personio job page with duties and application deadline: August 31, 2026.", "OK_HTML")
    monkeypatch.setattr(ats_watchlist, "fetch_url_text", fake_fetch)

    diag = {}
    rows = ats_watchlist.collect(diagnostics=diag, config_path=cfg)
    by_id = {r["id"]: r for r in rows}

    assert len(rows) == 2
    assert calls == ["https://igtp.jobs.personio.com/job/100?language=en"]
    assert by_id["100"]["detail_status"] == "OK_HTML"
    assert "Full public Personio job page" in by_id["100"]["full_detail"]
    assert by_id["200"]["detail_status"] == "OK"
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 0
    emp = diag["employers"]["IGTP"]
    assert emp["xml_detail_success"] == 1
    assert emp["detail_page_fallback_attempts"] == 1
    assert emp["detail_page_fallback_success"] == 1
    assert emp["detail_page_fallback_failed"] == 0


def test_personio_failed_fallback_remains_quarantined(monkeypatch, tmp_path):
    cfg = tmp_path / "ats.json"
    cfg.write_text('''{"employers":[{"name":"IGTP","platform":"personio","board_url":"https://igtp.jobs.personio.com/","language":"en","default_location":"Badalona, Spain"}]}''')
    xml = '''<workzag-jobs><position><id>100</id><office>BADALONA</office><name>Research Role</name><jobDescriptions/></position></workzag-jobs>'''
    monkeypatch.setattr(ats_watchlist, "make_retry_session", lambda **kwargs: FakeSession(xml))
    monkeypatch.setattr(ats_watchlist, "fetch_url_text", lambda *a, **k: ("", "HTTP_404"))

    diag = {}
    rows = ats_watchlist.collect(diagnostics=diag, config_path=cfg)
    assert rows[0]["full_detail"] == ""
    assert rows[0]["detail_status"] == "HTTP_404"
    assert diag["detail_success"] == 0
    assert diag["detail_failed"] == 1
    assert diag["employers"]["IGTP"]["detail_page_fallback_failed"] == 1


def test_v154_scoring_freeze_still_passes():
    root = Path(__file__).resolve().parents[1]
    assert verify_scoring_freeze(root)["ok"] is True
