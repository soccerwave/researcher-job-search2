from datetime import date

from jobbot.availability import assess_availability
from jobbot.evaluate import evaluate_job
from sources.institutions import _trim_teamtailor_boilerplate, parse_teamtailor_jobs


def _job(title, detail, location="Barcelona, Spain"):
    return {"title": title, "full_detail": detail, "location": location, "modality": ""}


def test_long_distance_exercise_word_does_not_create_exercise_neuroscience_core_match():
    out = evaluate_job(_job(
        "Study Coordinator in Neurodegenerative Diseases",
        "Neuroscience and Parkinson disease clinical research. Applicants may exercise their data-protection rights. The institute has a Brain, Mind and Behaviour research area. Experience in clinical trials is required.",
    ))
    assert out["domain_category"] != "CORE"


def test_solaris_project_name_does_not_match_solar_energy_domain():
    out = evaluate_job(_job(
        "Senior Postdoctoral Researcher – Advanced Therapies Platform",
        "The SOLARIS project develops Advanced Therapy Medicinal Products (ATMPs). Demonstrated expertise in gene therapy, gene editing and cell therapy. GMP and CRISPR experience. PhD required.",
    ))
    assert "energy" not in " ".join(out["partial_matches"])
    assert out["score"] <= 49
    assert any("advanced_therapies_atmp" in x for x in out["missing_requirements"])


def test_molecular_modelling_postdoc_is_specialist_skip():
    out = evaluate_job(_job(
        "Postdoctoral Fellow",
        "PhD required. Molecular modelling and molecular dynamics simulations using AMBER and GROMACS in Linux high-performance computing environments. Python and Bash scientific programming. Structural bioinformatics and deep learning.",
    ))
    assert out["recommendation"] == "SKIP"
    assert any("molecular_modelling_computational_biology" in x for x in out["missing_requirements"])


def test_genomic_bioinformatics_role_is_specialist_skip_despite_mental_health_domain():
    out = evaluate_job(_job(
        "Investigador/a en Psicosi i Biomarcadors Genòmics",
        "Salud mental. Experiencia en analisis bioinformatico de datos genomicos, integracion de datos genomicos y clinicos y biomarcadores genomicos. Publicaciones cientificas.",
    ))
    assert out["recommendation"] == "SKIP"
    assert any("genomic_bioinformatics_specialist" in x for x in out["missing_requirements"])


def test_computational_neuroimaging_specialist_role_is_skip():
    out = evaluate_job(_job(
        "Investigador/a Postdoctoral Junior",
        "Neurociencia y cognicion. Conocimientos avanzados en modelizacion de cerebro completo, preprocesamiento de neuroimagen y fisica estadistica. Experiencia en neurociencia computacional, machine learning, Matlab y Python. PhD required.",
    ))
    assert out["recommendation"] == "SKIP"
    assert any("computational_neuroimaging_specialist" in x for x in out["missing_requirements"])


def test_hospital_redcap_sample_operations_stack_is_not_equated_with_academic_rct_experience():
    out = evaluate_job(_job(
        "Asistente Clínico de Investigación y Gestión de Datos",
        "Ciencias de la salud. Experiencia previa en proyectos de investigacion clinica y traslacional. Experiencia en datos clinicos en entorno hospitalario real. Experiencia REDCap. Gestion de muestras biologicas. Identificacion e inclusion de pacientes y consentimiento informado. Proyecto europeo internacional.",
    ))
    assert out["score"] <= 49
    assert any("hospital_clinical_data_operations_experience" in x for x in out["missing_requirements"])


def test_required_clinical_trial_ops_in_catalan_is_specialist_gap():
    out = evaluate_job(_job(
        "Study Coordinator per a la Unitat de Recerca Clínica",
        "Ciencies de la salut. Experiencia previa en la coordinacio d assajos clinics. CRF, monitors, auditories i inspeccions. Coneixement de GCP i normativa d assajos clinics.",
    ))
    assert out["score"] <= 49
    assert any("regulated_clinical_trial_operations_experience" in x for x in out["missing_requirements"])


def test_required_regulated_clinical_profession_menu_is_hard_blocker():
    out = evaluate_job(_job(
        "Profesional Clínico de Investigación",
        "EL PERFIL QUE BUSCAMOS: Licenciatura o Grado en Medicina con especialidad via MIR, Psicologia con habilitacion sanitaria o Enfermeria. Clinical research duties.",
    ))
    assert out["recommendation"] == "SKIP"
    assert "regulated_clinical_profession" in out["blockers"]


def test_biomedical_preaward_scientific_pm_is_adjacent_review_not_unclear_low():
    out = evaluate_job(_job(
        "Pre-Award Scientific Project Manager",
        "A biomedical research institute. Horizon Europe proposal preparation, consortium building, research project coordination and grant applications. University degree in biomedical sciences required. PhD desirable. English C1.",
    ))
    assert out["domain_category"] == "ADJACENT"
    assert out["job_family"] == "research_project_management"
    assert out["recommendation"] == "REVIEW"
    assert out["score"] >= 65


def test_slash_gendered_investigador_clinico_prefers_clinical_family():
    out = evaluate_job(_job(
        "Investigador/a Clínico/a – Proyecto CONNECT-CARE",
        "Obesidad infantil. Diseno e implementacion de estudios clinicos, coordinacion entre centros, analisis estadistico en R y SPSS, proyecto internacional. Grado y posgrado en biomedicina o similares.",
    ))
    assert out["job_family"] == "clinical_human_research"


def test_teamtailor_employer_footer_is_trimmed_before_evaluation_text_is_used():
    detail = "Actual vacancy in molecular modelling and dynamics. ABOUT IRB BARCELONA We research cancer and diseases linked to ageing."
    trimmed = _trim_teamtailor_boilerplate(detail, "IRB Barcelona")
    assert "molecular modelling" in trimmed
    assert "ageing" not in trimmed


def test_teamtailor_board_default_location_can_be_supplied_by_collector_config_parser_still_preserves_explicit_location():
    html = "<a href='/jobs/123-role'><h3>Research role</h3><span class='job-location'>Madrid</span></a>"
    jobs = parse_teamtailor_jobs(html, "https://example.org/jobs", "Example")
    assert jobs[0]["location"] == "Madrid"


def test_deadline_for_applications_and_deadline_to_apply_are_parsed():
    a = assess_availability({"source": "Institutions", "full_detail": "Deadline for applications : 01/09/2026"}, date(2026, 8, 27))
    b = assess_availability({"source": "Institutions", "full_detail": "Deadline to apply: 06-09-2026"}, date(2026, 8, 27))
    assert a["application_status"] == "OPEN" and a["application_deadline"] == "2026-09-01"
    assert b["application_status"] == "OPEN" and b["application_deadline"] == "2026-09-06"
