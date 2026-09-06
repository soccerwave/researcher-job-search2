from jobbot.availability import assess_availability
from jobbot.production import SOURCE_ORDER, selected_sources
from sources import idibell

BOARD_FIXTURE = '''
<html><body><table><tbody>
<tr><td><a href="/convocatoriaspropias/en/Convocatorias/VerConvocatoria/2176">26-121_MS_PJ - Scientific Project Manager - DynamiCity Project</a></td><td>07/08/2026 00:00</td><td>30/09/2026 23:59</td></tr>
<tr><td><a href="/convocatoriaspropias/en/Convocatorias/VerConvocatoria/2186">26-126_SS_VN Study Coordinator for Cancer Clinical Trials</a></td><td>13/08/2026 00:00</td><td>07/09/2026 23:59</td></tr>
</tbody></table></body></html>
'''

DETAIL_FIXTURE = '''
<html><body><main>
<h1>26-121_MS_PJ - Scientific Project Manager - DynamiCity Project</h1>
<p>Application Submission process From: 07/08/2026 To: 30/09/2026</p>
<h2>About the role</h2>
<p>IDIBELL is looking for an experienced Project Manager to coordinate a Horizon Europe project focused on active mobility, physical activity and cancer prevention.</p>
<h2>Key responsibilities</h2><p>Coordinate study procedures, participant recruitment, data collection, quality assurance and international consortium activities.</p>
<h2>Job requirements</h2><p>At least 4 years of research experience; degree in Health Sciences; experience in non-pharmacological intervention studies and European collaborative research projects.</p>
<p>''' + ('Research project management physical activity epidemiology implementation study coordination. ' * 20) + '''</p>
</main></body></html>
'''


def test_idibell_board_parser_reads_reference_and_deadline():
    rows = idibell.parse_board_html(BOARD_FIXTURE)
    assert len(rows) == 2
    assert rows[0]["id"] == "26-121_MS_PJ"
    assert rows[0]["date"] == "30/09/2026"
    assert rows[0]["company"] == "IDIBELL"


def test_idibell_deadline_flows_through_existing_availability_logic():
    row = idibell.parse_board_html(BOARD_FIXTURE)[0]
    result = assess_availability(row, "2026-08-29")
    assert result["application_status"] == "OPEN"
    assert result["application_deadline"] == "2026-09-30"


def test_idibell_is_production_source():
    assert "idibell" in SOURCE_ORDER
    assert selected_sources("idibell") == ["idibell"]
    assert "idibell" in selected_sources("all")


def test_idibell_collect_uses_official_detail_page_as_full_jd(monkeypatch):
    class Response:
        def __init__(self, text, url):
            self.text = text
            self.url = url
        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, *args, **kwargs):
            return Response(BOARD_FIXTURE, url)
        def close(self):
            return None

    monkeypatch.setattr(idibell, "make_retry_session", lambda **kwargs: Session())
    monkeypatch.setattr(idibell, "fetch_url_text", lambda url, **kwargs: (DETAIL_FIXTURE, "OK_HTML"))
    diag = {}
    rows = idibell.collect(diagnostics=diag)
    assert len(rows) == 2
    assert diag["detail_success"] == 2
    assert diag["detail_failed"] == 0
    assert diag["coverage_complete"] is True
    assert all(r["detail_status"] == "OK_HTML" for r in rows)
    assert all(r["trusted_full_detail_source"] == idibell.SOURCE_NAME for r in rows)
