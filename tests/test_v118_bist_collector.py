from __future__ import annotations

import json

from sources import bist


def test_parse_rest_payload_reads_standard_wpjm_fields():
    payload = [
        {
            "id": 123,
            "date": "2026-08-27T09:00:00",
            "link": "https://bist.eu/job/example-centre-barcelona-research-project-manager/",
            "title": {"rendered": "Research &amp; Project Manager"},
            "content": {"rendered": "<p>Coordinate a European research consortium.</p>"},
            "meta": {
                "_company_name": "Example Centre",
                "_job_location": "Barcelona",
                "_job_expires": "2026-09-30",
            },
        }
    ]
    jobs = bist.parse_rest_payload(payload)
    assert len(jobs) == 1
    j = jobs[0]
    assert j["source"] == "BIST"
    assert j["title"] == "Research & Project Manager"
    assert j["company"] == "Example Centre"
    assert j["location"] == "Barcelona"
    assert j["id"] == "123"
    assert "Closing date: 2026-09-30" in j["description"]


def test_parse_ajax_html_reads_wpjm_cards():
    html = """
    <ul class='job_listings'>
      <li class='job_listing'>
        <a href='https://bist.eu/job/example-centre-barcelona-project-officer/'>
          <div class='position'><h3>Project Officer</h3><div class='company'><strong>Example Centre</strong></div></div>
          <div class='location'>Barcelona</div>
          <ul class='meta'><li class='date'><time datetime='2026-08-27'>Posted today</time></li></ul>
        </a>
      </li>
    </ul>
    """
    jobs = bist.parse_ajax_html(html)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Project Officer"
    assert jobs[0]["company"] == "Example Centre"
    assert jobs[0]["location"] == "Barcelona"
    assert jobs[0]["date"] == "2026-08-27"


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json", "X-WP-TotalPages": "1"}
        self.text = text
        self.url = bist.REST_ENDPOINT

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, get_response=None, post_response=None):
        self.get_response = get_response
        self.post_response = post_response
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if isinstance(self.get_response, Exception):
            raise self.get_response
        return self.get_response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response

    def close(self):
        pass


def test_rest_feed_is_preferred(monkeypatch):
    payload = [{
        "id": 7,
        "date": "2026-08-27T00:00:00",
        "link": "https://bist.eu/job/x-barcelona-project-manager/",
        "title": {"rendered": "Project Manager"},
        "content": {"rendered": "<p>EU project management and research.</p>"},
    }]
    fake = FakeSession(get_response=FakeResponse(payload=payload))
    monkeypatch.setattr(bist, "make_retry_session", lambda **kwargs: fake)
    monkeypatch.setattr(bist, "fetch_url_text", lambda *a, **k: ("Project Manager EU research full job description " * 20, "OK_HTML"))
    diag = {}
    jobs = bist.collect(diagnostics=diag)
    assert len(jobs) == 1
    assert diag["feed_mode"] == "wp_rest"
    assert diag["detail_success"] == 1
    assert not fake.post_calls


def test_ajax_fallback_when_rest_unavailable(monkeypatch):
    fragment = """
    <li class='job_listing'><a href='https://bist.eu/job/x-barcelona-project-officer/'>
    <h3>Project Officer</h3><div class='company'>Centre X</div><div class='location'>Barcelona</div>
    </a></li>
    """
    fake = FakeSession(
        get_response=RuntimeError("REST unavailable"),
        post_response=FakeResponse(payload={"html": fragment, "max_num_pages": 1}),
    )
    monkeypatch.setattr(bist, "make_retry_session", lambda **kwargs: fake)
    monkeypatch.setattr(bist, "fetch_url_text", lambda *a, **k: ("Project Officer research coordination full description " * 20, "OK_HTML"))
    diag = {}
    jobs = bist.collect(diagnostics=diag)
    assert len(jobs) == 1
    assert diag["feed_mode"] in {"jm_ajax", "admin_ajax"}
    assert diag["rest_error"]
    assert diag["detail_success"] == 1


def test_bist_does_not_apply_fit_prefilter(monkeypatch):
    payload = [
        {"id": 1, "link": "https://bist.eu/job/x-barcelona-quantum-scientist/", "title": {"rendered": "Quantum Scientist"}, "content": {"rendered": "<p>Quantum.</p>"}},
        {"id": 2, "link": "https://bist.eu/job/x-barcelona-project-manager/", "title": {"rendered": "Project Manager"}, "content": {"rendered": "<p>Health research.</p>"}},
    ]
    fake = FakeSession(get_response=FakeResponse(payload=payload))
    monkeypatch.setattr(bist, "make_retry_session", lambda **kwargs: fake)
    monkeypatch.setattr(bist, "fetch_url_text", lambda *a, **k: ("full valid job detail " * 40, "OK_HTML"))
    jobs = bist.collect(diagnostics={})
    assert {j["title"] for j in jobs} == {"Quantum Scientist", "Project Manager"}
