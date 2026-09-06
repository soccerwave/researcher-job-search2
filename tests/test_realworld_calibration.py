from jobbot.evaluate import evaluate_job


def test_isglobal_urban_health_postdoc_stays_out_of_primary_due_specialist_gap():
    job = {
        "title": "Postdoctoral researcher in climate change and urban health",
        "company": "ISGlobal",
        "location": "Barcelona, Spain",
        "full_detail": (
            "Public health research using Horizon Europe project data on climate, air pollution and urban health. "
            "PhD in epidemiology, environmental health, biostatistics or related discipline. "
            "Demonstrated record in epidemiology or environmental health. Experience with health impact assessment is an asset. "
            "Statistical analysis and complex data in R, academic writing, manuscripts and international consortium work."
        ),
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "ADJACENT"
    assert ev["job_family"] == "research_academic"
    assert ev["recommendation"] in {"LOW_PRIORITY", "SKIP"}
    assert ev["score"] <= 59
    assert ev["missing_requirements"]


def test_biocat_health_innovation_project_role_detected_but_catalan_gap_keeps_it_out_of_primary():
    job = {
        "title": "TÈCNIC/A DE PROJECTES D’INNOVACIÓ",
        "company": "Biocat",
        "location": "Barcelona, Spain",
        "full_detail": (
            "Impulsar i coordinar projectes d'innovació en salut i ciències de la vida. "
            "Relació amb centres de recerca, institucions i agents nacionals i internacionals. "
            "Formació universitària en ciències de la vida o de la salut, experiència en funcions similars, "
            "nivell fluït de català, castellà i anglès, i capacitat de gestió de projectes."
        ),
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "ADJACENT"
    assert ev["job_family"] in {"research_project_management", "scientific_health_innovation"}
    assert ev["score"] <= 64
    assert ev["recommendation"] in {"LOW_PRIORITY", "SKIP"}
    assert any("Catalan" in x for x in ev["missing_requirements"])


def test_tecsam_mental_health_innovation_role_detected_with_language_gap():
    job = {
        "title": "Promotor/a de la Xarxa TECSAM - Innovació en Salut Mental",
        "company": "Fundació Sant Joan de Déu",
        "location": "Sant Boi de Llobregat, Barcelona, Spain",
        "modality": "Hybrid",
        "full_detail": (
            "Innovació en salut mental, coordinació entre grups de recerca, institucions i ecosistema innovador. "
            "Suport a consorcis europeus i propostes de finançament. Experiència en gestió i implementació de projectes de recerca i innovació. "
            "Nivell alt escrit i parlat de català, castellà i anglès. Doctorat valorable."
        ),
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] == "ADJACENT"
    assert ev["job_family"] == "scientific_health_innovation"
    assert ev["score"] <= 64
    assert any("Catalan" in x for x in ev["missing_requirements"])


def test_irb_cell_signaling_postdoc_is_not_rescued_by_generic_postdoc_fit():
    job = {
        "title": "Postdoctoral Fellow",
        "company": "IRB Barcelona",
        "location": "Barcelona, Spain",
        "full_detail": (
            "Postdoctoral research on MAPK cell signaling and kinase pathways. You have a PhD in life sciences. "
            "Experience in cell signaling research, mass spectrometry-based phosphoproteomics, confocal microscopy, "
            "mammalian cell culture and molecular biology techniques. Scientific writing and international collaboration."
        ),
    }
    ev = evaluate_job(job)
    assert ev["job_family"] == "research_academic"
    assert ev["score"] <= 49
    assert ev["recommendation"] == "SKIP"
    assert any("Specialist methods" in x for x in ev["missing_requirements"])


def test_core_facility_specialist_lab_role_is_not_misclassified_as_transferable_coordination_role():
    job = {
        "title": "Junior Core Facility Coordinator",
        "company": "ISGlobal",
        "location": "Barcelona, Spain",
        "full_detail": (
            "Coordinate a core facility. BSc and MSc in Biotechnology or related biological discipline with practical laboratory background. "
            "Required experience in protein expression, immunoassays, biomarker quantification, molecular biology, biological samples, PCR and cell culture. "
            "Proficiency in Catalan, English and Spanish."
        ),
    }
    ev = evaluate_job(job)
    assert ev["score"] <= 49
    assert ev["recommendation"] == "SKIP"
    assert any("Specialist methods" in x for x in ev["missing_requirements"])
