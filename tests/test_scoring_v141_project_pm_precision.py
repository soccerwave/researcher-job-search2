import pytest

from jobbot.evaluate import evaluate_job


def _job(title: str, detail: str, location: str = "Barcelona, Spain"):
    return {"title": title, "full_detail": detail, "description": detail, "location": location, "modality": ""}


POSITIVE_RESEARCH_PM_CASES = [
    (
        "GESTOR/A DE PROYECTOS EUROPEOS",
        "Fundación para la Investigación Biomédica. Pre-Award, convocatorias competitivas, Horizonte Europa, ERC, MSCA, EU4Health, consorcios internacionales, preparación de propuestas de financiación y gestión de proyectos de investigación.",
    ),
    (
        "Técnico de Gestión Científica FIBHNJS",
        "Fundación para la Investigación Biomédica. Gestión científica, gestión de proyectos de investigación, convocatorias de financiación, proyectos públicos y privados en ámbito sanitario.",
    ),
    (
        "2026_99_COORDINADOR/A DE PROJECTES DE RECERCA CEEISCAT",
        "Institut de recerca. Coordinació científica i tècnica de projectes de recerca, estudis multicèntrics, informes científics i preparació de propostes de recerca competitiva.",
    ),
    (
        "Gestor/a Pre-Award Nacional",
        "Fundació de recerca. Suport a grups d'investigació, oportunitats de finançament, convocatòries competitives ISCIII i preparació de propostes.",
    ),
    (
        "Técnico/a de Gestión de Investigación Ref. 11-2026",
        "Instituto de investigación. Gestión y coordinación de proyectos, convocatorias internas de ayudas, acreditaciones CERCA e ISCIII, informes, memorias y coordinación científica.",
    ),
]


@pytest.mark.parametrize("title,detail", POSITIVE_RESEARCH_PM_CASES)
def test_v141_preserves_research_pm_recall(title, detail):
    result = evaluate_job(_job(title, detail))
    assert result["job_family"] == "research_project_management"
    assert not any("rather than research project management" in x for x in result["missing_requirements"])


def _assert_not_reviewed_as_research_pm(result):
    assert result["recommendation"] == "SKIP"
    assert result["score"] < 50
    assert result["job_family"] != "research_project_management"


def test_v141_evonik_industrial_rd_project_manager_stays_out():
    result = evaluate_job(_job(
        "Project Manager",
        """
        Chemical manufacturing company. University degree in Chemistry or Chemical Engineering.
        Strong background in project management, preferably in a research and development setting.
        Manage timelines, budgets and deliverables. Coordinate Applied Innovation, production,
        engineering and manufacturing. Profound knowledge of lab and production scale equipment.
        """,
    ))
    _assert_not_reviewed_as_research_pm(result)


def test_v141_healthcare_presales_software_pm_stays_out():
    result = evaluate_job(_job(
        "Healthcare Presales & Project Manager (m/f/d)",
        """
        Titulación universitaria. Gestión y consultoría de proyectos complejos de software sanitario.
        Preventa en sector público, preparación de propuestas, ofertas y documentación RFP/RFI,
        desarrollo de software e implantación de servicios tecnológicos, stakeholders y clientes.
        """,
        "Seville, Spain",
    ))
    _assert_not_reviewed_as_research_pm(result)


def test_v141_generic_it_pm_stays_out():
    result = evaluate_job(_job(
        "IT Project Manager",
        "Lead cloud software implementation, enterprise-system rollout and deployment for clients; manage vendors, service delivery, budgets and customer onboarding.",
    ))
    _assert_not_reviewed_as_research_pm(result)


def test_v141_facilities_construction_pm_at_research_institute_stays_out():
    result = evaluate_job(_job(
        "Project Manager",
        "University research institute. Responsible for facilities, office relocation, building refurbishment, construction budgets, procurement, vendor management and facilities scheduling.",
    ))
    _assert_not_reviewed_as_research_pm(result)


def test_v141_sales_customer_implementation_pm_stays_out():
    result = evaluate_job(_job(
        "Project Manager",
        "Healthcare technology company. Sales support, customer demos, client onboarding, software implementation, deployment, service delivery and customer satisfaction.",
    ))
    _assert_not_reviewed_as_research_pm(result)


def test_v141_generic_title_with_real_horizon_research_duties_is_preserved():
    result = evaluate_job(_job(
        "Project Manager",
        """
        University research centre. Coordinate a Horizon Europe research consortium, work packages,
        European Commission reporting, scientific coordination, funding proposals, milestones and
        consortium partners. Also manage procurement and external vendors for project activities.
        """,
    ))
    assert result["job_family"] == "research_project_management"
    assert result["score"] >= 50



def test_v141_research_funding_role_preserves_review_recall():
    result = evaluate_job(_job(
        "Técnico/a en Captación y Gestión de Fondos para Ciencia de Datos Clínica en I+D+I -2477",
        """
        Apoyo a proyectos de I+D+i, servicios científico-técnicos y grupos de investigación.
        Gestión de proyectos de I+D+i. Preparación de propuestas para convocatorias de financiación
        nacional e internacional, consorcios internacionales de I+D+i en salud, memorias técnicas
        y económicas, coordinación científica, entregables técnicos y financieros y comités científicos.
        """,
        "Sevilla, Spain",
    ))
    assert result["job_family"] == "research_project_management"
    assert result["domain_category"] == "ADJACENT"
    assert result["score"] >= 65
    assert result["recommendation"] in {"REVIEW", "APPLY", "STRONG_APPLY"}


def test_v141_pmo_technology_trainee_with_university_agreement_stays_out():
    result = evaluate_job(_job(
        "Project Manager (PMO) Trainee",
        """
        Pharmaceutical manufacturing company. Soporte en planificación, coordinación y supervisión
        de proyectos tecnológicos hasta su entrega final, puente entre equipos técnicos y departamentos
        de negocio, cronogramas, presupuestos y satisfacción del cliente interno o externo.
        Posibilidad de realizar un convenio con tu universidad.
        """,
        "Madrid, Spain",
    ))
    _assert_not_reviewed_as_research_pm(result)
