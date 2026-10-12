"""Targeted evaluator regressions: no speculative Catalan C2 and specialist wet-lab precision."""
from jobbot.evaluate import hard_blockers, _specialist_method_gaps, _mandatory_catalan_c2


def test_catalan_advantage_not_a_hard_blocker():
    jd = "Requirements: excellent English and Spanish. Catalan is an advantage."
    assert "catalan_c2" not in hard_blockers(jd, "Academic Project Manager")


def test_working_catalan_not_a_c2_blocker():
    jd = "Required: working knowledge of Catalan, Spanish and English."
    assert "catalan_c2" not in hard_blockers(jd, "Mission Project Manager")


def test_unrelated_required_word_does_not_block_catalan():
    jd = "Catalan desirable. Required: PhD and research project coordination."
    assert "catalan_c2" not in hard_blockers(jd, "Academic Project Manager")


def test_explicit_c2_remains_hard_blocked():
    assert _mandatory_catalan_c2("Required: Catalan C2 and Spanish B2.")
    assert "catalan_c2" in hard_blockers("Required: Catalan C2.", "Project Officer")


def test_cancer_stem_cell_lab_cluster_detected():
    text = ("Postdoctoral fellow in cancer biology and hematopoietic stem cell biology; "
            "experience in cell culture, flow cytometry and CRISPR is required.")
    assert "cancer_stem_cell_wet_lab" in _specialist_method_gaps(text, family="research_academic")


def test_single_cancer_word_not_a_lab_cluster():
    assert "cancer_stem_cell_wet_lab" not in _specialist_method_gaps(
        "Project manager coordinating a cancer research grant", family="research_project_management"
    )


def test_c2_in_separate_sentence_is_still_required():
    assert "catalan_c2" in hard_blockers("Catalan C2 is mandatory. Spanish is preferred.", "Project Officer")


def test_c2_only_desirable_is_not_hard_blocked():
    assert "catalan_c2" not in hard_blockers("Catalan C2 is desirable.", "Research Manager")


def test_catalan_requirement_guard_in_complete_evaluator():
    from jobbot.evaluate import evaluate_job
    job = {"title": "Academic Project Manager", "location": "Barcelona, Spain", "full_detail":
           "Required: working knowledge of Catalan, Spanish and English. Experience coordinating health research and grant reporting."}
    out = evaluate_job(job)
    assert "catalan_c2" not in out.get("hard_blockers", [])
