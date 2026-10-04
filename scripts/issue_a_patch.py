from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "jobbot" / "evaluate.py"
PROD = ROOT / "jobbot" / "production.py"
TEST = ROOT / "tests" / "test_scoring_v141_project_pm_precision.py"
MANIFEST = ROOT / "SCORING_FREEZE_V141.json"
VERSION = ROOT / "PRODUCTION_VERSION.json"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


s = EVAL.read_text(encoding="utf-8")

helper = r'''

def _generic_project_delivery_mismatch(title: str, text: str) -> tuple[bool, str]:
    """Detect operational/commercial project-delivery roles that are not research PM.

    This guard is deliberately role-aware rather than a keyword blacklist. It only acts
    on generic project-manager/coordinator/officer titles, exempts explicit research/
    scientific/EU-research titles, and also exempts generic titles whose JD contains a
    coherent set of real research-project duties (funders, consortium/work packages,
    scientific coordination, or research-funding proposal work).
    """
    t = normalize(title)
    n = normalize(text)

    generic_project_title = bool(re.search(
        r"\bproject (?:manager|coordinator|officer)\b", t, re.I
    ))
    if not generic_project_title:
        return False, ""

    explicit_research_title = bool(re.search(
        r"\b(?:research|scientific|clinical research|health research) project (?:manager|coordinator|officer)\b|"
        r"\b(?:eu|european|horizon europe) project (?:manager|coordinator|officer)\b|"
        r"\bgestor(?: a)? de proyectos? (?:de investigacion|cientificos?|europeos?)\b|"
        r"\bcoordinador(?: a)? de (?:proyectos? de investigacion|projectes? de recerca|proyectos? europeos?|projectes? europeus?)\b|"
        r"\btecnico(?: a)? de gestion (?:cientifica|de (?:la )?investigacion)\b",
        t, re.I
    ))
    if explicit_research_title:
        return False, ""

    research_duty_signals = [
        bool(re.search(r"horizon europe|european commission|\berc\b|\bmsca\b|eu4health", n, re.I)),
        bool(re.search(r"international consortium|consortium partners?|work packages?", n, re.I)),
        bool(re.search(
            r"scientific coordination|coordinacion cientifica|coordinacio cientifica|"
            r"technical coordination.{0,80}(?:research|study)|coordinacion tecnica.{0,80}(?:investigacion|estudio)|"
            r"coordinacio tecnica.{0,80}(?:recerca|estudi)",
            n, re.I
        )),
        bool(re.search(
            r"pre[- ]?award|research grants?|grant calls?|funding calls?|funding opportunities?|"
            r"convocatorias?.{0,80}(?:financiacion|ayudas?|competitivas?)|"
            r"convocatories?.{0,80}(?:financament|ajuts?|competitives?)",
            n, re.I
        )),
        bool(re.search(
            r"(?:grant|funding|research|horizon).{0,80}proposal|"
            r"proposal.{0,80}(?:grant|funding|research|horizon)|"
            r"(?:financiacion|investigacion|convocatoria).{0,80}propuestas?|"
            r"propuestas?.{0,80}(?:financiacion|investigacion|convocatoria)",
            n, re.I
        )),
    ]
    if sum(research_duty_signals) >= 2:
        return False, ""

    industrial_signals = [
        bool(re.search(r"\bcapex\b|capital project|plant design|production scale|manufacturing|factory|production line", n, re.I)),
        bool(re.search(r"industrial engineering|process engineering|commissioning|engineering delivery|equipment installation|production equipment", n, re.I)),
        bool(re.search(r"construction|procurement|supply chain|contractor management", n, re.I)),
    ]
    industrial_delivery = industrial_signals[0] and sum(industrial_signals) >= 2

    facilities_signals = [
        bool(re.search(r"facilit(?:y|ies)|office relocation|building refurbishment|fit[- ]?out|site works?|construction", n, re.I)),
        bool(re.search(r"procurement|vendor management|contractor management|maintenance", n, re.I)),
        bool(re.search(r"building budget|construction budget|facilities scheduling|commissioning", n, re.I)),
    ]
    facilities_delivery = sum(facilities_signals) >= 2

    commercial_signals = [
        bool(re.search(r"pre[- ]?sales|preventa|sales support|commercial|\brfp\b|\brfi\b|ofertas? comerciales?", n, re.I)),
        bool(re.search(r"software|information technology|\bit services?\b|\bict\b|cloud infrastructure|enterprise systems?", n, re.I)),
        bool(re.search(r"implementation|implantacion|implantacio|rollout|deployment|onboarding|service delivery|customer delivery", n, re.I)),
        bool(re.search(r"customers?|clients?|clientes?|stakeholder satisfaction", n, re.I)),
    ]
    commercial_it_delivery = bool(
        commercial_signals[0] and (commercial_signals[1] or commercial_signals[2])
        or commercial_signals[1] and commercial_signals[2] and commercial_signals[3]
    )

    explicit_it_title = bool(re.search(
        r"\b(?:it|ict) project manager\b|\bproject manager.{0,25}(?:it|ict|information technology|software|cloud)\b",
        t, re.I
    ))

    if industrial_delivery:
        return True, "industrial/CAPEX/manufacturing project delivery"
    if facilities_delivery:
        return True, "facilities/construction project delivery"
    if explicit_it_title or commercial_it_delivery:
        return True, "commercial/IT/customer implementation project delivery"
    return False, ""
'''

