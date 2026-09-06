from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from jobbot.production import SOURCE_ORDER, collect_sources, verify_scoring_freeze
from sources import linkedin_mads


class Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "ai-job-search-private"
    cli = repo / linkedin_mads.CLI_RELATIVE
    cli.parent.mkdir(parents=True)
    cli.write_text("// test cli", encoding="utf-8")
    return repo


def test_v151_source_registered_and_freeze_unchanged():
    assert "linkedin" in SOURCE_ORDER
    root = Path(__file__).resolve().parents[1]
    assert verify_scoring_freeze(root)["ok"] is True


def test_v151_collect_search_dedup_detail_and_status(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(linkedin_mads, "_load_queries", lambda: (["research project manager", "research coordinator"], []))

    calls = []
    def runner(cwd, args):
        calls.append(args)
        if "search" in args:
            query = args[args.index("-q") + 1]
            if query == "research project manager":
                payload = {"results": [
                    {"id": "111", "title": "Research Project Manager", "company": "Institute A", "location": "Barcelona", "date": "1 hour ago", "url": "https://linkedin.com/jobs/view/111"},
                    {"id": "222", "title": "Research Coordinator", "company": "Institute B", "location": "Madrid", "date": "2 hours ago", "url": "https://linkedin.com/jobs/view/222"},
                ]}
            else:
                payload = {"results": [
                    {"id": "222", "title": "Research Coordinator", "company": "Institute B", "location": "Madrid", "date": "2 hours ago", "url": "https://linkedin.com/jobs/view/222"},
                ]}
            return Proc(stdout=json.dumps(payload))
        identifier = args[args.index("detail") + 1]
        if identifier == "111":
            return Proc(stdout="Research project management in health research. Full responsibilities and requirements.")
        return Proc(stdout="This job is no longer accepting applications. Research coordination role.")

    diag = {}
    rows = linkedin_mads.collect(
        diagnostics=diag,
        repo_path=repo,
        include_remote_europe=False,
        max_jobs=10,
        runner=runner,
    )
    assert len(rows) == 2
    assert diag["raw_results"] == 3
    assert diag["unique_jobs"] == 2
    assert diag["search_attempts"] == 2
    assert diag["search_failed"] == 0
    assert diag["detail_success"] == 2
    assert diag["source_status_open"] == 1
    assert diag["source_status_closed"] == 1
    by_id = {r["id"]: r for r in rows}
    assert by_id["111"]["detail_status"] == "OK"
    assert by_id["111"]["source_application_status"] == "OPEN"
    assert by_id["222"]["source_application_status"] == "CLOSED"
    assert "research project manager" in by_id["222"]["search_query"]
    assert "research coordinator" in by_id["222"]["search_query"]


def test_v151_query_failure_is_partial_not_silent(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(linkedin_mads, "_load_queries", lambda: (["good query", "bad query"], []))

    def runner(cwd, args):
        if "search" in args:
            query = args[args.index("-q") + 1]
            if query == "bad query":
                return Proc(stderr="temporary LinkedIn failure", returncode=1)
            return Proc(stdout=json.dumps({"results": [{
                "id": "333", "title": "Scientific Project Manager", "company": "Institute C",
                "location": "Spain", "url": "https://linkedin.com/jobs/view/333"
            }]}))
        return Proc(stdout="Scientific project management, Horizon Europe, grants and research coordination.")

    diag = {}
    rows = linkedin_mads.collect(diagnostics=diag, repo_path=repo, include_remote_europe=False, runner=runner)
    assert len(rows) == 1
    assert diag["search_success"] == 1
    assert diag["search_failed"] == 1
    assert diag["coverage_complete"] is False
    assert "incomplete" in diag["coverage_warning"].lower()


def test_v151_missing_external_repo_is_truthful_error(tmp_path, monkeypatch):
    monkeypatch.setattr(linkedin_mads, "_candidate_repos", lambda explicit=None: [tmp_path / "missing"])
    diag = {}
    rows = linkedin_mads.collect(diagnostics=diag, runner=lambda *a, **k: Proc())
    assert rows == []
    assert diag["repo_path"] == ""
    assert "not found" in diag["coverage_warning"].lower()


def test_v151_orchestration_marks_total_linkedin_setup_failure_error(tmp_path):
    args = SimpleNamespace(
        source="linkedin", linkedin_repo="", linkedin_limit_per_search=10,
        linkedin_jobage_minutes=2160, linkedin_max_jobs=120, linkedin_spain_only=False,
        history_days=None, history_max_pages=40, history_max_candidates=250,
        euraxess_pages=8, euraxess_max_candidates=80, detail_delay=None,
    )

    def missing_source(*, diagnostics, **kwargs):
        diagnostics.update({
            "repo_path": "", "coverage_complete": False,
            "coverage_warning": "Mads ai-job-search repo with linkedin-search CLI was not found",
            "detail_success": 0, "detail_failed": 0, "truncated": 0,
            "search_attempts": 0, "search_success": 0, "search_failed": 0,
        })
        return []

    out = collect_sources(args, tmp_path, collector_overrides={"linkedin": missing_source})
    assert out["source_runs"]["linkedin"]["status"] == "ERROR"
    assert any("repo" in e.lower() for e in out["errors"])
