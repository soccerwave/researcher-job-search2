from types import SimpleNamespace

from jobbot.production import _coverage_complete


def test_fbg_complete_diagnostics_are_complete_in_orchestration():
    diag = {
        "board_fetched": True,
        "coverage_complete": True,
        "truncated": 0,
        "detail_failed": 0,
    }
    assert _coverage_complete("fbg", diag, SimpleNamespace()) is True


def test_fbg_truncation_remains_incomplete():
    diag = {
        "board_fetched": True,
        "coverage_complete": False,
        "truncated": 1,
        "detail_failed": 0,
    }
    assert _coverage_complete("fbg", diag, SimpleNamespace()) is False
