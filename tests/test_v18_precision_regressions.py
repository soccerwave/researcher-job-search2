from jobbot.evaluate import evaluate_job
import sources.euraxess as euraxess


def test_public_health_benefit_text_does_not_make_nuclear_postdoc_adjacent():
    job = {
        "title": "Postdoctoral Researcher position in Modelling and Simulation of Small Modular Reactors (SMRs)",
        "company": "IMDEA Energia",
        "location": "Spain",
        "full_detail": (
            "Research on modelling and simulation of small modular nuclear reactors. "
            "The contract includes all the benefits of the Spanish Public Health and Social Security System. "
            "Scientific publications and international collaboration are expected. PhD required."
        ),
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "DISTANT"
    assert ev["recommendation"] == "SKIP"
    assert ev["score"] <= 49


def test_legal_functional_capacity_phrase_does_not_create_physical_function_core_match():
    job = {
        "title": "Position for predoctoral research staff in training",
        "company": "University X",
        "location": "Spain",
        "full_detail": (
            "Applicants must have the functional capacity to perform the duties and meet legal public-employment requirements. "
            "The research is in industrial life-cycle analysis."
        ),
    }
    ev = evaluate_job(job)
    assert "doctoral_training_position" in ev["blockers"]
    assert ev["recommendation"] == "SKIP"
    assert ev["domain_category"] != "CORE"


def test_relevant_generic_project_manager_is_recognised_as_research_project_management():
    job = {
        "title": "Project Manager - DynamiCity Project",
        "company": "IDIBELL",
        "location": "Barcelona, Spain",
        "full_detail": (
            "Horizon Europe project on active mobility, physical activity and cancer prevention. "
            "Coordinate scientific and operational activities within an international consortium. "
            "Lead work packages, milestones and deliverables; coordinate participant recruitment, data collection and quality assurance. "
            "Contribute to scientific manuscripts and grant proposals. Experience in non-pharmacological intervention studies, "
            "preferably physical activity or exercise, and at least 4 years of research experience. PhD is highly valued."
        ),
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "CORE"
    assert ev["job_family"] == "research_project_management"
    assert ev["recommendation"] in {"APPLY", "STRONG_APPLY"}
    assert ev["score"] >= 80


def test_unrelated_generic_postdoc_with_transferable_skills_cannot_enter_primary():
    job = {
        "title": "Postdoctoral Researcher for Agricultural Ecosystems and Game Species Conservation",
        "company": "Forest Science Centre",
        "location": "Spain",
        "full_detail": (
            "Agricultural ecosystems and game species conservation research. Horizon Europe collaboration, project coordination, "
            "statistical analysis, scientific publications and international partners. PhD required."
        ),
    }
    ev = evaluate_job(job)
    assert ev["recommendation"] in {"LOW_PRIORITY", "SKIP"}
    assert ev["score"] <= 59


def test_clinical_researcher_requiring_degree_in_medicine_is_hard_blocked():
    job = {
        "title": "Clinical Researcher (Pneumology)",
        "company": "VHIR",
        "location": "Barcelona, Spain",
        "full_detail": (
            "Clinical research in COPD. Education and qualifications: Required: Degree in Medicine. "
            "Completion of specialist medical training (MIR). Required clinical experience as a medically qualified professional."
        ),
    }
    ev = evaluate_job(job)
    assert ev["recommendation"] == "SKIP"
    assert "mandatory_md" in ev["blockers"]


def test_neuromuscular_molecular_lab_postdoc_detects_specialist_method_gap():
    job = {
        "title": "Postdoctoral researcher for Experimental Neuromuscular Pathology",
        "company": "IRBLleida",
        "location": "Spain",
        "full_detail": (
            "Neuroscience research on physiology and pathology of the neuromuscular system. "
            "Required experience in electrophysiological recordings, advanced optical and electron microscopy, "
            "cell and molecular biology techniques including western blot, immunoprecipitation, PCR and cloning, and cell culture."
        ),
    }
    ev = evaluate_job(job)
    assert ev["recommendation"] == "SKIP"
    assert ev["score"] <= 49
    assert any("molecular_neuromuscular_lab" in x for x in ev["missing_requirements"])


def test_predoctoral_card_variants_are_rejected_before_detail_fetch():
    titles = [
        "Pre-doctoral Researcher in Magneto-optical characterization",
        "Predoctoral Researcher: Exposure and Effects",
        "Position for predoctoral research staff in training (Marie Curie)",
        "PhD Researcher - MSCA Doctoral Network - LEGEND - DC12",
    ]
    for title in titles:
        keep, reasons = euraxess._card_candidate({
            "title": title,
            "company": "University X",
            "location": "Spain",
            "description": "Physical activity may appear incidentally",
            "url": "https://euraxess.ec.europa.eu/jobs/999",
        })
        assert not keep, title
        assert "doctoral_student_position" in reasons


def test_euraxess_search_results_page_is_not_accepted_as_job_detail():
    bad = "Filter by Search results (7716) Showing results 1 to 10 JOB Portugal University X JOB France University Y"
    assert not euraxess._valid_euraxess_detail(bad)
    good = "Job Information Organisation/Company Institute X Country Spain Type of Contract Temporary Offer Description research"
    assert euraxess._valid_euraxess_detail(good)
