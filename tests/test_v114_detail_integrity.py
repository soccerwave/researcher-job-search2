from sources.fetch_detail import (
    _attachment_links,
    _detail_matches_title,
    _looks_like_attachment_shell,
    fetch_url_text,
)


class FakeResponse:
    def __init__(self, url, text, ctype="text/html"):
        self.url = url
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("unexpected network call")
        return self.responses.pop(0)


def test_generic_job_index_is_not_accepted_as_specific_full_jd():
    html = """
    <html><main>
      <h1>Job opportunities</h1>
      <p>Scientific Jobs</p>
      <p>Postdoctoral position in another lab</p>
      <p>Research Technician in another lab</p>
      <p>External Jobs</p>
      <p>In case you cannot find a suitable position, submit a general application.</p>
    </main></html>
    """
    session = FakeSession([FakeResponse("https://example.org/jobs", html)])
    detail, status = fetch_url_text(
        "https://example.org/jobs",
        title_hint="Postdoc in the Dynamics of Protein Synthesis and RNA Decay Lab",
        session=session,
    )
    assert detail == ""
    assert status == "DETAIL_MISMATCH"


def test_generic_open_application_page_is_rejected_for_named_role():
    text = (
        "JOB OPENINGS Applications are always welcome for: Veterinarian Pathologist "
        "QA Auditor Bioanalysis Laboratory Technician Business Development IT Engineer"
    )
    assert not _detail_matches_title("Bioanalysis, IMBA Study Director", text)


def test_attachment_shell_detection_and_candidate_ranking():
    html = """
    <html><body>
      <h1>Técnico/a de investigación en CREBA</h1>
      <p>Bases y requisitos de la convocatoria en el documento adjunto.</p>
      <a href="/privacy.pdf">Privacy policy</a>
      <a href="/files/oferta-trabajo-037-26.pdf">Oferta trabajo_037-26</a>
    </body></html>
    """
    assert _looks_like_attachment_shell("Bases y requisitos de la convocatoria en el documento adjunto")
    links = _attachment_links(html, "https://example.org/jobs/498", "Técnico/a de investigación en CREBA")
    assert links == ["https://example.org/files/oferta-trabajo-037-26.pdf"]


def test_thin_attachment_shell_follows_job_like_html_attachment_once():
    landing = """
    <html><main>
      <h1>Technician for Epidemiology and Biostatistics Unit</h1>
      <p>Download is available until the deadline.</p>
      <a href="/full-job-offer">Download full job offer</a>
    </main></html>
    """
    full = """
    <html><main>
      <h1>Technician for Epidemiology and Biostatistics Unit</h1>
      <p>Responsibilities include methodological support for epidemiological studies, study design,
      sample-size calculation, statistical analysis, database quality control and collaboration with
      biomedical researchers. Requirements include training in epidemiology or biostatistics and
      experience using R or comparable statistical software. This is a part-time research support role.</p>
    </main></html>
    """
    session = FakeSession([
        FakeResponse("https://example.org/download/job", landing),
        FakeResponse("https://example.org/full-job-offer", full),
    ])
    detail, status = fetch_url_text(
        "https://example.org/download/job",
        title_hint="Technician for Epidemiology and Biostatistics Unit",
        session=session,
    )
    assert "sample-size calculation" in detail
    assert status == "OK_ATTACHMENT"
    assert len(session.calls) == 2


def test_generic_title_can_still_accept_real_detailed_page():
    text = "Laboratory Technician Responsibilities include molecular assays, sample processing and quality control. Requirements include one year of laboratory experience. " * 6
    assert _detail_matches_title("Laboratory Technician", text)