s = replace_once(
    s,
    "\n\ndef evaluate_job(job: dict[str, Any]) -> dict[str, Any]:",
    helper + "\n\ndef evaluate_job(job: dict[str, Any]) -> dict[str, Any]:",
    "insert role-aware project delivery helper",
)

s = replace_once(
    s,
    '    family, _ = detect_family(title)\n',
    '    family, _ = detect_family(title)\n    project_delivery_mismatch, project_delivery_mismatch_reason = _generic_project_delivery_mismatch(title, norm)\n',
    "compute project delivery mismatch",
)

s = replace_once(
    s,
    '    if family == "unclear" and re.search(r"\\bproject (?:manager|coordinator|officer)\\b", normalize(title), re.I):\n',
    '    if family == "unclear" and not project_delivery_mismatch and re.search(r"\\bproject (?:manager|coordinator|officer)\\b", normalize(title), re.I):\n',
    "guard early generic PM inference",
)

marker = '''        title_norm_for_pm, re.I
    ))

    institutional_research_management_signals = ['''
insert = '''        title_norm_for_pm, re.I
    ))
    generic_project_management_title_cue = bool(re.search(
        r"\\bproject (?:manager|coordinator|officer)\\b",
        title_norm_for_pm, re.I
    ))
    research_specific_management_title_cue = bool(re.search(
        r"\\b(?:research|scientific|clinical research|health research) project (?:manager|coordinator|officer)\\b|"
        r"\\b(?:eu|european|horizon europe) project (?:manager|coordinator|officer)\\b|"
        r"gestor(?: a)? de proyectos? europeos?|gestor(?: a)? pre[- ]?award|"
        r"tecnico(?: a)? de gestion cientifica|tecnico(?: a)? de gestion de (?:la )?investigacion|"
        r"coordinador(?: a)? de projectes? de recerca|coordinador(?: a)? de proyectos? de investigacion",
        title_norm_for_pm, re.I
    ))

    institutional_research_management_signals = ['''
s = replace_once(s, marker, insert, "split generic vs research-specific PM title cues")

s = replace_once(
    s,
    '            r"directorate of research|research and innovation|research teams?|"\n            r"equips? d investigacio|grups? d investigacio|equipos? de investigacion",',
    '            r"directorate of research|research and innovation|research teams?|"\n            r"\\b(?:university|universidad|universitat)\\b(?!\\s+(?:degree|degrees|qualification|qualifications|education|studies|graduate|diploma))|"\n            r"equips? d investigacio|grups? d investigacio|equipos? de investigacion",',
    "constrain university institution signal",
)
# Remove the old broad substring signal if it is still present in the preceding line.
s = s.replace('r"centre de recerca|instituto de investigacion|universit|research foundation|"',
              'r"centre de recerca|instituto de investigacion|research foundation|"')

old_grants = '''            r"pre[- ]?award|proposal preparation|preparacion.{0,80}propuestas?|"
            r"elaboracio.{0,80}propostes?|competitive proposals?",'''
new_grants = '''            r"pre[- ]?award|"
            r"(?:grant|funding|research|horizon|call).{0,80}proposal preparation|"
            r"proposal preparation.{0,80}(?:grant|funding|research|horizon|call)|"
            r"(?:financiacion|investigacion|convocatoria).{0,80}preparacion.{0,80}propuestas?|"
            r"preparacion.{0,80}propuestas?.{0,80}(?:financiacion|investigacion|convocatoria)|"
            r"(?:financament|recerca|convocatoria).{0,80}elaboracio.{0,80}propostes?|"
            r"competitive (?:research|grant|funding) proposals?",'''
s = replace_once(s, old_grants, new_grants, "contextualise grant proposal signal")

old_promotion = '''    institutional_signal_count = sum(institutional_research_management_signals)
    if family == "unclear" and (
        (research_management_title_cue and institutional_signal_count >= 2)
        or institutional_signal_count >= 5
    ):
        family = "research_project_management"
'''
new_promotion = '''    institutional_signal_count = sum(institutional_research_management_signals)
    institutional_research_anchor = any(
        institutional_research_management_signals[i] for i in (0, 2, 3, 5, 6)
    )
    if family == "unclear" and not project_delivery_mismatch and (
        (research_specific_management_title_cue and institutional_signal_count >= 2)
        or (
            generic_project_management_title_cue
            and institutional_research_anchor
            and institutional_signal_count >= 2
        )
        or institutional_signal_count >= 5
    ):
        family = "research_project_management"
'''
s = replace_once(s, old_promotion, new_promotion, "make V1.40 promotion research-anchored")

