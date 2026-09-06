from jobbot.evaluate import evaluate_job


def test_equal_opportunity_disability_does_not_create_health_domain():
    job = {
        "title": "Research Manager",
        "company": "Generic Tech",
        "location": "Madrid, Spain",
        "full_detail": (
            "Manage product research and reporting. We are an equal opportunity employer "
            "and consider applicants regardless of race, gender, age, disability status or religion."
        ),
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] != "ADJACENT"
    assert ev["recommendation"] not in {"APPLY", "STRONG_APPLY"}


def test_managing_does_not_match_aging():
    job = {
        "title": "Systems Administrator",
        "company": "Tech Co",
        "location": "Barcelona, Spain",
        "full_detail": "Five years managing Microsoft Azure and Active Directory environments.",
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "UNCLEAR"


def test_retail_lifestyle_is_not_lifestyle_health_domain():
    job = {
        "title": "Digital Analytics Engineer",
        "company": "Retail Co",
        "location": "Spain",
        "full_detail": "International retail/lifestyle company focused on ecommerce, fashion and home products.",
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "UNCLEAR"


def test_mental_health_benefit_does_not_rescue_unrelated_research_pm():
    job = {
        "title": "Research Project Manager",
        "company": "Software Co",
        "location": "Spain",
        "full_detail": (
            "Coordinate software delivery and product research. Benefits include gym membership "
            "and mental health support."
        ),
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] != "ADJACENT"
    assert ev["score"] <= 64


def test_unrelated_internship_link_in_page_does_not_zero_score_postdoc():
    job = {
        "title": "Postdoctoral Researcher – Exercise Neuroscience",
        "company": "University",
        "location": "Granada, Spain",
        "full_detail": (
            "Exercise neuroscience postdoctoral role with physical activity intervention, cognitive assessment and statistical analysis. "
            "Related jobs: IT internship; social media internship."
        ),
    }
    ev = evaluate_job(job)
    assert "internship" not in ev["blockers"]
    assert ev["recommendation"] != "SKIP"


def test_actual_internship_title_is_still_blocked():
    job = {
        "title": "Research Internship – Physical Activity Lab",
        "company": "University",
        "location": "Barcelona, Spain",
        "full_detail": "Internship supporting physical activity research.",
    }
    ev = evaluate_job(job)
    assert "internship" in ev["blockers"]
    assert ev["recommendation"] == "SKIP"


def test_computational_linguistics_title_stays_distant_even_if_page_has_health_noise():
    job = {
        "title": "Researcher in Computational Linguistics and NLP for the Humanities (R2)",
        "company": "BSC",
        "location": "Barcelona, Spain",
        "full_detail": "NLP and computational humanities. Site navigation also mentions public health and digital health projects.",
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "DISTANT"
    assert ev["recommendation"] == "SKIP"


def test_rna_decay_postdoc_is_distant_without_exercise_link():
    job = {
        "title": "Postdoc in the Dynamics of Protein Synthesis and RNA Decay Lab",
        "company": "CRG",
        "location": "Barcelona, Spain",
        "full_detail": "Molecular biology research on protein synthesis, RNA decay and cellular regulation.",
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "DISTANT"
    assert ev["recommendation"] == "SKIP"
