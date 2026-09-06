from pathlib import Path
from types import SimpleNamespace

from jobbot.dedupe import deduplicate
from jobbot.production import SOURCE_ORDER, collect_sources, selected_sources, verify_scoring_freeze


def _args(source="both"):
    return SimpleNamespace(
        source=source,
        history_days=None,
        history_max_pages=40,
        history_max_candidates=250,
        euraxess_pages=8,
        euraxess_max_candidates=80,
        detail_delay=None,
        as_of=None,
        bist_max_pages=5,
        bist_max_jobs=100,
        institution_max_pages=4,
        institution_max_jobs_per_board=100,
        madrid_pages=10,
        madrid_max_jobs=100,
        fisabio_max_jobs=50,
        fps_max_jobs=50,
        iislafe_pages=3,
        iislafe_max_jobs=30,
    )


def test_v137_all_selects_every_production_source_in_stable_order():
    assert selected_sources("all") == list(SOURCE_ORDER)
    assert selected_sources("both") == ["biocat", "euraxess"]


def test_v137_fail_soft_keeps_successful_source_when_another_raises(tmp_path):
    def good_biocat(*, diagnostics, **kwargs):
        diagnostics.update({"board_fetch": "OK", "detail_success": 1, "detail_failed": 0})
        return [{
            "source": "Biocat", "id": "B1", "title": "Research Assistant",
            "company": "Example Institute", "location": "Barcelona", "url": "https://example.org/job/1",
            "full_detail": "A sufficiently long validated job description for testing orchestration.",
            "detail_status": "OK_HTML",
        }]

    def broken_euraxess(*, diagnostics, **kwargs):
        diagnostics.update({"source": "EURAXESS"})
        raise RuntimeError("temporary feed failure")

    out = collect_sources(
        _args("both"), tmp_path,
        collector_overrides={"biocat": good_biocat, "euraxess": broken_euraxess},
    )
    assert len(out["jobs"]) == 1
    assert out["source_runs"]["biocat"]["status"] == "OK"
    assert out["source_runs"]["euraxess"]["status"] == "ERROR"
    assert any("temporary feed failure" in e for e in out["errors"])


def test_v137_does_not_call_truncated_euraxess_scan_complete(tmp_path):
    def truncated_euraxess(*, diagnostics, **kwargs):
        diagnostics.update({
            "feed": {"coverage_complete": True, "page_errors": []},
            "candidate_truncated": 2,
            "detail_success": 1,
            "detail_failed": 0,
        })
        return [{
            "source": "EURAXESS", "id": "E1", "title": "Postdoctoral Researcher",
            "company": "Example University", "location": "Spain", "url": "https://example.org/job/2",
            "full_detail": "A sufficiently long validated job description for testing configured coverage.",
            "detail_status": "OK_HTML",
        }]

    out = collect_sources(_args("euraxess"), tmp_path, collector_overrides={"euraxess": truncated_euraxess})
    run = out["source_runs"]["euraxess"]
    assert run["status"] == "PARTIAL"
    assert run["coverage_complete"] is False
    assert any("truncated" in w.lower() for w in run["warnings"])


def test_v137_cross_source_merge_preserves_provenance_and_trusted_detail_source():
    a = {
        "source": "Source A", "id": "A1", "title": "Researcher", "company": "Institute",
        "location": "Barcelona", "url": "https://example.org/jobs/42",
        "full_detail": "short but valid detail", "detail_status": "OK_HTML",
        "source_provenance": [{"source": "Source A", "id": "A1", "url": "https://example.org/jobs/42", "detail_status": "OK_HTML"}],
    }
    b = {
        "source": "Source B", "id": "B9", "title": "Researcher", "company": "Institute",
        "location": "Barcelona", "url": "https://example.org/jobs/42?tracking=1",
        "full_detail": "this is a substantially longer valid detail used as the canonical full job description",
        "detail_status": "OK_HTML",
        "source_provenance": [{"source": "Source B", "id": "B9", "url": "https://example.org/jobs/42?tracking=1", "detail_status": "OK_HTML"}],
    }
    rows, removed = deduplicate([a, b])
    assert removed == 1
    assert len(rows) == 1
    merged = rows[0]
    assert {p["source"] for p in merged["source_provenance"]} == {"Source A", "Source B"}
    assert merged["trusted_full_detail_source"] == "Source B"


