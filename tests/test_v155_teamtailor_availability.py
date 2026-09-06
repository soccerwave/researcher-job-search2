from datetime import date

from run_live_sample import _assess_job_availability
from sources.institutions import parse_teamtailor_jobs


def test_teamtailor_listing_marks_current_job_open():
    html = '''
    <html><body>
      <a href="/jobs/12345-research-project-manager">
        <div><h3>Research Project Manager</h3><span class="location">Barcelona</span></div>
      </a>
    </body></html>
    '''
    rows = parse_teamtailor_jobs(html, "https://jobs.example.org/jobs", "Example Institute")
    assert len(rows) == 1
    assert rows[0]["source_application_status"] == "OPEN"
    assert rows[0]["source_status_evidence"] == "Listed on current Teamtailor jobs board"


def test_source_open_marker_resolves_unknown_availability():
    job = {
        "source": "Institutions",
        "title": "Research Project Manager",
        "company": "Example Institute",
        "url": "https://jobs.example.org/jobs/12345-research-project-manager",
        "full_detail": "Coordinate a multidisciplinary European research project.",
        "source_application_status": "OPEN",
        "source_status_evidence": "Listed on current Teamtailor jobs board",
    }
    result = _assess_job_availability(job, date(2026, 8, 29))
    assert result["application_status"] == "OPEN"
    assert result["deadline_evidence"] == "Listed on current Teamtailor jobs board"


def test_explicit_expired_deadline_still_overrides_source_open_marker():
    job = {
        "source": "Institutions",
        "title": "Research Project Manager",
        "company": "Example Institute",
        "url": "https://jobs.example.org/jobs/12345-research-project-manager",
        "date": "2026-01-01",
        "description": "Application deadline: 2026-08-01",
        "full_detail": "Application deadline: 2026-08-01. Coordinate a research project.",
        "source_application_status": "OPEN",
        "source_status_evidence": "Listed on current Teamtailor jobs board",
    }
    result = _assess_job_availability(job, date(2026, 8, 29))
    assert result["application_status"] == "CLOSED"
