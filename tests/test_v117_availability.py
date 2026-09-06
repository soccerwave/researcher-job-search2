from datetime import date
from jobbot.availability import assess_availability

ASOF = date(2026, 8, 27)


def test_future_explicit_deadline_beats_unreliable_expired_footer():
    job = {
        "source": "EURAXESS",
        "full_detail": "Application Deadline 30 Sep 2026 - 23:59 STATUS: EXPIRED",
    }
    a = assess_availability(job, ASOF)
    assert a["application_status"] == "OPEN"
    assert a["application_deadline"] == "2026-09-30"


def test_corrupt_metadata_year_ignored_body_deadline_closes_job():
    job = {
        "source": "EURAXESS",
        "full_detail": "Application Deadline 25 Aug 5206 - 15:00. The application deadline is 25 August 2026 at 3:00 p.m.",
    }
    a = assess_availability(job, ASOF)
    assert a["application_status"] == "CLOSED"
    assert a["application_deadline"] == "2026-08-25"


def test_biocat_ends_field_is_deadline():
    job = {"source": "Biocat", "date": "31.08.2026", "full_detail": "Job text"}
    a = assess_availability(job, ASOF)
    assert a["application_status"] == "OPEN"
    assert a["application_deadline"] == "2026-08-31"


def test_conflicting_explicit_deadlines_surface_and_use_earliest():
    job = {
        "source": "EURAXESS",
        "full_detail": "Application Deadline 15 Sep 2026. Submission and deadline: candidates submit applications by September 3, 2026.",
    }
    a = assess_availability(job, ASOF)
    assert a["application_status"] == "OPEN"
    assert a["application_deadline"] == "2026-09-03"
    assert a["deadline_conflict"] is True


def test_open_until_filled_without_date():
    job = {"source": "Other", "full_detail": "Applications will remain open until a candidate is selected."}
    a = assess_availability(job, ASOF)
    assert a["application_status"] == "OPEN_UNTIL_FILLED"


def test_unknown_when_no_deadline_evidence():
    a = assess_availability({"source": "Other", "full_detail": "Research role in Spain."}, ASOF)
    assert a["application_status"] == "UNKNOWN"


def test_bist_closes_header_is_deadline():
    job = {"source": "BIST", "full_detail": "Barcelona Posted 1 month ago Closes: Sep 6, 2026 IBEC research role."}
    a = assess_availability(job, ASOF)
    assert a["application_status"] == "OPEN"
    assert a["application_deadline"] == "2026-09-06"
