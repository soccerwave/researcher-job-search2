from jobbot.evaluate import evaluate_job


def _job(title, detail, location="Valencia, Spain"):
    return {
        "title": title,
        "company": "Public Health Research Foundation",
        "location": location,
        "full_detail": detail,
        "description": detail,
    }


def test_spanish_research_management_title_maps_to_target_family():
    detail = """
    Fundación de investigación sanitaria. El puesto participa en la gestión técnica de planes,
    proyectos y programas de investigación, elaboración de informes y apoyo a investigadores.
    Titulación universitaria de Grado. Experiencia en gestión de proyectos se valorará como mérito.
    """
    out = evaluate_job(_job("Técnico/a de Gestión de la Investigación (M3)", detail))
    assert out["job_family"] == "research_project_management"


def test_eu_research_management_merit_without_minimum_is_surfaced_for_review():
    detail = """
    Fundación de salud pública e investigación sanitaria y biomédica. Gestión integral de proyectos internacionales de investigación
    financiados por programas europeos desde la firma del Grant Agreement hasta el cierre administrativo,
    financiero y contractual. Preparación de informes financieros, entregables, auditorías y coordinación
    con investigadores y entidades financiadoras. Requisitos Necesarios: Titulación: Título de Grado,
    Diplomado o equivalente. Valoración de Méritos: experiencia profesional en gestión administrativo-financiera
    de proyectos europeos de I+D+i y formación en programas de financiación europeos. No existe criterio de
    suficiencia ni experiencia mínima obligatoria.
    """
    out = evaluate_job(_job("Técnico/a de Gestión de la Investigación", detail))
    assert out["job_family"] == "research_project_management"
    assert not any("research_project_management_sufficiency_experience" in x for x in out["missing_requirements"])
    # It should be surfaced, but a finance-heavy post-award role need not reach REVIEW
    # when direct grant-office financial experience is not evidenced in the profile.
    assert out["score"] >= 50
    assert out["recommendation"] in {"LOW_PRIORITY", "REVIEW", "APPLY", "STRONG_APPLY"}


def test_explicit_research_project_management_sufficiency_threshold_caps_role():
    detail = """
    Fundación de investigación sanitaria. Funciones de gestión técnica de proyectos de I+D+i, justificaciones,
    apoyo a investigadores y seguimiento económico. Requisitos Necesarios: Titulación universitaria de Grado.
    Méritos Valorables: A1 Experiencia previa acreditada en el departamento de gestión de proyectos I+D+i,
    1,5 puntos por mes trabajado en fundaciones de investigación. CRITERIO DE SUFICIENCIA: 30 puntos
    (Mínimo 9 puntos), acreditado mediante Curriculum vitae, no subsanable.
    """
    out = evaluate_job(_job("Técnico/a de Gestión de la Investigación", detail))
    assert out["job_family"] == "research_project_management"
    assert any("research_project_management_sufficiency_experience" in x for x in out["missing_requirements"])
    assert out["score"] <= 49
    assert out["recommendation"] == "SKIP"


def test_spanish_mandatory_nursing_degree_is_hard_blocker():
    detail = """
    Unidad de investigación clínica. REQUISITOS PARA PARTICIPAR EN LA CONVOCATORIA.
    3.2 Requisitos Necesarios: Titulación: Título de Grado, Diplomado o equivalentes (MECES 2, EQF6)
    en Enfermería. Funciones: visitas de ensayos clínicos, ECG, extracción de muestras y administración
    de productos en investigación.
    """
    out = evaluate_job(_job("Enfermero/a de Investigación", detail))
    assert out["score"] == 0
    assert out["recommendation"] == "SKIP"
    assert "mandatory_nursing" in out["blockers"]