s = replace_once(
    s,
    '    if family == "unclear" and domain_category in {"CORE", "ADJACENT"}:\n        eu_pm_signals = [',
    '    if family == "unclear" and not project_delivery_mismatch and domain_category in {"CORE", "ADJACENT"}:\n        eu_pm_signals = [',
    "guard generic EU PM inference",
)

score_marker = '''    if communication_specialist_role:
        missing.append("Role is primarily specialist research/science communication rather than research project management")
        score = min(score, 49)

    if score >= 90:
'''
score_insert = '''    if communication_specialist_role:
        missing.append("Role is primarily specialist research/science communication rather than research project management")
        score = min(score, 49)

    if project_delivery_mismatch:
        missing.append(
            "Role is primarily " + project_delivery_mismatch_reason + " rather than research project management"
        )
        score = min(score, 49)

    if score >= 90:
'''
s = replace_once(s, score_marker, score_insert, "add operational project-delivery score guard")

EVAL.write_text(s, encoding="utf-8")

p = PROD.read_text(encoding="utf-8")
p = replace_once(p, 'FROZEN_ENGINE = "V1.40_RESEARCH_PM_TITLE_VARIANT_RECALL"',
                 'FROZEN_ENGINE = "V1.41_ROLE_AWARE_PROJECT_PM_PRECISION"', "production scoring engine")
p = replace_once(p, 'PRODUCTION_VERSION = "V2.01_MADRID_EFFECTIVE_CACHE_AGE"',
                 'PRODUCTION_VERSION = "V2.02_ROLE_AWARE_PROJECT_PM_PRECISION"', "production version")
p = replace_once(p, 'FREEZE_MANIFEST = "SCORING_FREEZE_V140.json"',
                 'FREEZE_MANIFEST = "SCORING_FREEZE_V141.json"', "freeze manifest")
PROD.write_text(p, encoding="utf-8")

TEST.write_text(r'''import pytest

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
    assert result["score"] >= 50


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
''', encoding="utf-8")

VERSION.write_text(json.dumps({
    "production_version": "V2.02_ROLE_AWARE_PROJECT_PM_PRECISION",
    "scoring_engine": "V1.41_ROLE_AWARE_PROJECT_PM_PRECISION",
    "baseline": "V1.78_IDIBAPS_REPLACEMENT",
    "search_engine_baseline": "V1.78_IDIBAPS_REPLACEMENT",
    "scope": "Evaluator precision repair for generic Project Manager roles. V1.41 preserves explicit institutional/research project-management recall while preventing industrial/CAPEX/manufacturing, facilities/construction, presales/commercial IT and customer-implementation delivery roles from being promoted by leaky university/proposal signals. V2.01 Madrid effective-cache-age logic, V2.00 InfoJobs watch-only, V1.98 state collision guard and V1.97 FPS OK_API integration remain active.",
    "deployment_baseline": "V1.81_WORKER_URL_DISCOVERY_RETRY",
    "reporting_baseline": "V1.82_MADRID_NEEDS_DETAIL_SEPARATION",
    "previous_production_version": "V2.01_MADRID_EFFECTIVE_CACHE_AGE"
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

freeze_paths = [
    "jobbot/evaluate.py",
    "jobbot/rules.py",
    "jobbot/normalize.py",
    "config/rules.json",
    "config/profile.json",
    "jobbot/availability.py",
]
hashes = {}
for rel in freeze_paths:
    hashes[rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()

MANIFEST.write_text(json.dumps({
    "scoring_engine": "V1.41_ROLE_AWARE_PROJECT_PM_PRECISION",
    "package": "V2.02_ROLE_AWARE_PROJECT_PM_PRECISION",
    "status": "ACTIVE_PRODUCTION_CANDIDATE",
    "note": "V1.41 adds a role-aware precision guard for generic project delivery and repairs two V1.40 semantic leaks: university-degree text no longer counts as research-institution evidence, and commercial proposal/RFP wording no longer counts as research-grant proposal evidence. Explicit research/scientific/EU research PM titles and coherent institutional research-management duties remain recall-protected.",
    "tests_planned": [
        "tests/test_scoring_v141_project_pm_precision.py",
        "tests/test_v140_research_pm_recall.py",
        "tests/test_v188_evaluator_calibration.py",
        "existing evaluator regression suite",
        "2026-10-04 immutable canonical replay"
    ],
    "sha256": hashes,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("patched", EVAL)
print("wrote", TEST)
print("wrote", MANIFEST)
print("wrote", VERSION)
