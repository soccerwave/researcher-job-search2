import sources.euraxess as euraxess


def test_generic_postdoc_card_survives_without_exact_query_phrase():
    job = {
        "title": "Postdoctoral Researcher",
        "company": "University X",
        "location": "Spain",
        "description": "JOB Spain University X Research Field: Medical sciences",
        "url": "https://euraxess.ec.europa.eu/jobs/1",
    }
    keep, reasons = euraxess._card_candidate(job)
    assert keep
    assert "target_or_transferable_role_title" in reasons


def test_distant_generic_researcher_is_rejected_early():
    job = {
        "title": "Researcher in Quantum Materials",
        "company": "University X",
        "location": "Spain",
        "description": "Quantum materials and condensed matter physics",
        "url": "https://euraxess.ec.europa.eu/jobs/2",
    }
    keep, reasons = euraxess._card_candidate(job)
    assert not keep
    assert "obvious_distant_title" in reasons


def test_domain_card_with_research_role_is_candidate():
    job = {
        "title": "Research Project Officer",
        "company": "Institute X",
        "location": "Spain",
        "description": "Public health and behavioural change programme",
        "url": "https://euraxess.ec.europa.eu/jobs/3",
    }
    keep, reasons = euraxess._card_candidate(job)
    assert keep
    assert "target_or_adjacent_domain_on_card" in reasons


def test_phd_student_position_is_not_targeted():
    job = {
        "title": "PhD Position in Physical Activity and Health",
        "company": "University X",
        "location": "Spain",
        "description": "Physical activity research",
        "url": "https://euraxess.ec.europa.eu/jobs/4",
    }
    keep, reasons = euraxess._card_candidate(job)
    assert not keep
    assert "doctoral_student_position" in reasons
