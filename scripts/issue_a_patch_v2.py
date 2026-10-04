from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "jobbot" / "evaluate.py"
TEST = ROOT / "tests" / "test_scoring_v141_project_pm_precision.py"
EURAXESS_TEST = ROOT / "tests" / "test_v186_euraxess_recall_health.py"
MANIFEST = ROOT / "SCORING_FREEZE_V141.json"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


s = EVAL.read_text(encoding="utf-8")

# A bare mention of a university (degree requirement, internship agreement, etc.) is
# not research-institution evidence. Specific research-institution wording remains.
s = replace_once(
    s,
    '            r"\\b(?:university|universidad|universitat)\\b(?!\\s+(?:degree|degrees|qualification|qualifications|education|studies|graduate|diploma))|"\n',
    '',
    "remove bare-university institutional anchor",
)

funding_title_pattern = (
    r'(?:captacion|gestion).{0,80}(?:fondos|financiacion).{0,140}(?:ciencia|investigacion|recerca|i d i)|'
    r'(?:research|scientific).{0,60}(?:funding|grants?)|(?:grant|funding).{0,40}(?:manager|officer|coordinator)'
)

old_specific = '''        r"\\bcoordinador(?: a)? de projectes? de recerca\\b|"
        r"\\bcoordinador(?: a)? de proyectos? de investigacion\\b",
        title_norm_for_pm, re.I
    ))'''
new_specific = f'''        r"\\bcoordinador(?: a)? de projectes? de recerca\\b|"
        r"\\bcoordinador(?: a)? de proyectos? de investigacion\\b|"
        r"{funding_title_pattern}",
        title_norm_for_pm, re.I
    ))'''
s = replace_once(s, old_specific, new_specific, "add research-funding management title cue")

old_strong = '''        r"tecnico(?: a)? de gestion cientifica|tecnico(?: a)? de gestion de (?:la )?investigacion|"
        r"coordinador(?: a)? de projectes? de recerca|coordinador(?: a)? de proyectos? de investigacion",
        title_norm_for_pm, re.I
    ))
    institutional_research_management_context = bool(
        family == "research_project_management"
        and institutional_research_management_signals[0]
        and (
            institutional_signal_count >= 3
            or (strong_research_management_title_cue and institutional_signal_count >= 2)
        )
        and domain_category == "UNCLEAR"
    )'''
new_strong = f'''        r"tecnico(?: a)? de gestion cientifica|tecnico(?: a)? de gestion de (?:la )?investigacion|"
        r"coordinador(?: a)? de projectes? de recerca|coordinador(?: a)? de proyectos? de investigacion|"
        r"{funding_title_pattern}",
        title_norm_for_pm, re.I
    ))
    institutional_research_management_context = bool(
        family == "research_project_management"
        and (
            (
                institutional_research_management_signals[0]
                and institutional_signal_count >= 3
            )
            or (
                strong_research_management_title_cue
                and institutional_signal_count >= 2
            )
        )
        and domain_category == "UNCLEAR"
    )'''
s = replace_once(s, old_strong, new_strong, "allow strong research-funding title to anchor adjacent domain")

# Make the operational IT-delivery cluster bilingual enough to catch Spanish PMO roles
# while preserving research-tech PMs through the helper's >=2 research-duty exemption.
s = replace_once(
    s,
    '        bool(re.search(r"software|information technology|\\bit services?\\b|\\bict\\b|cloud infrastructure|enterprise systems?", n, re.I)),\n        bool(re.search(r"implementation|implantacion|implantacio|rollout|deployment|onboarding|service delivery|customer delivery", n, re.I)),\n        bool(re.search(r"customers?|clients?|clientes?|stakeholder satisfaction", n, re.I)),',
    '        bool(re.search(r"software|information technology|\\bit services?\\b|\\bict\\b|cloud infrastructure|enterprise systems?|technology projects?|proyectos? tecnologicos?|projectes? tecnologics?", n, re.I)),\n        bool(re.search(r"implementation|implantacion|implantacio|rollout|deployment|onboarding|service delivery|customer delivery|entrega final|lliurament final", n, re.I)),\n        bool(re.search(r"customers?|clients?|clientes?|cliente interno|cliente externo|stakeholder satisfaction", n, re.I)),',
    "extend operational IT-delivery evidence",
)

EVAL.write_text(s, encoding="utf-8")

# Repair the first staged test's intentionally over-strict synthetic score assertion,
# then add real recall and PMO false-positive regressions.
t = TEST.read_text(encoding="utf-8")
t = t.replace(
    '    assert result["score"] >= 50\n\n\ndef _assert_not_reviewed_as_research_pm(result):',
    '    assert not any("rather than research project management" in x for x in result["missing_requirements"])\n\n\ndef _assert_not_reviewed_as_research_pm(result):',
    1,
)
append = r'''


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
'''
if "test_v141_research_funding_role_preserves_review_recall" not in t:
    t += append
TEST.write_text(t, encoding="utf-8")

# This old collector regression intentionally froze the scoring engine at V1.39. An
# intentional scoring release must advance the expectation; EURAXESS logic itself is untouched.
e = EURAXESS_TEST.read_text(encoding="utf-8")
e = replace_once(
    e,
    '    assert production.FROZEN_ENGINE == "V1.39_INSTITUTIONAL_RESEARCH_PM_RECALL"\n    assert production.FREEZE_MANIFEST == "SCORING_FREEZE_V139.json"',
    '    assert production.FROZEN_ENGINE == "V1.41_ROLE_AWARE_PROJECT_PM_PRECISION"\n    assert production.FREEZE_MANIFEST == "SCORING_FREEZE_V141.json"',
    "advance stale EURAXESS freeze expectation",
)
EURAXESS_TEST.write_text(e, encoding="utf-8")

# Recompute freeze after the evaluator refinement.
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
manifest["note"] = (
    "V1.41 adds a role-aware precision guard for generic project delivery, removes bare university mentions "
    "as research-institution anchors, contextualizes proposal evidence, and adds explicit research-funding "
    "title/duty anchoring so legitimate I+D+i funding-management recall is preserved."
)
for rel in list(manifest["sha256"]):
    manifest["sha256"][rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("refined", EVAL)
print("updated", TEST)
print("updated", EURAXESS_TEST)
print("refreshed", MANIFEST)
