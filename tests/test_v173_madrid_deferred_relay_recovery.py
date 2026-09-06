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


def test_worker_uses_one_upstream_attempt_per_invocation():
    worker = (ROOT / "cloudflare-madrid-relay" / "src" / "index.js").read_text(encoding="utf-8")
    assert "const UPSTREAM_TIMEOUT_MS = 6000;" in worker
    assert "const MAX_ATTEMPTS = 1;" in worker
    assert "RETRY_DELAY_MS" not in worker
    assert "for (let attempt" not in worker


def test_only_transient_relay_failures_are_recovery_candidates():
    assert madrid._is_retryable_relay_failure("POEM_RELAY_HTTP_504")
    assert madrid._is_retryable_relay_failure("POEM_RELAY_HTTP_503")
    assert madrid._is_retryable_relay_failure("POEM_RELAY_HTTP_522")
    assert madrid._is_retryable_relay_failure("POEM_RELAY_HTTP_429")
    assert madrid._is_retryable_relay_failure("POEM_RELAY_FETCH_FAILED: ReadTimeout: x")
    assert not madrid._is_retryable_relay_failure("POEM_RELAY_HTTP_401")
    assert not madrid._is_retryable_relay_failure("POEM_API_PARTIAL_DETAIL")


def test_transient_relay_failure_gets_one_delayed_recovery(monkeypatch):
    monkeypatch.setenv("MADRID_RELAY_URL", "https://relay.example.workers.dev")
    monkeypatch.setenv("MADRID_RELAY_TOKEN", "token")
    monkeypatch.setattr(madrid.time, "sleep", lambda _: None)

    calls = {0: 0, 1: 0, 2: 0}

    def resolved(index, row, timeout):
        row["poem_transport"] = "cloudflare_relay"
        calls[index] += 1
        if index == 0 and calls[index] == 1:
            return index, "", "POEM_RELAY_HTTP_504", "", "poem_api_failed"
        if index == 1:
            return index, "", "POEM_RELAY_HTTP_401", "", "poem_api_failed"
        return index, f"full detail {index}", "OK", f"https://api.example/{index}", "poem_api"

    monkeypatch.setattr(madrid, "_resolve_detail_row", resolved)
    rows = [{"id": str(i)} for i in range(3)]
    diag = _blank_diag()

    madrid._enrich_detail_rows(rows, diag, timeout=(1, 1), detail_workers=6)

    assert calls == {0: 2, 1: 1, 2: 1}
    assert diag["detail_workers"] == 3
    assert diag["relay_recovery_candidates"] == 1
    assert diag["relay_recovery_attempts"] == 1
    assert diag["relay_recovery_success"] == 1
    assert diag["relay_recovery_failed"] == 0
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 1
    assert rows[0]["relay_recovery_attempted"] is True


def test_persistent_504_stops_after_second_total_attempt(monkeypatch):
    monkeypatch.setenv("MADRID_RELAY_URL", "https://relay.example.workers.dev")
    monkeypatch.setenv("MADRID_RELAY_TOKEN", "token")
    monkeypatch.setattr(madrid.time, "sleep", lambda _: None)

    calls = {0: 0, 1: 0}

    def resolved(index, row, timeout):
        row["poem_transport"] = "cloudflare_relay"
        calls[index] += 1
        if index == 0:
            return index, "", "POEM_RELAY_HTTP_504", "", "poem_api_failed"
        return index, "full detail", "OK", "https://api.example/1", "poem_api"

    monkeypatch.setattr(madrid, "_resolve_detail_row", resolved)
    rows = [{"id": "0"}, {"id": "1"}]
    diag = _blank_diag()

    madrid._enrich_detail_rows(rows, diag, timeout=(1, 1), detail_workers=6)

    assert calls == {0: 2, 1: 1}
    assert diag["relay_recovery_attempts"] == 1
    assert diag["relay_recovery_success"] == 0
    assert diag["relay_recovery_failed"] == 1
    assert diag["detail_success"] == 1
    assert diag["detail_failed"] == 1


def test_v173_manifest():
    manifest = json.loads((ROOT / "PRODUCTION_VERSION.json").read_text(encoding="utf-8"))
    assert manifest["production_version"] == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"
    assert manifest["baseline"] == "V1.78_IDIBAPS_REPLACEMENT"
    assert manifest["scoring_engine"] == "V1.36_FINAL_SCORING_CLEANUP"
