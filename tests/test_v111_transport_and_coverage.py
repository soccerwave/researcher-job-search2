from datetime import date
import sources.euraxess as euraxess
from sources.fetch_detail import make_retry_session


def test_retry_session_ignores_malformed_retry_after_header():
    session = make_retry_session(total_retries=2, backoff_factor=0.5)
    try:
        retry = session.get_adapter("https://").max_retries
        assert retry.respect_retry_after_header is False
        assert 429 in retry.status_forcelist
    finally:
        session.close()


def test_historical_page_failure_stops_without_skipping_gap(monkeypatch):
    class Resp:
        def __init__(self, text):
            self.text = text
        def raise_for_status(self):
            return None

    class Session:
        def __init__(self):
            self.calls = []
        def get(self, url, params=None, timeout=None, allow_redirects=True):
            page = int((params or {}).get("page", 0))
            self.calls.append(page)
            if page == 1:
                raise RuntimeError("simulated rate limit after retries")
            return Resp(f"page{page}")
        def close(self):
            pass

    session = Session()
    monkeypatch.setattr(euraxess, "make_retry_session", lambda **kwargs: session)
    monkeypatch.setattr(
        euraxess,
        "parse_search_html",
        lambda html: [{"title": "Postdoctoral Researcher", "date": "27 August 2026",
                       "location": "Spain", "url": "u1"}] if html == "page0" else [],
    )
    monkeypatch.setattr(euraxess, "_is_spain", lambda job: True)

    cards, diag = euraxess._fetch_mode(
        "https://example.test", pages=10, timeout=(1, 1), use_spain_facet=True,
        cutoff_date=date(2026, 6, 29), request_delay=0.0,
    )

    assert [c["url"] for c in cards] == ["u1"]
    assert session.calls == [0, 1]
    assert diag["stop_reason"] == "page_fetch_error"
    assert diag["coverage_complete"] is False
    assert "Historical coverage incomplete" in diag["coverage_warning"]
