import json
from pathlib import Path

from sources import csic_sede


BOARD = """
<html><body><main>
<div class="view-row"><span>30/07/2026</span>
<a href="/tramites/convocatorias-de-personal/convocatoria/38221">Predoctoral Santiago Grisolía 2026 (Ref.38221)</a></div>
</main></body></html>
"""


def test_v175_csic_relay_keeps_official_canonical_urls(monkeypatch):
    monkeypatch.setenv("CSIC_RELAY_URL", "https://csic-relay.example.workers.dev")
    monkeypatch.setenv("CSIC_RELAY_TOKEN", "secret-token")

    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def __init__(self):
            self.headers = {}
            self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(url)
            return Response(BOARD, url)
        def close(self):
            return None

    session = Session()
    monkeypatch.setattr(csic_sede, "make_retry_session", lambda **kwargs: session)

    detail_calls = []
    def fake_fetch(url, **kwargs):
        detail_calls.append((url, kwargs))
        return ("Predoctoral Santiago Grisolía official CSIC vacancy description " * 30, "OK_HTML")
    monkeypatch.setattr(csic_sede, "fetch_url_text", fake_fetch)

    diag = {}
    jobs = csic_sede.collect(max_pages=1, diagnostics=diag)

    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://sede.csic.gob.es/tramites/convocatorias-de-personal/convocatoria/38221"
    assert session.calls == ["https://csic-relay.example.workers.dev/board?page=0"]
    assert session.headers["Authorization"] == "Bearer secret-token"
    assert detail_calls[0][0] == "https://csic-relay.example.workers.dev/convocatoria/38221"
    assert detail_calls[0][1]["follow_job_attachments"] is False
    assert diag["relay_configured"] is True
    assert diag["board_transport"] == "cloudflare_relay"
    assert diag["detail_transport_counts"] == {"cloudflare_relay": 1, "direct": 0}
    assert diag["detail_success"] == 1


def test_v175_incomplete_relay_configuration_fails_fast(monkeypatch):
    monkeypatch.setenv("CSIC_RELAY_URL", "https://csic-relay.example.workers.dev")
    monkeypatch.delenv("CSIC_RELAY_TOKEN", raising=False)

    diag = {}
    assert csic_sede.collect(max_pages=1, diagnostics=diag) == []
    assert diag["relay_configured"] is False
    assert diag["relay_configuration_incomplete"] is True
    assert "configuration incomplete" in diag["coverage_warning"].lower()


def test_v175_manifest_declares_v174_baseline():
    manifest = json.loads(Path("PRODUCTION_VERSION.json").read_text(encoding="utf-8"))
    assert manifest["production_version"] == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"
    assert manifest["baseline"] == "V1.78_IDIBAPS_REPLACEMENT"
