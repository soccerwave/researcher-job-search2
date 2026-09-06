from jobbot.evaluate import evaluate_job


def _job(title, detail, location="Valencia, Spain"):
    return {
        "title": title,
        "company": "Public Research Foundation",
        "location": location,
        "full_detail": detail,
        "description": detail,
    }


def test_spanish_research_management_grade_that_is_really_science_communication_is_skip():
    detail = """
    Fundación de investigación sanitaria. Área de Comunicación y Difusión de la Ciencia.
    Funciones: desarrollar la estrategia de comunicación científica, gestionar relaciones con los medios,
    preparar campañas y contenidos para redes sociales y organizar eventos divulgativos.
    Se valorará formación y experiencia en Periodismo, Comunicación Audiovisual, Publicidad y Relaciones Públicas.
    """
    out = evaluate_job(_job("Técnico/a de gestión de la investigación (M3) - Área de Comunicación y Difusión de la Ciencia", detail))
    assert out["job_family"] == "unclear"
    assert out["score"] <= 49
    assert out["recommendation"] == "SKIP"
    assert any("science communication" in x for x in out["missing_requirements"])


def test_genuine_research_project_manager_with_dissem_task_is_not_demoted_to_communication_specialist():
    detail = """
    Health research institute. Manage Horizon Europe research projects, monitor work packages, deliverables,
    budgets and reporting, coordinate consortium partners and funding-agency communication. The role also
    supports dissemination of project results and one annual scientific event.
    """
    out = evaluate_job(_job("European Research Project Manager", detail))
    assert out["job_family"] == "research_project_management"
    assert not any("science communication" in x for x in out["missing_requirements"])


def test_mandatory_spanish_fp_grado_superior_credential_is_explicit_fit_gap():
    detail = """
    Área de Investigación Clínica. Requisitos Necesarios: Titulación: Título de Formación Profesional
    de Grado Superior o equivalente MECES 1 / EQF 5. Funciones: apoyo técnico a la gestión de estudios,
    archivo de documentación y soporte operativo del área de investigación clínica.
    """
    out = evaluate_job(_job("Ayudante técnico de gestión de la investigación (M2) - Área de Investigación Clínica", detail))
    assert any("mandatory_specific_vocational_qualification" in x for x in out["missing_requirements"])
    assert out["score"] <= 49
    assert out["recommendation"] == "SKIP"


def test_optional_or_merit_fp_training_does_not_trigger_mandatory_qualification_gap():
    detail = """
    Fundación de investigación. Requisitos Necesarios: Titulación universitaria de Grado.
    Méritos valorables: formación profesional de grado superior relacionada con gestión administrativa,
    experiencia en proyectos europeos y cursos de gestión de proyectos.
    """
    out = evaluate_job(_job("Técnico/a de Gestión de la Investigación", detail))
    assert not any("mandatory_specific_vocational_qualification" in x for x in out["missing_requirements"])
