import json
from pathlib import Path

from jobbot.availability import assess_availability
from jobbot.production import SOURCE_LABELS, SOURCE_ORDER, _collector_map, collect_sources, selected_sources
from sources import idibaps

BOARD_FIXTURE = '''
<html><body><main>
<div class="job-card">
  <a href="/uploads/media/default/0023/73/project-manager.pdf">[FRCB-IDIBAPS] Project Manager at the Child and Adolescent Psychiatry and Psychology group (Call FU-273/2026)</a>
  <div>Deadline 03/09/2026</div><div>State Open</div>
</div>
<div class="job-card">
  <a href="/uploads/media/default/0023/72/systems-neuro.pdf">[FRCB-IDIBAPS] R2A-Postdoctoral Researcher at the Systems Neuroscience group (Convocatòria FU-263/2026)</a>
  <div>Closing date 18/08/2026</div><div>State Closed</div>
  <a href="/uploads/media/default/0023/72/resolution.pdf">See first resolution</a>
</div>
</main></body></html>
'''

DETAIL_TEXT = '''
Project Manager at the Child and Adolescent Psychiatry and Psychology group.
Code: FU-273/2026
Job description: monitoring the work plan, coordination with internal and external stakeholders,
financial and administrative monitoring, budget planning and scientific-technical justification.
Required qualifications: University degree; PhD valued; Life sciences, preferably psychology.
Experience: EU project management valued; desirable at least 2 years of proven project-management experience.
Working mode: Hybrid.
Deadline: From publication until September 03, 2026.
'''


def test_v178_board_parser_extracts_official_status_deadline_and_pdf():
    jobs = idibaps.parse_board_html(BOARD_FIXTURE)
    assert len(jobs) == 2
    first = jobs[0]
    assert first["id"] == "FU-273/2026"
    assert first["company"] == "FRCB-IDIBAPS"
    assert first["location"] == "Barcelona, Spain"
    assert first["date"] == "03/09/2026"
    assert first["portal_status"] == "OPEN"
    assert first["source_application_status"] == "OPEN"
    assert first["url"].endswith("project-manager.pdf")


def test_v178_closed_listing_uses_source_status_without_resolution_link_pollution():
    jobs = idibaps.parse_board_html(BOARD_FIXTURE)
    closed = jobs[1]
    assert closed["id"] == "FU-263/2026"
    assert closed["portal_status"] == "CLOSED"
    assert closed["date"] == "18/08/2026"
    result = assess_availability(closed, "2026-08-30")
    assert result["application_status"] == "CLOSED"


def test_v178_collect_uses_official_pdf_as_trusted_full_detail(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, **kwargs):
            assert url == idibaps.BOARD_URL
            return Response(BOARD_FIXTURE, url)
        def close(self):
            return None

    monkeypatch.setattr(idibaps, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(idibaps, "fetch_url_text", lambda url, **kwargs: (DETAIL_TEXT * 8, "OK_PDF"))
    diag = {}
    jobs = idibaps.collect(diagnostics=diag)
    assert len(jobs) == 2
    assert diag["board_fetch"] == "OK"
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 0
    assert all(j["detail_status"] == "OK_PDF" for j in jobs)
    assert all(j.get("trusted_full_detail_source") == idibaps.SOURCE_NAME for j in jobs)


def test_v178_production_replaces_upf_with_idibaps_and_keeps_22_sources():
    assert len(SOURCE_ORDER) == 22
    assert "upf" not in SOURCE_ORDER
    assert SOURCE_ORDER.count("idibaps") == 1
    assert SOURCE_LABELS["idibaps"] == "FRCB-IDIBAPS Job Offers"
    assert _collector_map()["idibaps"] is idibaps.collect
    assert selected_sources("idibaps") == ["idibaps"]


def test_v178_total_board_failure_is_reported_as_source_error(tmp_path):
    class Args:
        source = "idibaps"
        history_days = None
        idibaps_max_jobs = 100

    def failed(*, diagnostics, **kwargs):
        diagnostics.update({
            "board_fetch": "FAILED",
            "coverage_complete": False,
            "coverage_warning": "IDIBAPS job board fetch/parse failed: HTTP 503",
            "detail_success": 0,
            "detail_failed": 0,
            "truncated": 0,
        })
        return []

    out = collect_sources(Args(), tmp_path, collector_overrides={"idibaps": failed})
    assert out["source_runs"]["idibaps"]["status"] == "ERROR"
    assert len(out["errors"]) == 1
    assert "IDIBAPS" in out["errors"][0]


def test_v178_manifest_and_cli_declare_replacement():
    manifest = json.loads(Path("PRODUCTION_VERSION.json").read_text(encoding="utf-8"))
    assert manifest["production_version"] == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"
    assert manifest["baseline"] == "V1.78_IDIBAPS_REPLACEMENT"
    assert "source count remains 22" in manifest["scope"]
    text = Path("run_live_sample.py").read_text(encoding="utf-8")
    assert 'p.add_argument("--idibaps-max-jobs", type=int, default=100)' in text
