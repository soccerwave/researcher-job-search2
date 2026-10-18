"""Regression checks for uncapped EURAXESS discovery and truthful coverage."""
from urllib.parse import parse_qs, urlparse

from sources.euraxess_transport import fetch_spain_pages


class Response:
    status_code = 200
    headers = {}

    def __init__(self, url, html):
        self.url, self.text = url, html

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, total_pages=12, empty_terminal=False):
        self.total_pages = total_pages
        self.empty_terminal = empty_terminal
        self.calls = []

    def get(self, url, **kwargs):
        return self._response("GET", url)

    def post(self, url, **kwargs):
        return self._response("POST", url)

    def _response(self, method, url):
        self.calls.append((method, url))
        page = int(parse_qs(urlparse(url).query).get("page", ["0"])[0])
        if page >= self.total_pages:
            return Response(url, "")
        nxt = f'<a rel="next" href="/jobs/search?page={page+1}">Next</a>'
        if page == self.total_pages - 1 and not self.empty_terminal:
            nxt = ""
        return Response(url, f"JOB_ROW:{page}\n{nxt}")

    def close(self):
        pass


def run(pages=None, total_pages=12, empty_terminal=False, deadline=None):
    session = Session(total_pages, empty_terminal)
    def parse(html):
        import re
        match = re.search(r"JOB_ROW:(\d+)", html)
        return [{"id": match.group(1), "url": f"https://euraxess.ec.europa.eu/jobs/{match.group(1)}",
                 "location": "Spain", "date": ""}] if match else []
    cards, diag = fetch_spain_pages(
        base="https://euraxess.ec.europa.eu", pages=pages, timeout=(1, 1),
        use_spain_facet=False, parse_search_html=parse,
        is_spain=lambda card: card["location"] == "Spain",
        parse_posted_date=lambda value: None, make_session=lambda **kwargs: session,
        deadline=deadline,
    )
    return cards, diag


def test_uncapped_traverses_beyond_eight_pages(monkeypatch):
    monkeypatch.setattr("sources.euraxess_transport.time.sleep", lambda _: None)
    cards, diag = run()
    assert diag["pages_fetched"] == 12
    assert len(cards) == 12
    assert diag["stop_reason"] == "last_page"
    assert diag["coverage_complete"] is True


def test_configured_page_limit_is_partial(monkeypatch):
    monkeypatch.setattr("sources.euraxess_transport.time.sleep", lambda _: None)
    _, diag = run(pages=8)
    assert diag["pages_fetched"] == 8
    assert diag["stop_reason"] == "configured_page_limit"
    assert diag["coverage_complete"] is False


def test_empty_page_completion(monkeypatch):
    monkeypatch.setattr("sources.euraxess_transport.time.sleep", lambda _: None)
    _, diag = run(empty_terminal=True)
    assert diag["stop_reason"] == "empty_page"
    assert diag["coverage_complete"] is True


def test_default_collect_is_uncapped():
    from inspect import signature
    from sources.euraxess import collect
    assert signature(collect).parameters["pages"].default is None


def test_expired_listing_budget_is_partial():
    import time
    _, diag = run(deadline=time.monotonic() - 1)
    assert diag["stop_reason"] == "time_budget"
    assert diag["coverage_complete"] is False


def test_expired_detail_budget_defers_without_network_call():
    import time
    from sources.euraxess_transport import fetch_detail_resilient
    class NoNetwork:
        pass
    def never_fetch(*args, **kwargs):
        raise AssertionError("Expired budget must not hit network")
    detail, status, count = fetch_detail_resilient(
        never_fetch, "https://euraxess.ec.europa.eu/jobs/42",
        timeout=(10, 45), title_hint="Researcher", session=NoNetwork(),
        pace_seconds=0, deadline=time.monotonic() - 1,
    )
    assert (detail, status, count) == ("", "DEFERRED_TIME_BUDGET", 0)


def test_reset_to_first_page_does_not_prove_complete_coverage(monkeypatch):
    """A simulated pagination reset is partial, even when initial pages were valid."""
    monkeypatch.setattr("sources.euraxess_transport.time.sleep", lambda _: None)

    class ResetSession(Session):
        def _response(self, method, url):
            self.calls.append((method, url))
            page = int(parse_qs(urlparse(url).query).get("page", ["0"])[0])
            row = 0 if page >= 3 else page
            nxt = f'<a rel="next" href="/jobs/search?page={page + 1}">Next</a>'
            return Response(url, f"JOB_ROW:{row}\n{nxt}")

    session = ResetSession()
    def parse(html):
        import re
        m = re.search(r"JOB_ROW:(\d+)", html)
        return [{"id": m.group(1), "url": "https://euraxess.ec.europa.eu/jobs/" + m.group(1),
                 "location": "Spain", "date": ""}] if m else []
    cards, diag = fetch_spain_pages(
        base="https://euraxess.ec.europa.eu", pages=None, timeout=(1, 1),
        use_spain_facet=False, parse_search_html=parse,
        is_spain=lambda c: True, parse_posted_date=lambda _: None,
        make_session=lambda **kwargs: session,
    )
    assert len(cards) == 3
    assert diag["stop_reason"] == "last_page_reset_unverified"
    assert diag["coverage_complete"] is False
    assert diag["pagination_repeat_detected"] is True


def test_restored_valid_detail_avoids_network_and_expired_entry_is_ignored(monkeypatch, tmp_path):
    """Replay a recurrent job from a R2-restored cache snapshot."""
    import json
    from datetime import datetime, timedelta
    from sources import euraxess

    url = "https://euraxess.ec.europa.eu/jobs/123"
    card = {
        "url": url, "id": "123", "title": "Research Project Manager",
        "company": "Example Institute", "description": "JOB Spain Example Institute",
        "location": "Spain", "date": "18 October 2026",
    }
    detail = "Job Information Country Spain Offer Description Research Project Manager"
    cache_file = tmp_path / "euraxess_details.json"
    monkeypatch.setattr(euraxess, "DETAIL_CACHE_PATH", cache_file)
    euraxess._DETAIL_CACHE.clear()
    euraxess._FEED_CACHE.clear()
    diag_feed = {
        "mode": "generic_feed_local_spain_filter", "coverage_complete": True,
        "spain_cards": 1, "spain_ratio": 1, "pages_fetched": 1,
        "parsed_cards": 1, "unique_cards": 1, "page_errors": [],
        "coverage_warning": "", "attempts": [{"pages_fetched": 1, "parsed_cards": 1}],
    }
    monkeypatch.setattr(euraxess, "_get_spain_feed", lambda *args, **kwargs: ([dict(card)], dict(diag_feed), False))
    class Session:
        def close(self):
            pass
    monkeypatch.setattr(euraxess, "make_retry_session", lambda **kwargs: Session())
    def no_network(*args, **kwargs):
        raise AssertionError("Repeated full-JD fetch despite valid cache")
    monkeypatch.setattr(euraxess, "fetch_url_text", no_network)
    fresh = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
    cache_file.write_text(json.dumps({url: {"detail": detail, "status": "OK_HTML", "fetched_at": fresh}}))
    diag = {}
    jobs = euraxess.collect(diagnostics=diag)
    assert len(jobs) == 1
    assert jobs[0]["full_detail"] == detail
    assert diag["detail_persistent_cache_hits"] == 1
    assert diag["detail_network_requests"] == 0
