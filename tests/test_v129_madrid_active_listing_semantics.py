from sources.madrid_idi import parse_listing_page


def test_madrid_card_marks_live_result_as_active_listing():
    html = """
    <div class='view-header'>Mostrando 1-1 de <strong>1</strong> ofertas activas encontradas</div>
    <div class='view-content'>
      <div class='job-item'>
        <a href='https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/12345' class='job-link'></a>
        <h3 class='job-title'>Research Project Manager</h3>
        <p class='job-organization'>Research Foundation</p>
        <div class='job-location'><span>Madrid</span></div>
        <span class='job-time'><div>20/08/2026</div></span>
      </div>
    </div>
    """
    jobs, meta = parse_listing_page(html)
    assert len(jobs) == 1
    assert jobs[0]["source_listing_active"] is True
    assert meta["expected_cards"] == 1
