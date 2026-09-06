from datetime import date

from jobbot.availability import assess_availability
from jobbot.dedupe import deduplicate

ASOF = date(2026, 8, 27)


def _job(jid, url, detail):
    return {
        "source": "Madrid I+D+i",
        "id": str(jid),
        "title": "Research Project Manager",
        "company": "Example Research Foundation",
        "location": "Madrid, Spain",
        "url": url,
        "full_detail": detail,
        "detail_status": "OK_HTML",
    }


def test_same_source_distinct_stable_ids_do_not_fuzzy_merge():
    shared = ("research project manager european consortium reporting deliverables " * 40)
    a = _job(1001, "https://portal/#/ver-oferta/1001", shared + " position alpha")
    b = _job(1002, "https://portal/#/ver-oferta/1002", shared + " position beta")
    out, removed = deduplicate([a, b])
    assert removed == 0
    assert len(out) == 2


def test_same_source_same_url_still_merges_even_if_ids_differ():
    # Exact canonical URL remains the strongest identity signal.
    shared = "same validated vacancy text " * 50
    a = _job(1001, "https://example.org/job/one", shared)
    b = _job(1002, "https://example.org/job/one?utm_source=x", shared)
    out, removed = deduplicate([a, b])
    assert removed == 1
    assert len(out) == 1


def test_madrid_poem_publication_end_is_not_application_deadline():
    job = {
        "source": "Madrid I+D+i",
        "full_detail": "Rich external employer job description without a closing date.",
        "poem_publication_end": "2026-08-30T22:00:00.000+00:00",
        "source_listing_active": True,
    }
    a = assess_availability(job, ASOF)
    assert a["application_status"] == "OPEN"
    assert a["application_deadline"] == ""
    assert a["deadline_conflict"] is False
    assert "active offers" in a["deadline_evidence"]


def test_madrid_explicit_employer_deadline_outranks_active_listing_signal():
    job = {
        "source": "Madrid I+D+i",
        "full_detail": "Application deadline: 30/08/2026",
        "poem_publication_end": "2026-08-30T22:00:00.000+00:00",
        "source_listing_active": True,
    }
    a = assess_availability(job, ASOF)
    assert a["application_deadline"] == "2026-08-30"
    assert a["deadline_conflict"] is False
    assert a["application_status"] == "OPEN"


def test_madrid_past_explicit_deadline_closes_even_if_portal_still_lists_active():
    job = {
        "source": "Madrid I+D+i",
        "full_detail": "Application deadline: 25/08/2026",
        "source_listing_active": True,
    }
    a = assess_availability(job, ASOF)
    assert a["application_status"] == "CLOSED"
    assert a["application_deadline"] == "2026-08-25"
