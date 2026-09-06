import json
from pathlib import Path
import sources.euraxess as euraxess


def _card(title, url):
    return {
        "source": "EURAXESS",
        "title": title,
        "company": "Example Institute",
        "location": "Spain",
        "date": "10 August 2026",
        "url": url,
        "description": "Research position in Spain",
    }


def test_historical_detail_rate_limit_stops_and_defers_remaining(monkeypatch, tmp_path):
    cards = [
        _card("Postdoctoral Researcher A", "https://euraxess.ec.europa.eu/jobs/1"),
        _card("Postdoctoral Researcher B", "https://euraxess.ec.europa.eu/jobs/2"),
        _card("Postdoctoral Researcher C", "https://euraxess.ec.europa.eu/jobs/3"),
    ]
    feed_diag = {"coverage_complete": True, "attempts": [{"pages_fetched": 1, "parsed_cards": 3}]}
    monkeypatch.setattr(euraxess, "_get_spain_feed", lambda **kwargs: (cards, feed_diag, False))
    monkeypatch.setattr(euraxess, "_is_spain", lambda job: True)
    monkeypatch.setattr(euraxess, "DETAIL_CACHE_PATH", tmp_path / "details.json")
    euraxess._DETAIL_CACHE.clear()

    calls = []
    def fake_fetch(url, **kwargs):
        calls.append(url)
        if url.endswith("/1"):
            return "Job Information Country Spain Offer Description valid", "OK_HTML"
        return "", "FETCH_FAILED: 429 Client Error: Too Many Requests"
    monkeypatch.setattr(euraxess, "fetch_url_text", fake_fetch)

    diag = {}
    jobs = euraxess.collect(
        history_days=60, as_of="2026-08-27", diagnostics=diag,
        detail_request_delay=0.0,
    )

    assert len(jobs) == 3
    assert diag["detail_success"] == 1
    assert diag["detail_failed"] == 2
    assert diag["detail_rate_limited"] is True
    assert diag["detail_deferred"] == 1
    assert diag["detail_network_requests"] == 2
    assert jobs[2]["detail_status"] == "DEFERRED_RATE_LIMIT"
    saved = json.loads((tmp_path / "details.json").read_text(encoding="utf-8"))
    assert "https://euraxess.ec.europa.eu/jobs/1" in saved


def test_persistent_detail_cache_is_reused_on_next_run(monkeypatch, tmp_path):
    cards = [
        _card("Postdoctoral Researcher A", "https://euraxess.ec.europa.eu/jobs/1"),
        _card("Postdoctoral Researcher B", "https://euraxess.ec.europa.eu/jobs/2"),
    ]
    feed_diag = {"coverage_complete": True, "attempts": [{"pages_fetched": 1, "parsed_cards": 2}]}
    monkeypatch.setattr(euraxess, "_get_spain_feed", lambda **kwargs: (cards, feed_diag, True))
    monkeypatch.setattr(euraxess, "_is_spain", lambda job: True)
    cache_path = tmp_path / "details.json"
    cache_path.write_text(json.dumps({
        "https://euraxess.ec.europa.eu/jobs/1": {
            "detail": "Job Information Country Spain Offer Description cached",
            "status": "OK_HTML",
        }
    }), encoding="utf-8")
    monkeypatch.setattr(euraxess, "DETAIL_CACHE_PATH", cache_path)
    euraxess._DETAIL_CACHE.clear()

    calls = []
    def fake_fetch(url, **kwargs):
        calls.append(url)
        return "Job Information Country Spain Offer Description fresh", "OK_HTML"
    monkeypatch.setattr(euraxess, "fetch_url_text", fake_fetch)

    diag = {}
    jobs = euraxess.collect(
        history_days=60, as_of="2026-08-27", diagnostics=diag,
        detail_request_delay=0.0,
    )

    assert len(jobs) == 2
    assert diag["detail_persistent_cache_hits"] == 1
    assert diag["detail_network_requests"] == 1
    assert diag["detail_success"] == 2
    assert diag["detail_resolution_complete"] is True
    assert calls == ["https://euraxess.ec.europa.eu/jobs/2"]
