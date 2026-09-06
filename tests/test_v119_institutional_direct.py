from __future__ import annotations

from sources import institutions


def test_parse_teamtailor_jobs_uses_numeric_job_urls_and_heading_title():
    html = """
    <main>
      <a class='job-card' href='/jobs/8148267-junior-core-facility-coordinator'>
        <div><h3>Junior Core Facility Coordinator</h3><span class='job-location'>Barcelona</span></div>
      </a>
      <a href='/jobs'>All jobs</a>
      <a href='/locations/barcelona'>Barcelona</a>
    </main>
    """
    jobs = institutions.parse_teamtailor_jobs(html, 'https://jobs.example.org/jobs', 'Example Institute')
    assert len(jobs) == 1
    j = jobs[0]
    assert j['source'] == 'Institutions'
    assert j['title'] == 'Junior Core Facility Coordinator'
    assert j['company'] == 'Example Institute'
    assert j['location'] == 'Barcelona'
    assert j['id'] == '8148267'
    assert j['url'] == 'https://jobs.example.org/jobs/8148267-junior-core-facility-coordinator'


class FakeResponse:
    def __init__(self, text, url, status_code=200):
        self.text = text
        self.url = url
        self.status_code = status_code
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


class FakeSession:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url not in self.mapping:
            raise RuntimeError('unavailable')
        return FakeResponse(self.mapping[url], url)
    def close(self):
        pass


def test_collect_is_fail_soft_per_board_and_no_fit_prefilter(monkeypatch):
    boards = [
        {'name': 'Health Centre', 'url': 'https://health.example/jobs'},
        {'name': 'Broken Centre', 'url': 'https://broken.example/jobs'},
    ]
    monkeypatch.setattr(institutions, 'BOARDS', boards)
    html = """
    <a href='/jobs/1-project-manager'><h3>Project Manager</h3><span class='job-location'>Madrid</span></a>
    <a href='/jobs/2-quantum-engineer'><h3>Quantum Engineer</h3><span class='job-location'>Madrid</span></a>
    """
    fake = FakeSession({'https://health.example/jobs': html})
    monkeypatch.setattr(institutions, 'make_retry_session', lambda **kwargs: fake)
    monkeypatch.setattr(institutions, 'fetch_url_text', lambda *a, **k: ('full valid job detail ' * 60, 'OK_HTML'))
    diag = {}
    jobs = institutions.collect(diagnostics=diag)
    assert {j['title'] for j in jobs} == {'Project Manager', 'Quantum Engineer'}
    assert diag['boards_fetched'] == 1
    assert len(diag['board_errors']) == 1
    assert diag['detail_success'] == 2


def test_direct_collector_does_not_apply_fit_prefilter(monkeypatch):
    monkeypatch.setattr(institutions, 'BOARDS', [{'name': 'X', 'url': 'https://x.example/jobs'}])
    html = """
    <a href='/jobs/10-exercise-project-manager'><h3>Exercise Project Manager</h3></a>
    <a href='/jobs/11-quantum-materials-postdoc'><h3>Quantum Materials Postdoc</h3></a>
    """
    fake = FakeSession({'https://x.example/jobs': html})
    monkeypatch.setattr(institutions, 'make_retry_session', lambda **kwargs: fake)
    monkeypatch.setattr(institutions, 'fetch_url_text', lambda *a, **k: ('full detail ' * 100, 'OK_HTML'))
    jobs = institutions.collect(diagnostics={})
    assert len(jobs) == 2
