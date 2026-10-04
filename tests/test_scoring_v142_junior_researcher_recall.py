from jobbot.evaluate import evaluate_job


def _job(title: str, detail: str, location: str = "Madrid, Spain"):
    return {"title": title, "full_detail": detail, "description": detail, "location": location, "modality": ""}


def test_v142_mixed_project_manager_junior_researcher_is_not_lost():
    result = evaluate_job(_job(
        "Project manager / Junior Researcher",
        """
        Universidad Politécnica de Madrid. Gestión de proyecto. Desarrollo de herramientas de apoyo
        a la decisión clínica, LLM, RAG y ML. Redacción de documentos y artículos científicos.
        Experiencia en proyectos de investigación relacionados con la salud, revisión sistemática,
        metodología de investigación, recopilación de datos y análisis estadístico. Colaboración con
        socios internacionales. Área: Gestión de proyectos de investigación.
        """,
    ))
    assert result["job_family"] == "research_academic"
    assert result["score"] >= 50
    assert result["recommendation"] != "SKIP"


def test_v142_plain_junior_researcher_is_research_academic():
    result = evaluate_job(_job(
        "Junior Researcher",
        "Health research project involving scientific writing, statistical analysis and international collaboration.",
    ))
    assert result["job_family"] == "research_academic"


def test_v142_market_researcher_is_not_promoted_by_junior_researcher_pattern():
    result = evaluate_job(_job(
        "Market Researcher",
        "Consumer market research, commercial insights, customer segmentation and marketing operations.",
    ))
    assert result["job_family"] != "research_academic"
