from types import SimpleNamespace

from jobbot import production
from sources import euraxess


def test_research_management_assistant_reaches_full_jd_gate():
    keep, reasons = euraxess._card_candidate({"title": "2026-0031 A RESEARCH MANAGEMENT ASSISTANT (M1) - LEVEL 1", "description": ""})
    assert keep is True
    assert "target_or_transferable_role_title" in reasons


def test_research_administration_family_reaches_full_jd_gate():
    keep, reasons = euraxess._card_candidate({"title": "Research Administration Officer", "description": ""})
    assert keep is True
    assert "target_or_transferable_role_title" in reasons


def test_euraxess_failed_feed_is_error_not_ok():
    diag = {"feed": {"mode": "failed", "coverage_complete": False, "coverage_warning": "feed failed"}}
    args = SimpleNamespace(history_days=None)
    assert production._coverage_complete("euraxess", diag, args) is False
    assert production._diagnostic_hard_error("euraxess", diag) == "feed failed"


def test_euraxess_page_error_or_truncation_is_partial_coverage():
    args = SimpleNamespace(history_days=None)
    page_error = {"feed": {"mode": "generic_feed_local_spain_filter", "coverage_complete": True, "page_errors": ["429"]}}
    truncated = {"feed": {"mode": "generic_feed_local_spain_filter", "coverage_complete": True, "page_errors": []}, "candidate_truncated": 2}
    assert production._coverage_complete("euraxess", page_error, args) is False
    assert production._diagnostic_hard_error("euraxess", page_error) == ""
    assert production._coverage_complete("euraxess", truncated, args) is False


def test_euraxess_healthy_empty_feed_is_not_failed(monkeypatch):
    euraxess._FEED_CACHE.clear()
    def fake_fetch_mode(base, pages, timeout, use_spain_facet, *, cutoff_date=None, request_delay=0.0):
        return [], {"base": base, "mode": "official_spain_facet" if use_spain_facet else "generic_feed_local_spain_filter", "pages_requested": pages, "pages_fetched": pages, "parsed_cards": 40, "unique_cards": 40, "spain_cards": 0, "spain_ratio": 0.0, "page_errors": [], "cutoff_date": None, "newest_seen_date": "2026-09-06", "oldest_seen_date": "2026-09-06", "dated_cards_seen": 40, "undated_cards_seen": 0, "stop_reason": "page_limit", "coverage_complete": True, "coverage_warning": ""}
    monkeypatch.setattr(euraxess, "_fetch_mode", fake_fetch_mode)
    cards, diag, cache_hit = euraxess._get_spain_feed(2, (1, 1))
    assert cards == []
    assert cache_hit is False
    assert diag["mode"] != "failed"
    assert diag["coverage_complete"] is True
    assert diag["page_errors"] == []


def test_v186_version_and_scoring_engine_unchanged():
    assert production.PRODUCTION_VERSION == "V1.86_EURAXESS_HEALTH_REPORTING_FIX"
    assert production.FROZEN_ENGINE == "V1.36_FINAL_SCORING_CLEANUP"
