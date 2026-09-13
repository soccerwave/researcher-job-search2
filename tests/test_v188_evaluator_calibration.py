from jobbot.evaluate import evaluate_job


def job(title: str, detail: str, location: str = "Barcelona, Spain"):
    return {"title": title, "full_detail": detail, "location": location}


def test_distant_research_pm_is_not_hard_blocked():
    result = evaluate_job(job(
        "European Research Project Manager - Drug Discovery",
        """
        Coordinate a Horizon Europe research consortium in drug discovery.
        Manage work packages, milestones, deliverables, risks, European Commission
        reporting, grant documentation, consortium meetings and proposal preparation.
        PhD valued.
        """,
    ))
    assert result["job_family"] == "research_project_management"
    assert not result["blockers"]
    assert 50 <= result["score"] <= 69


def test_research_data_family_recognises_birth_cohort_role():
    result = evaluate_job(job(
        "Data manager and data analyst for the Barcelona Life Study birth cohort",
        """
        Public health birth cohort studying child health and development.
        Responsibilities include data cleaning, data quality control, statistical data
        analysis, questionnaire datasets, database preparation and support for scientific
        papers. Research experience and a degree in biology, public health, psychology
        or data analysis are relevant.
        """,
    ))
    assert result["job_family"] == "research_data"
    assert 58 <= result["score"] <= 74
    assert result["recommendation"] in {"LOW_PRIORITY", "REVIEW"}


def test_project_context_ai_does_not_create_candidate_specialist_gap():
    result = evaluate_job(job(
        "Research Project Officer",
        """
        Coordinate a European research project on computer vision, deep learning,
        Python-based medical image analysis and computational pathology.
        Duties are project coordination, milestones, deliverables, risk tracking,
        consortium meetings, reporting and research data governance.
        """,
    ))
    assert result["job_family"] == "research_project_management"
    assert not any("computational_ai_specialist" in x for x in result["missing_requirements"])
    assert result["score"] >= 50


def test_candidate_level_ai_requirement_still_penalised():
    result = evaluate_job(job(
        "Research Project Officer",
        """
        European medical imaging project. Required: demonstrated expertise in deep
        learning, Python and medical image analysis. The candidate will develop and
        implement computer vision models in PyTorch in addition to project reporting.
        """,
    ))
    assert any("computational_ai_specialist" in x for x in result["missing_requirements"])
    assert result["score"] <= 49


def test_mandatory_redcap_experience_caps_research_data_role():
    result = evaluate_job(job(
        "Research Data Manager",
        """
        Clinical research data management role. Minimum 3 years of experience in REDCap
        database development is required. Responsibilities include database design, data
        cleaning, quality assurance, statistical analysis and supporting research teams.
        """,
    ))
    assert result["job_family"] == "research_data"
    assert any("mandatory_role_defining_specialist_experience" in x for x in result["missing_requirements"])
    assert result["score"] <= 59


def test_immunodetection_researcher_stays_below_review():
    result = evaluate_job(job(
        "Researcher in Immunodetection Techniques",
        """
        The researcher will perform Western blot, ELISA, immunohistochemistry,
        immunofluorescence, flow cytometry and immunoprecipitation in a biomedical
        laboratory and analyse experimental samples.
        """,
    ))
    assert any("immunodetection_wet_lab" in x for x in result["missing_requirements"])
    assert result["score"] < 65


def test_climate_specialist_requirement_caps_score():
    result = evaluate_job(job(
        "Technical Researcher in Climate-and-Health",
        """
        Public health project requiring experience handling and validating large climate
        model datasets, post-processing sub-seasonal and seasonal forecasts and statistical
        downscaling. Scientific programming in R is required. The researcher will tailor
        climate information for epidemiological indicators.
        """,
    ))
    assert any("mandatory_role_defining_specialist_experience" in x for x in result["missing_requirements"])
    assert result["score"] <= 59


def test_required_psychology_degree_is_eligibility_level_gap():
    result = evaluate_job(job(
        "Research Technician - Clinical Neuropsychology",
        """
        Essential: degree in Psychology required. Minimum two years of experience in
        neuropsychological testing and cognitive assessment. Duties include administering
        validated neuropsychological tests to study participants.
        """,
    ))
    assert any("mandatory_specific_academic_qualification" in x for x in result["missing_requirements"])
    assert result["score"] <= 49


def test_unrelated_specialist_postdoc_does_not_leak_into_review():
    result = evaluate_job(job(
        "Postdoctoral Researcher in Protein Engineering",
        """
        Develop protein engineering and molecular biology experiments including cell
        culture, cloning and biochemical assays. PhD required.
        """,
    ))
    assert result["score"] < 65

# V1.89 import smoke trigger


def test_v189_madrid_history_cache_smoke(tmp_path):
    import csv, gzip
    from datetime import date
    from sources import madrid_idi_history as h
    p = tmp_path / "h.csv.gz"
    row = {"source":"Madrid I+D+i","id":"123","url":"offer-123","title":"Project manager",
           "company":"Institute","availability_as_of":"2026-09-12","detail_status":"OK",
           "full_detail":"requirements functions project management " * 30}
    with gzip.open(p, "wt", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row)); w.writeheader(); w.writerow(row)
    cache, diag = h._load_cache(p, as_of=date(2026, 9, 13))
    assert ("id", "123") in cache and diag["historical_detail_cache_eligible"] == 1
    current = {"id":"123","title":"Project manager","company":"Institute"}
    assert h._match_current_to_history(current, cache) is not None
    assert h._match_current_to_history({**current, "title":"Different role"}, cache) is None

# V1.89 diagnostics consistency smoke trigger
