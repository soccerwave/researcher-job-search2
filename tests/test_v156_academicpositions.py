from pathlib import Path
from types import SimpleNamespace

from jobbot.production import SOURCE_ORDER, _collector_map, verify_scoring_freeze
from sources import academicpositions


LIST_EN = '''
<html><body><h1>2 jobs in Spain</h1>
<a href="/ad/rmit-europe/2026/auspire/250222">Australia-Spain Network for Innovation and Research Excellence – AuSpire</a>
<a href="/ad/example-university/2026/research-project-manager/250333">Research Project Manager</a>
</body></html>
'''

LIST_ES = '''
<html><body><h1>3 trabajos en España</h1>
<a href="/ad/rmit-europe/2026/auspire/250222">Australia-Spain Network for Innovation and Research Excellence – AuSpire</a>
<a href="/ad/example-university/2026/research-project-manager/250333">Research Project Manager</a>
<a href="/ad/health-institute/2026/clinical-research-coordinator/250444">Clinical Research Coordinator</a>
</body></html>
'''


def detail_html(title, employer, city, job_id, date="2026-08-20", deadline="2026-09-30"):
    return f'''<html><head><script type="application/ld+json">{{
      "@context":"https://schema.org", "@type":"JobPosting",
      "title": {title!r},
      "datePosted":"{date}", "validThrough":"{deadline}T23:59:00+02:00",
      "hiringOrganization":{{"@type":"Organization","name":{employer!r}}},
      "jobLocation":{{"@type":"Place","address":{{"@type":"PostalAddress","addressLocality":{city!r},"addressCountry":"Spain"}}}},
      "description":"<p>We are recruiting for this research role. Duties include project coordination, human research studies, grant reporting, data quality, stakeholder collaboration and scientific communication. Candidates should hold a PhD or related advanced degree and have relevant research experience.</p>"
    }}</script></head><body><main><h1>{title}</h1><p>Application deadline: {deadline}</p></main></body></html>'''.replace("'", '"')


class FakeResponse:
    def __init__(self, text, url, status_code=200):
        self.text = text
        self.url = url
        self.status_code = status_code
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def get(self, url, **kwargs):
        if url == "https://academicpositions.com/jobs/country/spain":
            return FakeResponse(LIST_EN, url)
        if url == "https://academicpositions.es/jobs/country/spain":
            return FakeResponse(LIST_ES, url)
        job_id = academicpositions._ad_id_from_url(url)
        if job_id == "250222":
            return FakeResponse(detail_html("AuSpire Postdoctoral Fellowship", "RMIT Europe", "Barcelona", job_id), url)
        if job_id == "250333":
            return FakeResponse(detail_html("Research Project Manager", "Example University", "Madrid", job_id), url)
        if job_id == "250444":
            return FakeResponse(detail_html("Clinical Research Coordinator", "Health Institute", "Barcelona", job_id), url)
        raise AssertionError(url)
    def close(self):
        pass


def test_listing_parser_uses_stable_ad_ids_and_declared_count():
    rows, declared = academicpositions.parse_listing(LIST_EN, "https://academicpositions.com/jobs/country/spain")
    assert declared == 2
    assert [r["id"] for r in rows] == ["250222", "250333"]
    assert rows[1]["title"] == "Research Project Manager"


def test_detail_parser_prefers_jobposting_jsonld_and_keeps_deadline():
    html = detail_html("Research Project Manager", "Example University", "Madrid", "250333")
    meta, status = academicpositions.parse_detail(html, "https://academicpositions.com/ad/x/2026/y/250333")
    assert status == "OK_HTML"
    assert meta["title"] == "Research Project Manager"
    assert meta["company"] == "Example University"
    assert meta["location"] == "Madrid, Spain"
    assert meta["date"] == "2026-08-20"
    assert meta["deadline"] == "2026-09-30"
    assert "project coordination" in meta["full_detail"].lower()


def test_bilingual_boards_dedupe_by_academicpositions_job_id():
    diag = {}
    rows = academicpositions.collect(diagnostics=diag, session=FakeSession())
    assert len(rows) == 3
    assert {r["id"] for r in rows} == {"250222", "250333", "250444"}
    assert diag["boards_fetched"] == 2
    assert diag["board_declared_counts"] == {"international_en": 2, "spain_es": 3}
    assert diag["unique_jobs"] == 3
    assert diag["detail_success"] == 3
    assert diag["detail_failed"] == 0
    assert diag["coverage_complete"] is True
    shared = next(r for r in rows if r["id"] == "250222")
    assert "international_en" in shared["boards_seen"] and "spain_es" in shared["boards_seen"]


def test_cloudflare_challenge_is_not_scored_as_full_jd():
    meta, status = academicpositions.parse_detail(
        "<html><title>Just a moment...</title><body>Checking your browser cf-chl-foo</body></html>",
        "https://academicpositions.com/ad/x/2026/y/123",
    )
    assert meta == {}
    assert status == "ACADEMICPOSITIONS_ACCESS_BLOCKED"


def test_v156_source_is_registered_and_scoring_freeze_passes():
    assert "academicpositions" in SOURCE_ORDER
    assert _collector_map()["academicpositions"] is academicpositions.collect
    root = Path(__file__).resolve().parents[1]
    assert verify_scoring_freeze(root)["ok"] is True


class OptionalMirrorFailureSession(FakeSession):
    def get(self, url, **kwargs):
        if url == "https://academicpositions.es/jobs/country/spain":
            raise RuntimeError("HTTP 403")
        return super().get(url, **kwargs)


def test_v195_optional_spanish_mirror_failure_does_not_downgrade_complete_primary_board():
    diag = {}
    rows = academicpositions.collect(diagnostics=diag, session=OptionalMirrorFailureSession())
    assert len(rows) == 2
    assert diag["required_boards_requested"] == 1
    assert diag["required_boards_fetched"] == 1
    assert diag["board_errors"] == []
    assert len(diag["optional_board_errors"]) == 1
    assert diag["board_declared_counts"]["international_en"] == 2
    assert diag["board_parsed_job_counts"]["international_en"] == 2
    assert diag["coverage_complete"] is True
    assert diag["coverage_warning"] == ""


class PrimaryFailureMirrorHealthySession(FakeSession):
    def get(self, url, **kwargs):
        if url == "https://academicpositions.com/jobs/country/spain":
            raise RuntimeError("HTTP 503")
        return super().get(url, **kwargs)


def test_v195_primary_board_failure_remains_incomplete_even_if_optional_mirror_works():
    diag = {}
    rows = academicpositions.collect(diagnostics=diag, session=PrimaryFailureMirrorHealthySession())
    assert len(rows) == 3
    assert diag["required_boards_fetched"] == 0
    assert len(diag["board_errors"]) == 1
    assert diag["coverage_complete"] is False
    assert "authoritative Spain country board failed" in diag["coverage_warning"]
