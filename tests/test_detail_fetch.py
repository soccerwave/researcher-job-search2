from sources.fetch_detail import _clean, _extract_html_text


def test_clean_collapses_whitespace():
    assert _clean("a\n  b\t c") == "a b c"


def test_html_extraction_removes_navigation_and_footer_noise():
    html = '''
    <html><body>
      <nav>Jobs Internship Helpdesk internship</nav>
      <main><h1>Postdoctoral Researcher</h1><section><p>Exercise neuroscience and physical activity research.</p></section></main>
      <footer>Social Media internship</footer>
    </body></html>
    '''
    text = _extract_html_text(html, title_hint="Postdoctoral Researcher")
    assert "Exercise neuroscience" in text
    assert "Helpdesk internship" not in text
    assert "Social Media internship" not in text