def test_v137_v136_freeze_manifest_matches_package_bytes():
    root = Path(__file__).resolve().parents[1]
    result = verify_scoring_freeze(root)
    assert result["ok"] is True
    assert len(result["files_checked"]) == 6
    assert result["mismatches"] == []


def test_v137_run_writes_production_outputs_and_excludes_closed_detail_review(tmp_path, monkeypatch):
    import run_live_sample as cli

    closed_unresolved = {
        "source": "Biocat", "id": "B2", "title": "Unresolved role", "company": "Example Institute",
        "location": "Barcelona", "url": "https://example.org/job/closed",
        "description": "Application deadline: 01 August 2026",
        "full_detail": "", "detail_status": "FAILED",
        "source_provenance": [{"source": "Biocat", "id": "B2", "url": "https://example.org/job/closed", "detail_status": "FAILED"}],
    }
    open_resolved = {
        "source": "Biocat", "id": "B3", "title": "Exercise Researcher", "company": "Example Institute",
        "location": "Barcelona", "url": "https://example.org/job/open",
        "description": "Application deadline: 30 September 2026",
        "full_detail": "Exercise physiology research role involving human participants, physical activity, data analysis and research coordination.",
        "detail_status": "OK_HTML",
        "source_provenance": [{"source": "Biocat", "id": "B3", "url": "https://example.org/job/open", "detail_status": "OK_HTML"}],
    }

    def fake_collect_sources(args, out_dir):
        return {
            "jobs": [closed_unresolved, open_resolved],
            "errors": [], "warnings": [],
            "diagnostics": {key: ({"board_fetch": "OK", "detail_success": 1, "detail_failed": 1} if key == "biocat" else None) for key in SOURCE_ORDER},
            "source_runs": {"biocat": {
                "source": "Biocat", "status": "PARTIAL", "jobs_collected": 2,
                "coverage_complete": True, "detail_resolution_complete": False,
                "detail_success": 1, "detail_failed": 1, "truncated": 0,
                "error": "", "warnings": ["detail incomplete"],
            }},
            "selected_sources": ["biocat"], "euraxess_audit": [],
        }

    monkeypatch.setattr(cli, "ROOT", Path(__file__).resolve().parents[1])
    monkeypatch.setattr(cli, "collect_sources", fake_collect_sources)
    args = _args("biocat")
    args.as_of = "2026-08-28"
    args.out = str(tmp_path.relative_to(cli.ROOT)) if tmp_path.is_relative_to(cli.ROOT) else str(tmp_path)

    # Absolute --out is supported by pathlib join semantics and keeps the test isolated.
    summary = cli.run(args)
    assert summary["configured_scan_complete"] is False
    assert summary["needs_detail_review"] == 1
    assert summary["closed"] == 1
    assert (tmp_path / "run_summary.json").exists()
    assert (tmp_path / "all_canonical.csv").exists()
    assert (tmp_path / "actionable.csv").exists()
    actionable_text = (tmp_path / "actionable.csv").read_text(encoding="utf-8-sig")
    assert "Unresolved role" not in actionable_text


def test_v137_collector_internal_total_failure_is_reported_as_error(tmp_path):
    def fisabio_returns_diagnostics_instead_of_raising(*, diagnostics, **kwargs):
        diagnostics.update({
            "board_fetched": False,
            "coverage_complete": False,
            "coverage_warning": "FISABIO active board fetch/parse failed: test failure",
            "detail_success": 0,
            "detail_failed": 0,
            "truncated": 0,
        })
        return []

    out = collect_sources(_args("fisabio"), tmp_path, collector_overrides={"fisabio": fisabio_returns_diagnostics_instead_of_raising})
    assert out["source_runs"]["fisabio"]["status"] == "ERROR"
    assert any("test failure" in e for e in out["errors"])
