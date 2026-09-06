from jobbot.evaluate import evaluate_job


def _job(title, detail, location="Barcelona, Spain"):
    return {"title": title, "full_detail": detail, "description": detail, "location": location, "modality": "Hybrid"}


def test_post_award_international_projects_is_target_research_pm_family():
    detail = """
    Join the International Projects Management team and support European and international
    health and mental-health research and innovation projects funded by Horizon Europe and EU4Health. Liaise with
    funding institutions, support Grant Agreement negotiation, coordinate with Principal
    Investigators and project teams, support budget monitoring, reporting and consortium
    agreements. University degree in a related field. Strong interest in EU-funded research
    project management. Previous project-management or health-sector experience is valued.
    Professional working English; working languages Spanish and Catalan.
    """
    out = evaluate_job(_job("Post-Award Officer – European & International Projects", detail))
    assert out["job_family"] == "research_project_management"
    assert out["score"] >= 65
    assert out["recommendation"] == "REVIEW"


def test_specialist_three_year_grant_finance_still_stays_out_of_primary_queue():
    detail = """
    Research grants and post-award financial management role. Minimum 3 years of experience
    in economic and administrative management of research grants and fellowships is required.
    Responsibilities include budgets, financial justifications, audits and funder rules.
    """
    out = evaluate_job(_job("Post-Award Grants Officer", detail))
    assert out["job_family"] == "research_project_management"
    assert out["score"] <= 49
    assert out["recommendation"] == "SKIP"


def test_specialist_preaward_support_and_budget_expertise_is_not_equated_with_pi_grant_writing():
    detail = """
    Biomedical research institute pre-award grants role. Proven experience supporting researchers
    in preparing applications for local, national and international funding programmes is required.
    Expertise in budget preparation for research grant applications is required. The role also
    covers grant agreement negotiation and regulatory requirements. PhD in a scientific field.
    """
    out = evaluate_job(_job("Pre-Award Grants Officer", detail))
    assert out["job_family"] == "research_project_management"
    assert out["score"] <= 49
    assert out["recommendation"] == "SKIP"
    assert any("preaward_grant_operations_experience" in x for x in out["missing_requirements"])
