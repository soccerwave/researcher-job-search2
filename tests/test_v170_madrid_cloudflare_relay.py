from __future__ import annotations

import json
from pathlib import Path

from sources import madrid_idi

ROOT = Path(__file__).resolve().parents[1]


class DummyResponse:
    status_code = 200

    def json(self):
        return {
            "result": {"status": True, "http_code": 201},
            "data": {"idOferta": 63740, "dsPuesto": "Research role", "dsFuncion": "A" * 100},
        }


class CaptureSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return DummyResponse()


def test_madrid_uses_authenticated_relay_when_configured(monkeypatch):
    monkeypatch.setenv("MADRID_RELAY_URL", "https://madrid-api-probe.example.workers.dev/")
    monkeypatch.setenv("MADRID_RELAY_TOKEN", "shared-test-token")
    session = CaptureSession()
    relay_calls = []

    def relay_get(url, **kwargs):
        relay_calls.append((url, kwargs))
        return DummyResponse()

    monkeypatch.setattr(madrid_idi.requests, "get", relay_get)
    job = {"id": "63740"}

    data, status = madrid_idi._fetch_poem_api(job, session, timeout=(10, 45))

    assert status == "POEM_API_OK"
    assert data["idOferta"] == 63740
    assert job["poem_transport"] == "cloudflare_relay"
    assert session.calls == []  # relay bypasses urllib3 5xx retry adapter
    assert relay_calls[0][0] == "https://madrid-api-probe.example.workers.dev/offer/63740"
    assert relay_calls[0][1]["headers"]["Authorization"] == "Bearer shared-test-token"
    assert relay_calls[0][1]["timeout"] == (5, 15)


def test_madrid_does_not_fall_back_directly_when_relay_config_is_partial(monkeypatch):
    monkeypatch.setenv("MADRID_RELAY_URL", "https://madrid-api-probe.example.workers.dev")
    monkeypatch.delenv("MADRID_RELAY_TOKEN", raising=False)
    session = CaptureSession()
    job = {"id": "63740"}

    data, status = madrid_idi._fetch_poem_api(job, session, timeout=(10, 45))

    assert data == {}
    assert status == "POEM_RELAY_CONFIG_INVALID"
    assert job["poem_transport"] == "relay_config_invalid"
    assert session.calls == []


def test_madrid_local_path_remains_direct_without_relay(monkeypatch):
    monkeypatch.delenv("MADRID_RELAY_URL", raising=False)
    monkeypatch.delenv("MADRID_RELAY_TOKEN", raising=False)
    session = CaptureSession()
    job = {"id": "63740"}

    data, status = madrid_idi._fetch_poem_api(job, session, timeout=(3, 7))

    assert status == "POEM_API_OK"
    assert job["poem_transport"] == "direct_api"
    assert session.calls[0][0].startswith(madrid_idi.POEM_OFFERS_API)
    assert session.calls[0][1]["timeout"] == (3, 7)


def test_madrid_relay_worker_is_fixed_purpose_and_authenticated():
    worker = (ROOT / "cloudflare-madrid-relay" / "src" / "index.js").read_text(encoding="utf-8")
    assert 'url.pathname.match(/^\\/offer\\/(\\d{1,10})$/)' in worker
    assert "MADRID_RELAY_TOKEN" in worker
    assert "Authorization" in worker
    assert "apiscm.comunidad.madrid" in worker
    assert "url.searchParams.get(\"url\")" not in worker


def test_cloud_workflows_supply_madrid_relay_settings():
    for rel in (
        ".github/workflows/production-job-search.yml",
        ".github/workflows/source-diagnostic.yml",
        ".github/workflows/all-source-diagnostic.yml",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "MADRID_RELAY_URL: ${{ vars.MADRID_RELAY_URL }}" in text
        assert "MADRID_RELAY_TOKEN: ${{ secrets.MADRID_RELAY_TOKEN }}" in text

    production = (ROOT / ".github/workflows/production-job-search.yml").read_text(encoding="utf-8")
    assert "Verify Madrid relay" in production
    assert 'curl -fsS --max-time 10 "${MADRID_RELAY_URL%/}/health"' in production


def test_v170_production_version_manifest():
    manifest = json.loads((ROOT / "PRODUCTION_VERSION.json").read_text(encoding="utf-8"))
    assert manifest["production_version"] == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"
    assert manifest["scoring_engine"] == "V1.36_FINAL_SCORING_CLEANUP"
