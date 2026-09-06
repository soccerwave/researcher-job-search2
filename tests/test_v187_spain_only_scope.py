from inspect import signature
from pathlib import Path
from types import SimpleNamespace

from jobbot import production
from sources import linkedin_mads


def _args(spain_only=False):
    return SimpleNamespace(
        linkedin_repo="",
        linkedin_limit_per_search=10,
        linkedin_jobage_minutes=2160,
        linkedin_max_jobs=120,
        linkedin_spain_only=spain_only,
    )


def test_production_forces_linkedin_spain_only_even_without_legacy_flag(tmp_path):
    kwargs = production._kwargs_for_source("linkedin", _args(False), tmp_path, [])
    assert kwargs["include_remote_europe"] is False


def test_legacy_spain_only_flag_remains_compatible(tmp_path):
    kwargs = production._kwargs_for_source("linkedin", _args(True), tmp_path, [])
    assert kwargs["include_remote_europe"] is False


def test_linkedin_adapter_default_is_spain_only():
    param = signature(linkedin_mads.collect).parameters["include_remote_europe"]
    assert param.default is False


def test_v187_keeps_frozen_scoring_engine():
    assert production.PRODUCTION_VERSION == "V1.87_SPAIN_ONLY_SCOPE"
    assert production.FROZEN_ENGINE == "V1.36_FINAL_SCORING_CLEANUP"


def test_manifest_declares_spain_only_scope():
    import json
    manifest = json.loads(Path("PRODUCTION_VERSION.json").read_text(encoding="utf-8"))
    assert manifest["production_version"] == "V1.87_SPAIN_ONLY_SCOPE"
    assert "Spain-only" in manifest["scope"]
