from jobbot.evaluate import evaluate_job


def _job(title, detail, location="Spain"):
    return {"title": title, "full_detail": detail, "location": location, "modality": ""}


def test_mandatory_prior_regulated_trial_operations_is_a_practical_skip():
    out = evaluate_job(_job(
        "Study Coordinator for Cancer Clinical Trials",
        """
        Health research role coordinating oncology clinical trials. Job requirements – Professional experience:
        At minimum 6 months of experience in oncology or hematology cancer clinical trials as coordinator or data entry.
        Coordination or data entry in phase I, II and III cancer trials. Communication with Sponsors and CROs.
        SAE completion, Case Report Forms, monitoring visits, audits and inspections. Bachelor degree in Life Sciences.
        """,
    ))
    assert out["job_family"] == "clinical_human_research"
    assert out["recommendation"] == "SKIP"
    assert out["score"] <= 49
    assert any("regulated_clinical_trial_operations_experience" in x for x in out["missing_requirements"])


def test_generic_academic_rct_does_not_trigger_regulated_trial_gap():
    out = evaluate_job(_job(
        "Research Coordinator – Physical Activity Trial",
        """
        Coordinate a randomized controlled trial of a physical activity intervention in adults.
        Recruit participants, schedule assessments, manage research data, prepare manuscripts and work with an international consortium.
        Experience coordinating research studies is valued. PhD in health sciences preferred.
        """,
    ))
    assert not any("regulated_clinical_trial_operations_experience" in x for x in out["missing_requirements"])
    assert out["recommendation"] != "SKIP" or out["score"] > 0


def test_clinical_trial_support_role_without_explicit_minimum_experience_is_not_blocked():
    out = evaluate_job(_job(
        "Superior Research Technician",
        """
        Health sciences. Support coordination of a randomized clinical trial, patient follow-up and visits.
        Manage eCRFs and study documentation and support monitoring. Experience supporting clinical trials or research studies will be valued.
        Bachelor's degree in Health Sciences. High Catalan and Spanish requested.
        """,
    ))
    assert out["job_family"] == "clinical_human_research"
    assert not any("regulated_clinical_trial_operations_experience" in x for x in out["missing_requirements"])


def test_opaque_public_research_call_with_adjacent_domain_signal_reaches_full_jd_gate():
    import sources.euraxess as euraxess
    keep, reasons = euraxess._card_candidate({
        "title": "2026/120: 1 T4A ICI 22 ISCIII",
        "description": "Movement Disorders Unit, Neurology. Clinical research in Parkinson disease.",
        "location": "Spain",
    })
    assert keep
    assert "target_or_adjacent_domain_on_card" in reasons
    assert "opaque_research_call_with_domain_signal" in reasons


def test_domain_word_does_not_rescue_descriptive_distant_engineer_title():
    import sources.euraxess as euraxess
    keep, reasons = euraxess._card_candidate({
        "title": "Engineer specializing in cognitive AI, autonomous agents and human interaction",
        "description": "Cognitive research and artificial intelligence engineering",
        "location": "Spain",
    })
    assert not keep
