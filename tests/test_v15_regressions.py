from jobbot.evaluate import evaluate_job
from sources.euraxess import parse_search_html, _query_relevant, _is_spain


def test_euraxess_card_metadata_parsing():
    html = '''<div>JOB Spain IDIBELL Posted on: 13 August 2026
    <h3><a href="/jobs/99999">Study Coordinator in Physical Activity Trial</a></h3>
    Work Locations: Number of offers: 1, Spain, Barcelona Research Field: Medical sciences</div>'''
    jobs = parse_search_html(html, "physical activity")
    assert len(jobs) == 1
    j = jobs[0]
    assert j["company"] == "IDIBELL"
    assert j["location"] == "Spain"
    assert j["date"] == "13 August 2026"


def test_euraxess_postfilter_requires_real_query_relevance():
    job = {"title": "Quantum Device R&D engineer", "description": "quantum devices and cleanroom", "full_detail": "", "location": "Spain"}
    assert not _query_relevant(job, "physical activity")


def test_euraxess_postfilter_requires_spain():
    job = {"title": "Postdoc in Physical Activity", "description": "Country Netherlands", "full_detail": "", "location": "Netherlands"}
    assert not _is_spain(job)


def test_recognition_does_not_trigger_cognition_domain():
    job = {
        "title": "Postdoctoral Fellow in Ion-Exchange Membranes and Electrodialysis",
        "location": "Spain",
        "full_detail": "Research assessment includes recognition of academic contributions. PhD required."
    }
    ev = evaluate_job(job)
    assert ev["domain_category"] != "ADJACENT" or "cognitive_health" not in " ".join(ev["fit_signals"])


def test_cancer_study_coordinator_is_not_primary_from_neuroscience_boilerplate_alone():
    # V1.13 deliberately changed the old V1.5 behavior: coordination roles are no longer
    # card-/title-blocked merely because the disease area is cancer. They may reach full-JD
    # evaluation, but generic institute neuroscience boilerplate must not make them high-priority.
    job = {
        "title": "Study Coordinator for Cancer Clinical Trials",
        "location": "Spain",
        "full_detail": "The institute works in cancer, neuroscience and regenerative medicine. The role coordinates oncology clinical trials and cancer therapies. Project coordination and international projects."
    }
    ev = evaluate_job(job)
    assert ev["score"] <= 64
    assert ev["recommendation"] in {"LOW_PRIORITY", "SKIP"}
