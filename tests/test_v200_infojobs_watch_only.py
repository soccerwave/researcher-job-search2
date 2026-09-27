from pathlib import Path
from types import SimpleNamespace

import run_live_sample as cli
from jobbot.production import collect_sources


def _args(source="infojobs"):
    return SimpleNamespace(
        source=source,
        history_days=None,
        history_max_pages=40,
        history_max_candidates=250,
        euraxess_pages=8,
        euraxess_max_candidates=80,
        detail_delay=None,
        as_of="2026-09-27",
        bist_max_pages=5,
        bist_max_jobs=100,
        institution_max_pages=4,
        institution_max_jobs_per_board=100,
        madrid_pages=10,
        madrid_max_jobs=100,
        madrid_detail_workers=3,
        fisabio_max_jobs=50,
        fps_max_jobs=50,
        iislafe_pages=3,
        iislafe_max_jobs=30,
        gencat_max_jobs=50,
        csic_max_jobs=100,
        isciii_pages=3,
        isciii_max_jobs=100,
        idibaps_max_jobs=100,
        upc_max_jobs=100,
        idibell_max_jobs=100,
        hospitaldelmar_max_jobs=100,
        santpau_pages=3,
        santpau_max_jobs=60,
        fbg_max_jobs=50,
        linkedin_repo="",
        infojobs_repo="",
        linkedin_limit_per_search=10,
        linkedin_jobage_minutes=2160,
        linkedin_max_jobs=120,
        infojobs_limit_per_search=10,
        infojobs_jobage_days=1,
        infojobs_max_jobs=100,
        academicpositions_max_jobs=80,
        ikerbasque_max_calls=20,
        atswatch_max_jobs_per_employer=100,
        out="out",
        state_file=None,
        no_state=True,
    )


def test_v200_infojobs_discovery_is_watch_only(tmp_path):
    def fake_infojobs(*, diagnostics, enrich_detail, **kwargs):
        assert enrich_detail is False
        diagnostics.update({
            "coverage_complete": True,
            "search_attempts": 7,
            "search_success": 7,
            "search_failed": 0,
            "truncated": 0,
            "detail_success": 0,
            "detail_failed": 0,
        })
        return [{
            "source": "InfoJobs",
            "id": "IJ1",
            "title": "Research Project Manager",
            "company": "Example Institute",
            "location": "Barcelona",
            "url": "https://www.infojobs.net/example/of-i123",
            "full_detail": "",
            "detail_status": "",
        }]

    out = collect_sources(
        _args(), tmp_path,
        collector_overrides={"infojobs": fake_infojobs},
    )

    assert out["jobs"] == []
    assert len(out["watch_jobs"]) == 1
    assert out["watch_jobs"][0]["watch_only"] is True
    assert out["source_runs"]["infojobs"]["status"] == "OK"
    assert out["source_runs"]["infojobs"]["watch_discovered"] == 1


def test_v200_watch_rows_do_not_enter_canonical_or_needs_detail(tmp_path, monkeypatch):
    watch = {
        "source": "InfoJobs",
        "id": "IJ1",
        "title": "Research Project Manager",
        "company": "Example Institute",
        "location": "Barcelona",
        "url": "https://www.infojobs.net/example/of-i123",
        "watch_only": True,
    }

    def fake_collect_sources(args, out_dir):
        return {
            "jobs": [],
            "watch_jobs": [watch],
            "errors": [],
            "warnings": [],
            "diagnostics": {"infojobs": {"watch_only": True, "watch_discovered": 1}},
            "source_runs": {
                "infojobs": {
                    "source": "InfoJobs",
                    "status": "OK",
                    "jobs_collected": 1,
                    "coverage_complete": True,
                    "detail_resolution_complete": True,
                    "detail_success": 0,
                    "detail_failed": 0,
                    "truncated": 0,
                    "error": "",
                    "warnings": [],
                    "watch_only": True,
                    "watch_discovered": 1,
                }
            },
            "selected_sources": ["infojobs"],
            "euraxess_audit": [],
        }

    monkeypatch.setattr(cli, "collect_sources", fake_collect_sources)
    monkeypatch.setattr(cli, "assert_scoring_freeze", lambda root: {"ok": True, "mismatches": []})
    monkeypatch.setattr(cli, "ROOT", tmp_path)

    args = _args()
    args.out = "out"
    summary = cli.run(args)

    out_dir = tmp_path / "out"
    canonical = (out_dir / "all_canonical.csv").read_text(encoding="utf-8-sig")
    needs = (out_dir / "needs_detail_review.csv").read_text(encoding="utf-8-sig")
    watch_csv = (out_dir / "infojobs_watch.csv").read_text(encoding="utf-8-sig")

    assert "Research Project Manager" not in canonical
    assert "Research Project Manager" not in needs
    assert "Research Project Manager" in watch_csv
    assert summary["needs_detail_review"] == 0
    assert summary["infojobs_watch_only"] == 1
