from datetime import date

from jobbot.availability import assess_availability
from jobbot.evaluate import evaluate_job
from sources.madrid_idi import _external_detail_matches_job, _api_has_substantive_detail


def test_madrid_external_generic_group_page_is_not_full_jd():
    job = {
        "title": "Doctor/a investigador/a en técnicas de inmunodetección",
        "company": "INARI BIOTECH",
        "poem_reference": "",
    }
    generic = (
        "INARI BIOTECH Servicios Bioinformática Bioestadística Ciencia de datos. "
        "Nuestra misión es impulsar la investigación biomédica. Contacto, equipo, servicios, publicaciones. "
    ) * 12
    assert _external_detail_matches_job(job, generic, "https://example.org/") is False


def test_madrid_external_specific_generic_title_can_pass_with_vacancy_structure():
    job = {
        "title": "IT Project Manager - Research support 2026",
        "company": "IMDEA Networks",
        "poem_reference": "IT Project Manager - Research support",
    }
    detail = (
        "IMDEA Networks IT Project Manager. Deadline August 30 2026. Responsibilities include leading IT infrastructure migration. "
        "Requirements: experience with Kubernetes and private cloud. How to apply: submit your application online. "
        "Contract type full time. Salary according to experience."
    )
    assert _external_detail_matches_job(job, detail, "https://example.org/job/it-project-manager") is True


def test_poem_structured_fields_can_rescue_external_mismatch():
    data = {
        "dsPuesto": "Investigador contratado",
        "dsFunciones": "Diseño y ejecución de experimentos con participantes humanos y análisis estadístico de resultados.",
        "dsRequisitos": "Doctorado y experiencia previa en investigación aplicada y coordinación de proyectos.",
        "dsEmpresa": "Universidad X",
    }
    rendered = "Functions: " + data["dsFunciones"] + "\nRequirements: " + data["dsRequisitos"]
    assert _api_has_substantive_detail(data, rendered) is True


def test_spanish_fecha_fin_inscripcion_closes_expired_role():
    job = {
        "source": "Madrid I+D+i",
        "source_listing_active": True,
        "full_detail": "Fecha fin de inscripción: 15/07/2026",
    }
    out = assess_availability(job, as_of=date(2026, 8, 27))
    assert out["application_status"] == "CLOSED"
    assert out["application_deadline"] == "2026-07-15"


def test_spanish_fin_plazo_with_weekday_and_month_name():
    job = {
        "source": "Madrid I+D+i",
        "source_listing_active": True,
        "full_detail": "Fin del plazo de presentación de solicitudes: Domingo, 9 Agosto, 2026",
    }
    out = assess_availability(job, as_of=date(2026, 8, 27))
    assert out["application_status"] == "CLOSED"
    assert out["application_deadline"] == "2026-08-09"


def test_spanish_application_window_end_is_deadline():
    job = {
        "source": "Madrid I+D+i",
        "source_listing_active": True,
        "full_detail": "Plazo de solicitud del 20/07/2026 al 31/07/2026",
    }
    out = assess_availability(job, as_of=date(2026, 8, 27))
    assert out["application_status"] == "CLOSED"
    assert out["application_deadline"] == "2026-07-31"


def test_explicit_closed_status_beats_madrid_active_listing_fallback():
    job = {
        "source": "Madrid I+D+i",
        "source_listing_active": True,
        "full_detail": "Estado Plazo de solicitud cerrado",
    }
    out = assess_availability(job, as_of=date(2026, 8, 27))
    assert out["application_status"] == "CLOSED"


def test_it_project_manager_in_research_institute_is_distant_skip():
    job = {
        "title": "IT Project Manager - Research Support",
        "company": "Research Institute",
        "location": "Madrid, Spain",
        "full_detail": (
            "Lead strategic adoption of AI tools and AIOps across research and administrative operations. "
            "Migrate legacy services to Kubernetes and private cloud infrastructure, manage vendors and IT services."
        ),
    }
    out = evaluate_job(job)
    assert out["domain_category"] == "DISTANT"
    assert out["recommendation"] == "SKIP"
    assert out["score"] <= 49


def test_telecom_networks_researcher_is_distant_skip():
    job = {
        "title": "Investigador Senior en Redes de Comunicaciones y Sistemas Inteligentes",
        "company": "R&D Company",
        "location": "Madrid, Spain",
        "full_detail": (
            "Doctorado en Informática, Matemáticas o Telecomunicaciones. Desarrollo de software científico, "
            "simulación, gemelos digitales, Python, MATLAB y tecnologías de comunicaciones."
        ),
    }
    out = evaluate_job(job)
    assert out["domain_category"] == "DISTANT"
    assert out["recommendation"] == "SKIP"


def test_generic_host_search_for_external_fellowship_is_blocked():
    job = {
        "title": "Call for applications: Postdoctoral Candidate in Sleep Medicine",
        "company": "Research Institute",
        "location": "Spain",
        "full_detail": (
            "We are seeking a highly motivated postdoctoral candidate who is eligible to apply for the Junior Leader Fellowship. "
            "The selected candidate will co-develop a research project with the host group."
        ),
    }
    out = evaluate_job(job)
    assert out["recommendation"] == "SKIP"
    assert "fellowship_hosting_call" in out["blockers"]


def test_real_health_research_project_manager_is_not_it_override():
    job = {
        "title": "Scientific Project Manager",
        "company": "Health Research Institute",
        "location": "Madrid, Spain",
        "full_detail": (
            "Coordinate a Horizon Europe clinical research project in mental health. Manage consortium partners, "
            "deliverables, milestones and proposal preparation. PhD desirable."
        ),
    }
    out = evaluate_job(job)
    assert out["domain_category"] == "ADJACENT"
    assert out["job_family"] == "research_project_management"
    assert out["recommendation"] in {"REVIEW", "APPLY", "STRONG_APPLY"}
