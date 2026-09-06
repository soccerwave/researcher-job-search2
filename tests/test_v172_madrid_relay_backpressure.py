from __future__ import annotations

import json
from pathlib import Path

from sources import madrid_idi as madrid

ROOT = Path(__file__).resolve().parents[1]


def _blank_diag():
    return {
        "detail_attempts": 0,
        "external_detail_mismatches": 0,
        "poem_transport_counts": {},
        "poem_api_success": 0,
        "poem_api_partial": 0,
        "poem_api_failed": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_resolved_via_poem_api": 0,
        "detail_resolved_via_poem": 0,
        "detail_resolved_via_external_api_link": 0,
        "detail_resolved_via_external": 0,
    }


def test_relay_caps_detail_concurrency_to_three(monkeypatch):
    monkeypatch.setenv("MADRID_RELAY_URL", "https://relay.example.workers.dev")
    monkeypatch.setenv("MADRID_RELAY_TOKEN", "token")

    def resolved(index, row, timeout):
        row["poem_transport"] = "cloudflare_relay"
        return index, "full detail", "OK", "https://api.example/1", "poem_api"

    monkeypatch.setattr(madrid, "_resolve_detail_row", resolved)
    rows = [{"id": str(i)} for i in range(8)]
    diag = _blank_diag()

    madrid._enrich_detail_rows(rows, diag, timeout=(1, 1), detail_workers=6)

    assert diag["detail_workers_requested"] == 6
    assert diag["detail_workers"] == 3
    assert diag["relay_detail_worker_cap"] == 3
    assert diag["detail_success"] == 8


def test_direct_mode_keeps_requested_detail_concurrency(monkeypatch):
    monkeypatch.delenv("MADRID_RELAY_URL", raising=False)
    monkeypatch.delenv("MADRID_RELAY_TOKEN", raising=False)

    def resolved(index, row, timeout):
        row["poem_transport"] = "direct_api"
        return index, "full detail", "OK", "https://api.example/1", "poem_api"

    monkeypatch.setattr(madrid, "_resolve_detail_row", resolved)
    rows = [{"id": str(i)} for i in range(8)]
    diag = _blank_diag()

    madrid._enrich_detail_rows(rows, diag, timeout=(1, 1), detail_workers=6)

    assert diag["detail_workers_requested"] == 6
    assert diag["detail_workers"] == 6
    assert diag["relay_detail_worker_cap"] is None


def test_relay_keeps_bounded_timeout_and_attempt_telemetry():
    worker = (ROOT / "cloudflare-madrid-relay" / "src" / "index.js").read_text(encoding="utf-8")
    assert "const UPSTREAM_TIMEOUT_MS = 6000;" in worker
    assert "const MAX_ATTEMPTS = 1;" in worker
    assert "X-Madrid-Relay-Attempts" in worker


def test_v172_manifest():
    manifest = json.loads((ROOT / "PRODUCTION_VERSION.json").read_text(encoding="utf-8"))
    assert manifest["production_version"] == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"
    assert manifest["baseline"] == "V1.78_IDIBAPS_REPLACEMENT"
    assert manifest["scoring_engine"] == "V1.36_FINAL_SCORING_CLEANUP"
