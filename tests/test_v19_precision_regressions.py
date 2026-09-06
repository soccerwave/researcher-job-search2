from jobbot.evaluate import evaluate_job


def _job(title, detail, location="Spain"):
    return {"title": title, "full_detail": detail, "location": location, "modality": ""}


def test_child_adolescent_psychiatry_project_manager_is_primary_review_not_skip():
    detail = """
    Research Field Psychological sciences Psychology. Horizon Europe project MINDSET.
    Line of research: Psychotic and affective disorders in children and adolescents.
    Project Manager responsibilities include scientific-technical justifications, work-plan monitoring,
    communication with consortium partners and funding agencies, financial reporting, project meetings,
    scientific manuscripts, and stakeholder coordination. PhD valued. At least B2 Spanish and English.
    """
    out = evaluate_job(_job("Project Manager (G3) at the Child and Adolescent Psychiatry and Psychology group", detail))
    assert out["domain_category"] == "ADJACENT"
    assert out["job_family"] == "research_project_management"
    assert out["recommendation"] == "REVIEW"
    assert out["score"] >= 65


def test_nuclear_postdoc_stays_out_despite_generic_public_health_footer():
    detail = """
    Postdoctoral researcher in nuclear reactor physics and Small Modular Reactors.
    PhD in Nuclear Engineering required. Modelling, neutronics and thermal-hydraulics.
    Contract includes benefits of the Spanish Public Health and Social Security System.
    """
    out = evaluate_job(_job("Postdoctoral Researcher in Small Modular Reactors", detail))
    assert out["recommendation"] == "SKIP"
    assert out["score"] <= 49



def test_spanish_wastewater_membrane_postdoc_is_distant_skip():
    detail = """
    Personal investigador postdoctoral para tratamiento de aguas residuales mediante tecnologia de membranas.
    Doctor en química o ingeniería química. Experiencia en tratamiento de aguas residuales a escala piloto.
    """
    out = evaluate_job(_job("Personal Investigador postdoctoral: Implementación de tecnología de membranas para el tratamiento de aguas residuales", detail))
    assert out["recommendation"] == "SKIP"
    assert out["domain_category"] == "DISTANT"


def test_immune_cell_wet_lab_role_is_not_low_priority_false_positive():
    detail = """
    Research role studying immunomodulatory drugs and innate immune system. Processing biological samples including serum and Ficoll,
    cell culture, generation of macrophages from monocytes, and multiparametric flow cytometry are central duties.
    """
    out = evaluate_job(_job("Investigador/a 93_2026", detail))
    assert out["recommendation"] == "SKIP"
    assert out["score"] <= 49


def test_research_manager_that_is_really_science_communications_is_skip():
    detail = """
    Research Field Communication sciences. The role coordinates communications for research centres and manages media and digital channels.
    Required training and experience in R&D&I communication, science communication, institutional communication and corporate communication.
    Bachelor's degree in Advertising and Public Relations, Audiovisual Communication, Journalism, Communication or related degree.
    """
    out = evaluate_job(_job("Research Manager 2026/CP/227", detail))
    assert out["recommendation"] == "SKIP"
    assert out["score"] <= 49
    assert out["job_family"] == "unclear"
