from datetime import date
from pathlib import Path

from jobbot.production import (
    PRODUCTION_VERSION,
    SOURCE_ORDER,
    _collector_map,
    _coverage_complete,
    _diagnostic_hard_error,
    verify_scoring_freeze,
)
from run_live_sample import _assess_job_availability
from sources import ikerbasque_calls


BOARD = '''
<html><body>
<nav>
  <a href="/en/calls/permanent-positions-2026">Permanent Positions 2026</a>
  <a href="/en/calls/ikerbasque-erc-fast-track-2026">Ikerbasque ERC Fast Track 2026</a>
  <a href="/en/calls/research-fellows-2026-1">Research Fellows 2026</a>
</nav>
<main>
  <section class="call-card"><h3><a href="/en/calls/permanent-positions-2026">Permanent Positions 2026</a></h3><h4>Open</h4><p>Ikerbasque offers 10 permanent positions for researchers willing to develop a long-term scientific career in the Basque Country.</p><a href="/en/calls/permanent-positions-2026">Read more</a></section>
  <section class="call-card"><h3><a href="/en/calls/ikerbasque-erc-fast-track-2026">Ikerbasque ERC Fast Track 2026</a></h3><h4>Open</h4><p>Permanent research positions for researchers who have obtained an ERC grant.</p><a href="/en/calls/ikerbasque-erc-fast-track-2026">Read more</a></section>
  <section class="call-card"><h3><a href="/en/calls/research-fellows-2026-1">Research Fellows 2026</a></h3><h4>Closed</h4><p>15 Research Fellow positions for postdoctoral researchers.</p><a href="/en/calls/research-fellows-2026-1">Read more</a></section>
</main>
</body></html>
'''


class FakeResponse:
    def __init__(self, text, url=ikerbasque_calls.BOARD_URL):
        self.text = text
        self.url = url
        self.status_code = 200
    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, url, **kwargs):
        assert url == ikerbasque_calls.BOARD_URL
        return FakeResponse(BOARD)
    def close(self):
        pass


def test_parse_calls_dedupes_navigation_and_preserves_board_status():
    rows = ikerbasque_calls.parse_board_html(BOARD)
    assert len(rows) == 3
    by_title = {r["title"]: r for r in rows}
    assert by_title["Permanent Positions 2026"]["source_application_status"] == "OPEN"
    assert by_title["Ikerbasque ERC Fast Track 2026"]["source_application_status"] == "OPEN"
    assert by_title["Research Fellows 2026"]["source_application_status"] == "CLOSED"
    assert by_title["Research Fellows 2026"]["id"] == "research-fellows-2026-1"


def test_board_status_is_source_authoritative_when_frozen_parser_has_no_deadline():
    rows = ikerbasque_calls.parse_board_html(BOARD)
    by_title = {r["title"]: r for r in rows}
    assert _assess_job_availability(by_title["Ikerbasque ERC Fast Track 2026"], date(2026, 8, 29))["application_status"] == "OPEN"
    assert _assess_job_availability(by_title["Research Fellows 2026"], date(2026, 8, 29))["application_status"] == "CLOSED"


def test_collect_is_lightweight_complete_and_enriches_every_call(monkeypatch):
    monkeypatch.setattr(
        ikerbasque_calls,
        "fetch_url_text",
        lambda url, **kwargs: ("Official Ikerbasque call full detail " * 45, "OK_HTML"),
    )
    diag = {}
    rows = ikerbasque_calls.collect(diagnostics=diag, session=FakeSession())
    assert len(rows) == 3
    assert diag["board_fetched"] is True
    assert diag["parsed_calls"] == 3
    assert diag["open_calls"] == 2
    assert diag["closed_calls"] == 1
    assert diag["status_unknown"] == 0
    assert diag["detail_success"] == 3
    assert diag["detail_failed"] == 0
    assert diag["coverage_complete"] is True
    assert all(r["trusted_full_detail_source"] == ikerbasque_calls.SOURCE_NAME for r in rows)


def test_ikerbasque_orchestration_contract_and_total_failure_reporting():
    complete = {"board_fetched": True, "coverage_complete": True, "truncated": 0}
    failed = {"board_fetched": False, "coverage_complete": False, "coverage_warning": "DNS failure"}
    assert _coverage_complete("ikerbasque", complete, object()) is True
    assert _diagnostic_hard_error("ikerbasque", failed) == "DNS failure"


def test_v161_source_registered_and_scoring_freeze_unchanged():
    assert "ikerbasque" in SOURCE_ORDER
    assert _collector_map()["ikerbasque"] is ikerbasque_calls.collect
    root = Path(__file__).resolve().parents[1]
    assert verify_scoring_freeze(root)["ok"] is True
