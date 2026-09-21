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


def test_v193_repeated_result_page_marks_coverage_incomplete(monkeypatch):
    euraxess._FEED_CACHE.clear()

    class Response:
        def __init__(self, html):
            self.text = html
        def raise_for_status(self):
            return None

    page = """
    <div><a href="/jobs/123456">Research Project Manager</a>
    JOB Spain Example University Posted on: 20 September 2026 Work Locations: Spain</div>
    """

    class Session:
        def get(self, *args, **kwargs):
            return Response(page)
        def close(self):
            pass

    monkeypatch.setattr(euraxess, "make_retry_session", lambda **kwargs: Session())
    cards, diag = euraxess._fetch_mode(
        "https://example.test", 3, (1, 1), use_spain_facet=False
    )
    assert len(cards) == 1
    assert diag["pagination_repeat_detected"] is True
    assert diag["repeated_pages"] == [1]
    assert diag["stop_reason"] == "pagination_repeat"
    assert diag["coverage_complete"] is False
    assert "pagination_repeat" in diag["coverage_warning"]


def test_v193_unhonored_spain_facet_is_incomplete(monkeypatch):
    euraxess._FEED_CACHE.clear()

    class Response:
        text = """
        <div><a href="/jobs/123456">Researcher in Materials</a>
        JOB Sweden Example University Posted on: 20 September 2026 Work Locations: Sweden</div>
        """
        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()
        def close(self):
            pass

    monkeypatch.setattr(euraxess, "make_retry_session", lambda **kwargs: Session())
    cards, diag = euraxess._fetch_mode(
        "https://example.test", 1, (1, 1), use_spain_facet=True
    )
    assert cards == []
    assert diag["facet_honored"] is False
    assert diag["coverage_complete"] is False
    assert "spain_facet_not_honored" in diag["coverage_warning"]


def test_v193_live_warning_surfaces_pagination_repeat():
    diag = {
        "feed": {
            "mode": "generic_feed_local_spain_filter",
            "coverage_complete": False,
            "page_errors": [],
            "pagination_repeat_detected": True,
            "coverage_warning": "EURAXESS coverage incomplete: pagination_repeat_pages=[1]",
        },
        "candidate_truncated": 0,
        "detail_rate_limited": False,
    }
    args = SimpleNamespace(history_days=None)
    warnings = production._warnings_for_source("euraxess", diag, args)
    assert any("pagination repeated" in w.lower() for w in warnings)
    assert any("coverage incomplete" in w.lower() for w in warnings)
    assert production._coverage_complete("euraxess", diag, args) is False
