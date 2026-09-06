from datetime import date
from pathlib import Path

from jobbot.production import SOURCE_ORDER, _collector_map, verify_scoring_freeze
from run_live_sample import _assess_job_availability
from sources import sant_pau_research


BOARD_1 = '''
<html><body>
<a href="/en/w/ac6a-study-coordinator-7">Open Ref. 2026_121 2026/121: 1 AC6A - Study Coordinator Call for applications for an AC6A – Study Coordinator position at the Drug Research Centre (CIM). Application deadline: 11 September 2026 at 3:00 p.m. Join</a>
<a href="/en/w/t4a-ici-22-isc iii">Open Ref. 2026_120 2026/120: 1 T4A ICI 22 ISCIII Call for applications for a T4A ICI 22 ISCIII position. Application deadline: 25 August 2026 at 3:00 p.m. Join</a>
<a href="/en/w/internal-promotion">Open Ref. 2026_114 Internal Promotion 2026/114: 1 T4A – Junior Higher Technician Call for applications for an internal position. Application deadline: 11 August 2026 at 3:00 p.m. Join</a>
<a href="/en/w/closed-role">Closed Ref. 2026/112 2026/112: 1 AUL – Laboratory Assistant Deadline: 31 July 2026</a>
<div>Showing 1 to 60 of 61 entries.</div>
</body></html>
'''

BOARD_2 = '''
<html><body>
<a href="/en/w/research-tech">Open Ref. 2026/123 2026/123: 1 T2 - Research Technician Call for a T2 role. Application deadline: 20 September 2026 at 3:00 p.m. Join</a>
<div>Showing 61 to 61 of 61 entries.</div>
</body></html>
'''


class FakeResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url
        self.status_code = 200
    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, url, **kwargs):
        if "start=1" in url:
            return FakeResponse(BOARD_1, url)
        if "start=2" in url:
            return FakeResponse(BOARD_2, url)
        raise AssertionError(url)
    def close(self):
        pass


def test_board_parser_keeps_external_open_calls_and_normalizes_deadline():
    rows, total = sant_pau_research.parse_board_html(BOARD_1)
    assert total == 61
    assert [r["id"] for r in rows] == ["2026_121", "2026_120"]
    assert rows[0]["title"] == "AC6A - Study Coordinator"
    assert rows[0]["date"] == "2026-09-11"
    assert rows[1]["date"] == "2026-08-25"


def test_sant_pau_deadline_overrides_stale_open_board_label():
    rows, _ = sant_pau_research.parse_board_html(BOARD_1)
    current = _assess_job_availability(rows[0], date(2026, 8, 29))
    stale = _assess_job_availability(rows[1], date(2026, 8, 29))
    assert current["application_status"] == "OPEN"
    assert stale["application_status"] == "CLOSED"


def test_collect_paginates_board_dedupes_and_enriches(monkeypatch):
    monkeypatch.setattr(
        sant_pau_research,
        "fetch_url_text",
        lambda url, **kwargs: ("Full IR Sant Pau research vacancy detail " * 30, "OK_HTML"),
    )
    diag = {}
    rows = sant_pau_research.collect(diagnostics=diag, session=FakeSession())
    assert len(rows) == 3
    assert {r["id"] for r in rows} == {"2026_121", "2026_120", "2026_123"}
    assert diag["pages_fetched"] == 2
    assert diag["board_total_reported"] == 61
    assert diag["detail_success"] == 3
    assert diag["detail_failed"] == 0
    assert diag["coverage_complete"] is True


def test_v158_source_registered_and_scoring_freeze_unchanged():
    assert "santpau" in SOURCE_ORDER
    assert _collector_map()["santpau"] is sant_pau_research.collect
    root = Path(__file__).resolve().parents[1]
    assert verify_scoring_freeze(root)["ok"] is True
