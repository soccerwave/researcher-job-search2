from sources.biocat import parse_board_html
from sources.euraxess import parse_search_html


def test_biocat_parser_minimal():
    html = '''<div class="offer"><div>Biocat - Technical</div><h3><a href="/job/123">TÈCNIC/A DE PROJECTES D’INNOVACIÓ</a></h3><div>Entity: Support association Sector: Others Location: Barcelona Ends: 28.08.2026</div></div>'''
    jobs = parse_board_html(html)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "TÈCNIC/A DE PROJECTES D’INNOVACIÓ"
    assert jobs[0]["location"] == "Barcelona"


def test_euraxess_parser_minimal():
    html = '''<div><span>JOB Spain University X Posted on: 21 August 2026</span><h3><a href="/jobs/12345">Postdoctoral Researcher in Physical Activity and Health</a></h3></div>'''
    jobs = parse_search_html(html, "physical activity")
    assert len(jobs) == 1
    assert "Physical Activity" in jobs[0]["title"]
    assert jobs[0]["source"] == "EURAXESS"
