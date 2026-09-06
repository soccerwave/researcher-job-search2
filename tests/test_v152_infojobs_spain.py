from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from jobbot.production import SOURCE_ORDER, collect_sources, verify_scoring_freeze
from sources import infojobs_spain


class Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "ai-job-search-spain-test"
    cli = repo / infojobs_spain.CLI_RELATIVE
    cli.parent.mkdir(parents=True)
    cli.write_text("// test cli", encoding="utf-8")
    return repo


def test_v152_source_registered_and_freeze_unchanged():
    assert "infojobs" in SOURCE_ORDER
    root = Path(__file__).resolve().parents[1]
    assert verify_scoring_freeze(root)["ok"] is True


def test_v152_collect_search_dedup_detail_and_status(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(infojobs_spain, "_load_queries", lambda: ["gestor proyectos investigacion", "coordinador investigacion clinica"])

    def runner(cwd, args):
        if "search" in args:
            query = args[args.index("-q") + 1]
            if query.startswith("gestor"):
                payload = {"results": [
                    {"id": "ij-1", "title": "Gestor/a de proyectos de investigación", "company": "Institute A", "location": "Barcelona", "date": "2026-08-29", "url": "https://www.infojobs.net/job/ij-1"},
                    {"id": "ij-2", "title": "Coordinador/a de investigación clínica", "company": "Institute B", "location": "Madrid", "date": "2026-08-29", "url": "https://www.infojobs.net/job/ij-2"},
                ]}
            else:
                payload = {"results": [
                    {"id": "ij-2", "title": "Coordinador/a de investigación clínica", "company": "Institute B", "location": "Madrid", "date": "2026-08-29", "url": "https://www.infojobs.net/job/ij-2"},
                ]}
            return Proc(stdout=json.dumps(payload))
        identifier = args[args.index("detail") + 1]
        if identifier == "ij-1":
            return Proc(stdout="Gestión de proyectos de investigación europeos en salud. Requisitos y funciones completas.")
        return Proc(stdout="Esta oferta ya no está disponible. Coordinación de estudios clínicos.")

    diag = {}
    rows = infojobs_spain.collect(diagnostics=diag, repo_path=repo, max_jobs=10, runner=runner)
    assert len(rows) == 2
    assert diag["raw_results"] == 3
    assert diag["unique_jobs"] == 2
    assert diag["search_attempts"] == 2
    assert diag["search_failed"] == 0
    assert diag["detail_success"] == 2
    assert diag["source_status_open"] == 1
    assert diag["source_status_closed"] == 1
    by_id = {r["id"]: r for r in rows}
    assert by_id["ij-1"]["source_application_status"] == "OPEN"
    assert by_id["ij-2"]["source_application_status"] == "CLOSED"
    assert "gestor proyectos investigacion" in by_id["ij-2"]["search_query"]
    assert "coordinador investigacion clinica" in by_id["ij-2"]["search_query"]


def test_v152_uses_existing_infojobs_cli_contract(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(infojobs_spain, "_load_queries", lambda: ["investigador salud"])
    calls = []

    def runner(cwd, args):
        calls.append(args)
        if "search" in args:
            return Proc(stdout=json.dumps({"results": [{"id": "44", "title": "Investigador/a Salud", "company": "Org", "location": "Barcelona"}]}))
        return Proc(stdout="Investigación en salud, diseño de estudios y análisis de datos.")

    infojobs_spain.collect(diagnostics={}, repo_path=repo, jobage_days=2, limit_per_search=7, runner=runner)
    search = calls[0]
    assert search[:2] == [str(infojobs_spain.CLI_RELATIVE), "search"]
    assert search[search.index("--jobage") + 1] == "2"
    assert search[search.index("--limit") + 1] == "7"
    assert "-l" not in search
    detail = calls[1]
    assert detail == [str(infojobs_spain.CLI_RELATIVE), "detail", "44", "--format", "plain"]


def test_v152_query_failure_is_partial_not_silent(tmp_path, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(infojobs_spain, "_load_queries", lambda: ["good", "bad"])

    def runner(cwd, args):
        if "search" in args:
            if args[args.index("-q") + 1] == "bad":
                return Proc(stderr="temporary InfoJobs failure", returncode=1)
            return Proc(stdout=json.dumps({"results": [{"id": "5", "title": "Scientific Project Officer", "company": "Org", "location": "Spain"}]}))
        return Proc(stdout="Scientific project coordination in health research.")

    diag = {}
    rows = infojobs_spain.collect(diagnostics=diag, repo_path=repo, runner=runner)
    assert len(rows) == 1
    assert diag["search_success"] == 1
    assert diag["search_failed"] == 1
    assert diag["coverage_complete"] is False
    assert "incomplete" in diag["coverage_warning"].lower()


def test_v152_missing_external_repo_is_truthful_error(tmp_path, monkeypatch):
    monkeypatch.setattr(infojobs_spain, "_candidate_repos", lambda explicit=None: [tmp_path / "missing"])
    diag = {}
    rows = infojobs_spain.collect(diagnostics=diag, runner=lambda *a, **k: Proc())
    assert rows == []
    assert diag["repo_path"] == ""
    assert "not found" in diag["coverage_warning"].lower()


def test_v152_orchestration_marks_total_infojobs_setup_failure_error(tmp_path):
    args = SimpleNamespace(
        source="infojobs", infojobs_repo="", infojobs_limit_per_search=10,
        infojobs_jobage_days=1, infojobs_max_jobs=100,
        history_days=None, history_max_pages=40, history_max_candidates=250,
        euraxess_pages=8, euraxess_max_candidates=80, detail_delay=None,
    )

    def missing_source(*, diagnostics, **kwargs):
        diagnostics.update({
            "repo_path": "", "coverage_complete": False,
            "coverage_warning": "Spain ai-job-search repo with infojobs-search CLI was not found",
            "detail_success": 0, "detail_failed": 0, "truncated": 0,
            "search_attempts": 0, "search_success": 0, "search_failed": 0,
        })
        return []

    out = collect_sources(args, tmp_path, collector_overrides={"infojobs": missing_source})
    assert out["source_runs"]["infojobs"]["status"] == "ERROR"
    assert any("repo" in e.lower() for e in out["errors"])
