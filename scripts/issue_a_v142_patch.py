from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "jobbot" / "rules.py"
PROD = ROOT / "jobbot" / "production.py"
VERSION = ROOT / "PRODUCTION_VERSION.json"
OLD_MANIFEST = ROOT / "SCORING_FREEZE_V141.json"
NEW_MANIFEST = ROOT / "SCORING_FREEZE_V142.json"
TEST = ROOT / "tests" / "test_scoring_v142_junior_researcher_recall.py"
EURAXESS_TEST = ROOT / "tests" / "test_v186_euraxess_recall_health.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


rules = RULES.read_text(encoding="utf-8")
rules = replace_once(
    rules,
    '        r"research scientist", r"research fellow", r"health researcher", r"exercise researcher",\n',
    '        r"research scientist", r"research fellow", r"junior researcher", r"health researcher", r"exercise researcher",\n',
    "add explicit junior researcher family pattern",
)
RULES.write_text(rules, encoding="utf-8")

prod = PROD.read_text(encoding="utf-8")
prod = replace_once(prod, 'FROZEN_ENGINE = "V1.41_ROLE_AWARE_PROJECT_PM_PRECISION"', 'FROZEN_ENGINE = "V1.42_JUNIOR_RESEARCHER_TITLE_RECALL"', "engine bump")
prod = replace_once(prod, 'PRODUCTION_VERSION = "V2.02_ROLE_AWARE_PROJECT_PM_PRECISION"', 'PRODUCTION_VERSION = "V2.03_JUNIOR_RESEARCHER_TITLE_RECALL"', "production bump")
prod = replace_once(prod, 'FREEZE_MANIFEST = "SCORING_FREEZE_V141.json"', 'FREEZE_MANIFEST = "SCORING_FREEZE_V142.json"', "manifest bump")
PROD.write_text(prod, encoding="utf-8")

VERSION.write_text(json.dumps({
    "production_version": "V2.03_JUNIOR_RESEARCHER_TITLE_RECALL",
    "scoring_engine": "V1.42_JUNIOR_RESEARCHER_TITLE_RECALL",
    "baseline": "V1.78_IDIBAPS_REPLACEMENT",
    "search_engine_baseline": "V1.78_IDIBAPS_REPLACEMENT",
    "scope": "Issue A recall-protection refinement. Explicit Junior Researcher titles now map to research_academic so mixed titles such as Project manager / Junior Researcher are not lost after the V1.41 generic-PM precision repair. V1.41 role-aware PM guards remain unchanged.",
    "deployment_baseline": "V1.81_WORKER_URL_DISCOVERY_RETRY",
    "reporting_baseline": "V1.82_MADRID_NEEDS_DETAIL_SEPARATION",
    "previous_production_version": "V2.02_ROLE_AWARE_PROJECT_PM_PRECISION"
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

TEST.write_text(r'''from jobbot.evaluate import evaluate_job


def _job(title: str, detail: str, location: str = "Madrid, Spain"):
    return {"title": title, "full_detail": detail, "description": detail, "location": location, "modality": ""}


def test_v142_mixed_project_manager_junior_researcher_is_not_lost():
    result = evaluate_job(_job(
        "Project manager / Junior Researcher",
        """
        Universidad Politécnica de Madrid. Gestión de proyecto. Desarrollo de herramientas de apoyo
        a la decisión clínica, LLM, RAG y ML. Redacción de documentos y artículos científicos.
        Experiencia en proyectos de investigación relacionados con la salud, revisión sistemática,
        metodología de investigación, recopilación de datos y análisis estadístico. Colaboración con
        socios internacionales. Área: Gestión de proyectos de investigación.
        """,
    ))
    assert result["job_family"] == "research_academic"
    assert result["score"] >= 50
    assert result["recommendation"] != "SKIP"


def test_v142_plain_junior_researcher_is_research_academic():
    result = evaluate_job(_job(
        "Junior Researcher",
        "Health research project involving scientific writing, statistical analysis and international collaboration.",
    ))
    assert result["job_family"] == "research_academic"


def test_v142_market_researcher_is_not_promoted_by_junior_researcher_pattern():
    result = evaluate_job(_job(
        "Market Researcher",
        "Consumer market research, commercial insights, customer segmentation and marketing operations.",
    ))
    assert result["job_family"] != "research_academic"
''', encoding="utf-8")

# Keep the EURAXESS collector lineage test aligned with the intentionally advanced scoring freeze.
e = EURAXESS_TEST.read_text(encoding="utf-8")
e = replace_once(
    e,
    '    assert production.FROZEN_ENGINE == "V1.41_ROLE_AWARE_PROJECT_PM_PRECISION"\n    assert production.FREEZE_MANIFEST == "SCORING_FREEZE_V141.json"',
    '    assert production.FROZEN_ENGINE == "V1.42_JUNIOR_RESEARCHER_TITLE_RECALL"\n    assert production.FREEZE_MANIFEST == "SCORING_FREEZE_V142.json"',
    "advance scoring freeze expectation",
)
EURAXESS_TEST.write_text(e, encoding="utf-8")

old = json.loads(OLD_MANIFEST.read_text(encoding="utf-8"))
paths = list(old["sha256"])
hashes = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in paths}
NEW_MANIFEST.write_text(json.dumps({
    "scoring_engine": "V1.42_JUNIOR_RESEARCHER_TITLE_RECALL",
    "package": "V2.03_JUNIOR_RESEARCHER_TITLE_RECALL",
    "status": "ACTIVE_PRODUCTION_CANDIDATE",
    "note": "Issue A recall refinement: explicit Junior Researcher title recognition restores research_academic family for mixed project-manager/researcher vacancies without weakening V1.41 generic Project Manager precision guards.",
    "tests_planned": [
        "tests/test_scoring_v142_junior_researcher_recall.py",
        "tests/test_scoring_v141_project_pm_precision.py",
        "tests/test_v140_research_pm_recall.py",
        "tests/test_v188_evaluator_calibration.py",
        "2026-10-04 immutable canonical replay"
    ],
    "sha256": hashes,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("patched rules/version/freeze/tests for V1.42 / V2.03")
