from datetime import date
import sources.euraxess as euraxess


def test_history_cutoff_is_inclusive_60_day_window():
    assert euraxess._history_cutoff(60, "2026-08-27") == date(2026, 6, 29)
    assert euraxess._parse_posted_date("27 August 2026") == date(2026, 8, 27)
    assert euraxess._parse_posted_date("") is None


def test_historical_fetch_filters_old_cards_and_stops_after_old_page(monkeypatch):
    pages = {
        "page0": [
            {"title": "Researcher A", "date": "27 August 2026", "location": "Spain", "url": "u1"},
            {"title": "Researcher B", "date": "10 August 2026", "location": "Spain", "url": "u2"},
        ],
        "page1": [
            {"title": "Researcher C", "date": "30 June 2026", "location": "Spain", "url": "u3"},
            {"title": "Researcher D", "date": "28 June 2026", "location": "Spain", "url": "u4"},
        ],
        "page2": [
            {"title": "Researcher E", "date": "20 June 2026", "location": "Spain", "url": "u5"},
        ],
    }

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
            return Resp(f"page{page}")
        def close(self):
            pass

    session = Session()
    monkeypatch.setattr(euraxess, "make_retry_session", lambda **kwargs: session)
    monkeypatch.setattr(euraxess, "parse_search_html", lambda html: pages.get(html, []))
    monkeypatch.setattr(euraxess, "_is_spain", lambda job: True)

    cards, diag = euraxess._fetch_mode(
        "https://example.test", pages=10, timeout=(1, 1), use_spain_facet=True,
        cutoff_date=date(2026, 6, 29),
    )

    assert [c["url"] for c in cards] == ["u1", "u2", "u3"]
    # page1 straddles the cutoff, so page2 is fetched; page2 is entirely old and stops traversal.
    assert session.calls == [0, 1, 2]
    assert diag["stop_reason"] == "cutoff_reached"
    assert diag["cutoff_date"] == "2026-06-29"
    assert diag["oldest_seen_date"] == "2026-06-20"
