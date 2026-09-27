from jobbot.evaluate import evaluate_job


def _job(title, detail, location="Spain"):
    return {
        "title": title,
        "full_detail": detail,
        "description": detail,
        "location": location,
        "modality": "",
    }


def test_v140_european_projects_manager_is_research_pm():
    result = evaluate_job(_job(
        "GESTOR/A DE PROYECTOS EUROPEOS",
        """
        Fundación para la Investigación Biomédica. Vigilancia estratégica e identificación
        de oportunidades, apoyo a investigadores en fase Pre-Award, preparación y presentación
        de propuestas competitivas, programas Horizonte Europa, ERC, MSCA y EU4Health,
        construcción y gestión de consorcios internacionales, seguimiento de convocatorias
        competitivas, comunicación científica y gestión de proyectos.
        """,
        "Madrid, Spain",
    ))
    assert result["job_family"] == "research_project_management"
    assert result["domain_category"] == "ADJACENT"
    assert result["score"] >= 65


def test_v140_scientific_management_technician_is_research_pm():
    result = evaluate_job(_job(
        "Técnico de Gestión Científica FIBHNJS",
        """
        Fundación para la Investigación Biomédica de un hospital infantil universitario.
        Gestión científica asociada a la Oficina de Gestión. Experiencia en gestión de proyectos,
        gestión de proyectos de investigación, búsqueda activa de convocatorias de financiación
        de investigación, gestión de proyectos públicos y privados en ámbito sanitario, e inglés B2.
        """,
        "Madrid, Spain",
    ))
    assert result["job_family"] == "research_project_management"
    assert result["domain_category"] == "ADJACENT"
    assert result["score"] >= 65


def test_v140_research_projects_coordinator_is_target_family():
    result = evaluate_job(_job(
        "2026_99_COORDINADOR/A DE PROJECTES DE RECERCA CEEISCAT",
        """
        Institut de recerca. Coordinació científica i tècnica de projectes de recerca,
        gestió d'estudis multicèntrics, seguiment de protocols, control de qualitat de dades,
        anàlisis epidemiològiques i estadístiques, informes científics, publicacions,
        reunions científiques i preparació de noves propostes de recerca competitiva.
        """,
        "Badalona, Spain",
    ))
    assert result["job_family"] == "research_project_management"
    assert result["domain_category"] in {"CORE", "ADJACENT"}


def test_v140_preaward_manager_is_research_pm_and_not_unclear():
    result = evaluate_job(_job(
        "Gestor/a Pre-Award Nacional",
        """
        Fundació de recerca. Suport als grups d'investigació en la identificació
        d'oportunitats de finançament i preparació de propostes per a convocatòries competitives.
        Assessorament als equips de recerca, revisió de pressupostos, criteris d'avaluació,
        informació institucional, seminaris per a investigadors i experiència en convocatòries
        biomèdiques ISCIII, AEI, AGAUR i PERIS.
        """,
        "Esplugues de Llobregat, Spain",
    ))
    assert result["job_family"] == "research_project_management"
    assert result["domain_category"] == "ADJACENT"
    assert result["score"] >= 65


def test_v140_strategic_research_project_manager_recovers_family():
    result = evaluate_job(_job(
        "Project Manager for the Strategic Management Office at the Directorate of Research, Innovation and Learning",
        """
        Research foundation supporting research and innovation activities in a hospital ecosystem.
        Project Manager for strategic projects in Advanced Therapies and Internationalisation.
        Planning, coordination, monitoring and reporting of projects, workplans, timelines,
        milestones and risk management. Collaboration with the Directorate of Research,
        research teams, healthcare stakeholders and international partners.
        """,
        "Barcelona, Spain",
    ))
    assert result["job_family"] == "research_project_management"
    assert result["score"] >= 50


def test_v140_generic_facilities_pm_at_research_institute_stays_out():
    result = evaluate_job(_job(
        "Project Manager",
        """
        University research institute. Responsible for office relocation, building refurbishment,
        procurement, vendor management, facilities scheduling and construction budgets.
        No responsibility for research projects, grants, scientific coordination or proposals.
        """,
        "Barcelona, Spain",
    ))
    assert result["job_family"] != "research_project_management" or result["score"] < 65


def test_v140_generic_commercial_pm_stays_out():
    result = evaluate_job(_job(
        "Project Manager",
        """
        Commercial software company. Manage ERP rollout, procurement, sales operations,
        vendor contracts, implementation budget and customer delivery milestones.
        """,
        "Barcelona, Spain",
    ))
    assert result["job_family"] != "research_project_management"
