from jobbot.dedupe import deduplicate, fingerprint


def _job(job_id: str, query_id: str, title: str = "Researcher") -> dict:
    return {
        "source": "Hospital del Mar Research Institute",
        "title": title,
        "company": "Hospital del Mar Research Institute",
        "location": "Barcelona, Spain",
        "id": job_id,
        "url": f"https://researchmar.net/ofertes/en_detall-oferta-temporals.html?id={query_id}",
        "detail_status": "OK_HTML",
        "full_detail": f"Full job description for {job_id}. " * 50,
    }


def test_query_identity_parameter_prevents_distinct_vacancies_collapsing():
    a = _job("FIMIM-A", "3419", "Research Technician")
    b = _job("FIMIM-B", "3405", "Researcher")
    out, removed = deduplicate([a, b])
    assert len(out) == 2
    assert removed == 0
    assert fingerprint(a) != fingerprint(b)


def test_same_query_identity_still_deduplicates_cross_source_copy():
    a = _job("FIMIM-A", "3419", "Research Technician")
    b = dict(a)
    b["source"] = "Biocat"
    b["id"] = ""
    b["url"] = "https://www.researchmar.net/ofertes/en_detall-oferta-temporals.html?id=3419&utm_source=feed"
    out, removed = deduplicate([a, b])
    assert len(out) == 1
    assert removed == 1


def test_tracking_and_pagination_query_parameters_remain_ignored():
    a = {
        "source": "Example A", "title": "Research Project Manager", "company": "Institute X",
        "location": "Barcelona", "url": "https://example.org/jobs/abc?utm_source=x&page=1",
        "detail_status": "OK_HTML", "full_detail": "same validated job description " * 60,
    }
    b = dict(a)
    b["source"] = "Example B"
    b["url"] = "https://example.org/jobs/abc?utm_source=y&page=2"
    out, removed = deduplicate([a, b])
    assert len(out) == 1
    assert removed == 1
