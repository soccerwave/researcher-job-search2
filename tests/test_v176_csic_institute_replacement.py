import json
from pathlib import Path

from jobbot.production import SOURCE_LABELS, SOURCE_ORDER, _collector_map, collect_sources
from sources import csic_institutes


ICM = '''
<html><body><main>
<article><time datetime="2026-09-01">1 September 2026</time>
<a href="/es/oferta-trabajo/research-project-manager">Research Project Manager</a></article>
</main></body></html>
'''

IQAC = '''
<html><body><main><section>
<span>01/09/2026</span>
<a href="/en/join-iqac/postdoctoral-researcher-neurochemistry/">Postdoctoral researcher in neurochemistry</a>
<p>Deadline: September 30</p>
</section></main></body></html>
'''

IMB = '''
<html><body><main>
<h2>Ofertas de trabajo</h2>
<div><a href="/sites/default/files/job-open.pdf">Project Manager - National Strategic Initiatives</a></div>
<h2>Plazas para TFG/TFM</h2>
<a href="/sites/default/files/student.pdf">Student project</a>
<h2>Procesos de Selección finalizados o en proceso de evaluación</h2>
<a href="/sites/default/files/closed.pdf">Closed role</a>
</main></body></html>
'''


def test_v176_parsers_keep_only_official_current_job_sections():
    icm = csic_institutes.parse_icm_board_html(ICM)
    iqac = csic_institutes.parse_iqac_board_html(IQAC)
    imb = csic_institutes.parse_imb_cnm_board_html(IMB)
    assert [j["title"] for j in icm] == ["Research Project Manager"]
    assert icm[0]["company"] == "ICM-CSIC"
    assert icm[0]["date"] == "2026-09-01"
    assert [j["title"] for j in iqac] == ["Postdoctoral researcher in neurochemistry"]
    assert iqac[0]["company"] == "IQAC-CSIC"
    assert [j["title"] for j in imb] == ["Project Manager - National Strategic Initiatives"]
    assert imb[0]["company"] == "IMB-CNM-CSIC"
    assert "student" not in imb[0]["title"].lower()


def test_v176_collection_is_fail_soft_across_three_institute_boards(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
            self.headers = {"content-type": "text/html"}
            self.content = text.encode()
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, **kwargs):
            if "iqac" in url:
                raise RuntimeError("temporary IQAC outage")
            if "icm.csic" in url:
                return Response(ICM, url)
            return Response(IMB, url)
        def close(self):
            return None

    monkeypatch.setattr(csic_institutes, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(csic_institutes, "fetch_url_text", lambda *a, **k: ("Validated official job description " * 40, "OK_HTML"))

    diag = {}
    jobs = csic_institutes.collect(diagnostics=diag)
    assert len(jobs) == 2
    assert diag["boards_requested"] == 3
    assert diag["boards_fetched"] == 2
    assert len(diag["board_errors"]) == 1
    assert diag["coverage_complete"] is False
    assert diag["detail_success"] == 2
    assert "1 of 3" in diag["coverage_warning"]


def test_v176_zero_jobs_on_a_successfully_fetched_board_is_not_an_error(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None
    class Session:
        def get(self, url, **kwargs):
            if "icm.csic" in url:
                return Response("<html><main><p>No results.</p></main></html>", url)
            if "iqac" in url:
                return Response(IQAC, url)
            return Response(IMB, url)
        def close(self):
            return None

    monkeypatch.setattr(csic_institutes, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(csic_institutes, "fetch_url_text", lambda *a, **k: ("Validated official job description " * 40, "OK_HTML"))
    diag = {}
    jobs = csic_institutes.collect(diagnostics=diag)
    assert len(jobs) == 2
    assert diag["boards_fetched"] == 3
    assert diag["board_job_counts"]["icm"] == 0
    assert diag["board_errors"] == []
    assert diag["coverage_complete"] is True


def test_v176_production_key_keeps_22_source_architecture_and_uses_new_collector():
    assert SOURCE_LABELS["csic"] == "CSIC Barcelona Institutes"
    assert len(SOURCE_ORDER) == 22
    assert SOURCE_ORDER.count("csic") == 1
    assert _collector_map()["csic"] is csic_institutes.collect


def test_v176_diagnostics_no_longer_require_csic_relay_secrets():
    for rel in [".github/workflows/source-diagnostic.yml", ".github/workflows/all-source-diagnostic.yml", ".github/workflows/production-job-search.yml"]:
        text = Path(rel).read_text(encoding="utf-8")
        assert "CSIC_RELAY_URL" not in text
        assert "CSIC_RELAY_TOKEN" not in text
        assert "Verify CSIC relay" not in text


def test_v176_validation_record_preserves_csic_replacement_scope():
    validation = json.loads(Path("docs/validation/VALIDATION_V176.json").read_text(encoding="utf-8"))
    assert validation["production_version"] == "V1.76_CSIC_INSTITUTE_REPLACEMENT"
    assert validation["baseline"] == "V1.75_CSIC_CLOUDFLARE_RELAY"
    assert validation["replacement_scope"]["whole_csic_coverage_claimed"] is False


def test_v176_orchestration_marks_partial_vs_total_failure_correctly(tmp_path):
    class Args:
        source = "csic"
        history_days = None
        csic_max_jobs = 100
    def partial(*, diagnostics, **kwargs):
        diagnostics.update({
            "coverage_complete": False, "boards_fetched": 2,
            "board_errors": [{"institute": "iqac", "error": "offline"}],
            "coverage_warning": "CSIC institute coverage incomplete: 1 of 3 official institute board(s) failed",
            "detail_success": 0, "detail_failed": 0, "truncated": 0,
        })
        return []
    out = collect_sources(Args(), tmp_path, collector_overrides={"csic": partial})
    assert out["source_runs"]["csic"]["status"] == "PARTIAL"
    assert out["errors"] == []

    def total(*, diagnostics, **kwargs):
        diagnostics.update({
            "coverage_complete": False, "boards_fetched": 0,
            "board_errors": [{"institute": "icm", "error": "offline"}],
            "coverage_warning": "CSIC institute coverage incomplete: 3 of 3 official institute board(s) failed",
            "detail_success": 0, "detail_failed": 0, "truncated": 0,
        })
        return []
    out = collect_sources(Args(), tmp_path, collector_overrides={"csic": total})
    assert out["source_runs"]["csic"]["status"] == "ERROR"
    assert len(out["errors"]) == 1
