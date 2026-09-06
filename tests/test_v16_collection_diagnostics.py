import pytest
import sources.euraxess as euraxess


def test_official_spain_facet_param_is_explicit():
    params = euraxess._page_params(2, True)
    assert params["f[0]"] == "job_country:788"
    assert params["page"] == "2"


def test_euraxess_zero_is_explainable_when_feed_was_fetched(monkeypatch):
    feed_diag = {
        "base": "https://www.euraxess.es",
        "mode": "official_spain_facet",
        "pages_requested": 1,
        "pages_fetched": 1,
        "parsed_cards": 2,
        "unique_cards": 2,
        "spain_cards": 2,
        "spain_ratio": 1.0,
        "page_errors": [],
        "attempts": [{"pages_fetched": 1, "parsed_cards": 2, "page_errors": []}],
    }
    cards = [
        {
            "source": "EURAXESS",
            "title": "Postdoctoral Researcher in Physical Activity and Health",
            "company": "University X",
            "location": "Spain",
            "description": "Physical activity intervention and health research",
            "url": "https://euraxess.ec.europa.eu/jobs/1",
        },
        {
            "source": "EURAXESS",
            "title": "Researcher in Quantum Materials",
            "company": "University Y",
            "location": "Spain",
            "description": "Quantum materials and condensed matter physics",
            "url": "https://euraxess.ec.europa.eu/jobs/2",
        },
    ]
    monkeypatch.setattr(euraxess, "_get_spain_feed", lambda pages, timeout: (cards, feed_diag, False))
    diag = {}
    jobs = euraxess.collect("physical activity", enrich_detail=False, pages=1, diagnostics=diag)
    assert len(jobs) == 1
    assert jobs[0]["title"].startswith("Postdoctoral")
    assert diag["spain_feed_cards"] == 2
    assert diag["query_card_matches"] == 1
    assert diag["kept"] == 1


def test_euraxess_inaccessible_feed_is_not_silent_zero(monkeypatch):
    feed_diag = {
        "base": "",
        "mode": "failed",
        "pages_requested": 1,
        "pages_fetched": 0,
        "parsed_cards": 0,
        "unique_cards": 0,
        "spain_cards": 0,
        "spain_ratio": 0.0,
        "page_errors": [],
        "attempts": [
            {"pages_fetched": 0, "parsed_cards": 0, "page_errors": ["page 0: 403 Forbidden"]}
        ],
    }
    monkeypatch.setattr(euraxess, "_get_spain_feed", lambda pages, timeout: ([], feed_diag, False))
    with pytest.raises(RuntimeError, match="inaccessible"):
        euraxess.collect("physical activity", enrich_detail=False, pages=1, diagnostics={})
