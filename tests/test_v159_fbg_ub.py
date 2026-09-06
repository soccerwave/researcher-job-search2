from datetime import date
from pathlib import Path

from jobbot.production import SOURCE_ORDER, _collector_map, verify_scoring_freeze
from run_live_sample import _assess_job_availability
from sources import fbg_ub


BOARD = '''
<html><body><table>
<tr><th>Codi</th><th>Director</th><th>Lloc de feina</th><th>Data inici</th><th>Data fi inscripció</th><th>PDF Oferta</th><th>Inscripció</th></tr>
<tr><td>202500402</td><td>Consiglio, Antonella</td><td>Ajudant Investigador</td><td>25-08-2026</td><td>04-09-2026</td><td><input /></td><td><input /></td></tr>
<tr><td>202500389</td><td>Patxot Cardoner, Concepció</td><td>Research Assistant to work on dynamic microsimulation.</td><td>30-07-2026</td><td>05-09-2026</td><td><input /></td><td><input /></td></tr>
</table></body></html>
'''


class FakeResponse:
    def __init__(self, text, url=fbg_ub.BOARD_URL):
        self.text = text
        self.url = url
        self.status_code = 200
    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, url, **kwargs):
        assert url == fbg_ub.BOARD_URL
        return FakeResponse(BOARD)
    def close(self):
        pass


def test_parse_current_board_rows_and_deadlines():
    rows = fbg_ub.parse_board_html(BOARD)
    assert [r["id"] for r in rows] == ["202500402", "202500389"]
    assert rows[0]["title"] == "Ajudant Investigador"
    assert rows[0]["date"] == "2026-09-04"
    assert rows[0]["start_date"] == "2026-08-25"
    assert rows[1]["application_deadline"] == "2026-09-05"
    assert "idoferta=202500389" in rows[1]["url"]


def test_board_deadline_controls_frozen_availability():
    rows = fbg_ub.parse_board_html(BOARD)
    assert _assess_job_availability(rows[0], date(2026, 8, 29))["application_status"] == "OPEN"
    assert _assess_job_availability(rows[0], date(2026, 9, 5))["application_status"] == "CLOSED"


def test_collect_enriches_all_current_offers(monkeypatch):
    monkeypatch.setattr(
        fbg_ub,
        "fetch_url_text",
        lambda url, **kwargs: ("Full FBG UB vacancy description " * 40, "OK_HTML"),
    )
    diag = {}
    rows = fbg_ub.collect(diagnostics=diag, session=FakeSession())
    assert len(rows) == 2
    assert diag["board_fetched"] is True
    assert diag["parsed_jobs"] == 2
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 0
    assert diag["coverage_complete"] is True
    assert all(r["trusted_full_detail_source"] == fbg_ub.SOURCE_NAME for r in rows)


def test_v159_source_registered_and_scoring_freeze_unchanged():
    assert "fbg" in SOURCE_ORDER
    assert _collector_map()["fbg"] is fbg_ub.collect
    root = Path(__file__).resolve().parents[1]
    assert verify_scoring_freeze(root)["ok"] is True


def test_fbg_idoferta_query_identity_prevents_same_endpoint_collapse():
    from jobbot.dedupe import deduplicate
    rows = fbg_ub.parse_board_html(BOARD)
    unique, removed = deduplicate(rows)
    assert len(unique) == 2
    assert removed == 0
