from __future__ import annotations

import json
from pathlib import Path

from sources import madrid_idi as madrid

ROOT = Path(__file__).resolve().parents[1]


def test_substantive_poem_short_circuits_external_fetch(monkeypatch):
    data = {
        "dsPuesto": "Research Project Manager",
        "dsEmpresa": "Research Institute",
        "dsFunciones": (
            "Coordinate Horizon Europe work packages, deliverables, milestones, partner meetings, "
            "reporting, study implementation and dissemination. " * 6
        ),
        "dsRequisitos": (
            "University degree in health sciences. Experience coordinating international research "
            "projects and strong written English. " * 5
        ),
        "dsOtros": "More information: https://example.org/jobs/project-manager",
    }
    monkeypatch.setattr(madrid, "_fetch_poem_api", lambda *a, **k: (data, "POEM_API_OK"))

    external_calls = []

    def should_not_fetch(*args, **kwargs):
        external_calls.append((args, kwargs))
        raise AssertionError("substantive POEM record must not fetch external URLs")

    monkeypatch.setattr(madrid, "fetch_url_text", should_not_fetch)
    job = {
        "id": "1",
        "title": "Research Project Manager",
        "company": "Research Institute",
        "location": "Madrid, Spain",
        "detail_candidates": ["https://example.org/jobs/project-manager"],
    }

    detail, status, url, method = madrid._fetch_detail_candidates(job, object(), (1, 1))

    assert status == "OK"
    assert method == "poem_api"
    assert "Horizon Europe" in detail
    assert url.endswith("/ofertas/1")
    assert external_calls == []


def test_partial_poem_still_uses_matching_external_full_jd(monkeypatch):
    data = {
        "dsPuesto": "Clinical Research Coordinator",
        "dsEmpresa": "Hospital Foundation",
        "dsOtros": "La descripción de este puesto está disponible aquí https://example.org/jobs/crc",
    }
    monkeypatch.setattr(madrid, "_fetch_poem_api", lambda *a, **k: (data, "POEM_API_OK"))
    external = (
        "Clinical Research Coordinator. Responsibilities include coordinating participant visits, "
        "study documentation and data quality. Requirements include experience in clinical research. "
        "How to apply: submit your CV before the closing date. " * 3
    )
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return external, "OK_HTML"

    monkeypatch.setattr(madrid, "fetch_url_text", fetch)
    job = {
        "id": "2",
        "title": "Clinical Research Coordinator",
        "company": "Hospital Foundation",
        "location": "Madrid, Spain",
        "detail_candidates": [],
    }

    detail, status, url, method = madrid._fetch_detail_candidates(job, object(), (1, 1))

    assert calls == ["https://example.org/jobs/crc"]
    assert status == "OK_HTML"
    assert method == "external_from_poem_api"
    assert "Responsibilities" in detail
    assert url == "https://example.org/jobs/crc"


def test_v171_manifest_and_scoring_freeze_identity():
    manifest = json.loads((ROOT / "PRODUCTION_VERSION.json").read_text(encoding="utf-8"))
    assert manifest["production_version"] == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"
    assert manifest["baseline"] == "V1.78_IDIBAPS_REPLACEMENT"
    assert manifest["scoring_engine"] == "V1.36_FINAL_SCORING_CLEANUP"
