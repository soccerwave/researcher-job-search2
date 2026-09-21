from sources.biocat import parse_board_html


def _card(title: str, external: str, document: str) -> str:
    return f"""
    <article>
      <div>IRIS-CC - Technical</div>
      <h3><a href="{external}">{title}</a></h3>
      <a href="{document}">Job offer document</a>
      <div>Entity: Research center and institute Sector: Biomedical research Location: Barcelona Ends: 30.09.2026</div>
    </article>
    """


def test_v194_prefers_biocat_hosted_offer_document():
    html = _card(
        "Biorepository Technician",
        "https://www.cnag.eu/jobs",
        "/sites/default/files/webform/send_job_offer/6321/biorepository.pdf",
    )
    jobs = parse_board_html(html)
    assert len(jobs) == 1
    assert jobs[0]["url"] == (
        "https://www.biocat.cat/sites/default/files/webform/"
        "send_job_offer/6321/biorepository.pdf"
    )


def test_v194_same_title_distinct_documents_are_not_deduplicated():
    title = "Tècnic/a superior per a l’Àrea Prioritària de Recerca de Clínica de l’IRIS-CC"
    html = (
        _card(
            title,
            "https://iris-cc.cat/download/tecnic-superior",
            "/sites/default/files/webform/send_job_offer/7994/we-mind-1.pdf",
        )
        + _card(
            title,
            "https://iris-cc.cat/download/tecnic-superior",
            "/sites/default/files/webform/send_job_offer/7995/we-mind-2.pdf",
        )
    )
    jobs = parse_board_html(html)
    assert len(jobs) == 2
    assert {job["url"] for job in jobs} == {
        "https://www.biocat.cat/sites/default/files/webform/send_job_offer/7994/we-mind-1.pdf",
        "https://www.biocat.cat/sites/default/files/webform/send_job_offer/7995/we-mind-2.pdf",
    }
