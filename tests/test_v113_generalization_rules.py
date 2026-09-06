from jobbot.evaluate import evaluate_job
import sources.euraxess as euraxess


def _job(title, detail, location="Spain"):
    return {"title": title, "full_detail": detail, "location": location, "modality": ""}


def test_organizational_behaviour_is_not_equated_with_mental_health():
    out = evaluate_job(_job(
        "Postdoctoral Researcher in Organizational Behaviour and Social Identity",
        "Research Field: Psychological sciences, Behavioural sciences. PhD in Organizational Behavior, Management, Psychology, Economics or Sociology. Advanced multilevel models, SEM, causal inference and longitudinal analysis.",
    ))
    assert out["domain_category"] != "ADJACENT"
    assert out["score"] <= 59
    assert out["recommendation"] not in {"REVIEW", "APPLY", "STRONG_APPLY"}


def test_required_patch_clamp_specialism_is_a_practical_skip():
    out = evaluate_job(_job(
        "Postdoctoral researcher: electrophysiology & single-cell biophysics",
        "Neuroscience postdoc. We seek an experimentalist with strong patch-clamp electrophysiology to record directly from hair cells. Demonstrated strength in patch-clamp electrophysiology is required. PhD in physiology, biophysics or neuroscience.",
    ))
    assert out["recommendation"] == "SKIP"
    assert out["score"] <= 49
    assert any("patch_clamp_electrophysiology" in x for x in out["missing_requirements"])


def test_generic_researcher_title_is_blocked_when_full_jd_is_phd_training():
    out = evaluate_job(_job(
        "INVESTIGADOR / Researcher",
        "Horizon Europe MSCA Doctoral Network. The university offers 1 fully funded PhD position. Candidates must not already possess a doctoral degree and must meet admission requirements for the PhD program.",
    ))
    assert out["recommendation"] == "SKIP"
    assert "doctoral_training_position_jd" in out["blockers"]


def test_fellowship_host_search_is_not_treated_as_an_actual_job():
    out = evaluate_job(_job(
        "Marie Skłodowska-Curie Actions Postdoctoral Fellowship call 2026",
        "We are looking for experienced researchers interested in applying for the MSCA Postdoctoral Fellowship with our institute as host institution. We will support the application and proposal preparation.",
    ))
    assert out["recommendation"] == "SKIP"
    assert "fellowship_hosting_call" in out["blockers"]


def test_real_cofund_employment_programme_is_not_hosting_call_blocked():
    out = evaluate_job(_job(
        "BREATH Postdoctoral Programme (MSCA COFUND)",
        "The programme offers 6 positions. Fellows will be hired on a full-time employment contract for 24 months. Research is in biomaterials and translational research.",
    ))
    assert "fellowship_hosting_call" not in out["blockers"]


def test_descriptive_health_eu_project_support_role_infers_research_pm_family():
    out = evaluate_job(_job(
        "Health sciences graduate to support participation on a European research project",
        "Horizon Europe health project. Support in the management, coordination and monitoring of project activities from design to a clinical study. Follow project deliverables and milestones and support reporting to the European Commission and consortium partners. Organise consortium meetings and follow action points. Bachelor's degree in Health Sciences and at least 3 years in research required. English B2.",
    ))
    assert out["domain_category"] == "ADJACENT"
    assert out["job_family"] == "research_project_management"
    assert out["recommendation"] in {"LOW_PRIORITY", "REVIEW", "APPLY", "STRONG_APPLY"}
    assert out["score"] >= 60


def test_generic_clinical_trial_technician_can_infer_clinical_family_from_jd():
    out = evaluate_job(_job(
        "Superior Research Technician",
        "Health sciences research. Support coordination of a randomized clinical trial, patient follow-up, scheduling visits and participant recruitment. Manage eCRFs and clinical data capture, maintain study documentation and support monitoring. Bachelor's degree in Health Sciences. High Catalan and Spanish requested.",
    ))
    assert out["job_family"] == "clinical_human_research"
    # Catalan remains a meaningful gap; family inference should improve recall without
    # automatically promoting the role to Apply.
    assert out["score"] <= 64


def test_card_gate_rescues_transferable_roles_before_full_jd():
    titles = [
        "Study Coordinator for Cancer Clinical Trials",
        "University–Business R&D&I Officer",
        "BIOBANK & CLINICAL OPERATIONS Technician",
        "PART-TIME – Technician for the Epidemiology and Biostatistics Unit (Methodological Support)",
    ]
    for title in titles:
        keep, reasons = euraxess._card_candidate({
            "title": title,
            "description": "Spain research vacancy",
            "location": "Spain",
        })
        assert keep, (title, reasons)


def test_card_gate_still_rejects_specialist_cancer_postdoc_without_transferable_role():
    keep, reasons = euraxess._card_candidate({
        "title": "R2 POSTDOCTORAL RESEARCHER – CELLULAR ONCOLOGY",
        "description": "Cancer cell biology and molecular oncology",
        "location": "Spain",
    })
    assert not keep
    assert "obvious_distant_title" in reasons


def test_coherent_non_target_specialist_stacks_do_not_survive_on_transferable_skills():
    examples = [
        ("Postdoctoral researcher in chemical looping processes", "PhD Chemical Engineering. Chemical looping and thermochemical conversion using pyrolysis and gasification. Pilot scale-up. Horizon Europe publications and international collaboration."),
        ("Postdoc in soil health prediction", "Soil health and crop productivity using microbiome metabarcoding and metagenomics with machine learning predictive models. Scientific publications."),
        ("Postdoctoral AI researcher in computational pathology", "Computer vision and vision-language foundation models, deep learning, Python and computational pathology. International research project."),
    ]
    for title, detail in examples:
        out = evaluate_job(_job(title, detail))
        assert out["recommendation"] == "SKIP", (title, out)
        assert out["score"] <= 49


def test_core_exercise_research_positive_control_remains_high():
    out = evaluate_job(_job(
        "Postdoctoral Researcher in Exercise Physiology",
        "Human exercise intervention research on physical activity and cardiorespiratory fitness. Randomized controlled trial, physiological and fitness assessments, statistical analysis in R, scientific publications and international collaboration. PhD in exercise physiology required.",
    ))
    assert out["domain_category"] == "CORE"
    assert out["job_family"] == "research_academic"
    assert out["recommendation"] in {"APPLY", "STRONG_APPLY"}
    assert out["score"] >= 80


def test_disability_employment_quota_text_is_not_research_domain_evidence():
    out = evaluate_job(_job(
        "Postdoctoral Researcher in Generic Science",
        "Minimum experience 3 years, or 2 years for people with disabilities greater than 66 percent. Research is in generic laboratory science.",
    ))
    assert "disability" not in " ".join(out["fit_signals"]) 
