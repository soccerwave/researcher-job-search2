from pathlib import Path

import run_live_sample as cli
from jobbot.production import verify_scoring_freeze


def _row(source, recommendation, status="OPEN", provenance=None):
    return {
        "source": source,
        "title": f"{source} role",
        "company": "Institute",
        "location": "Spain",
        "recommendation": recommendation,
        "application_status": status,
        "source_provenance": provenance or [{"source": source, "id": source, "url": f"https://example.org/{source}"}],
    }


def test_v157_coverage_audit_measures_exclusive_and_overlap_contribution():
    rows = [
        _row("A", "APPLY"),
        _row("A+B", "LOW_PRIORITY", provenance=[{"source": "A"}, {"source": "B"}]),
        _row("B", "SKIP"),
        _row("C", "NEEDS_DETAIL_REVIEW"),
        _row("A+C", "REVIEW", status="CLOSED", provenance=[{"source": "A"}, {"source": "C"}]),
    ]
    runs = {
        "a": {"source": "A"},
        "b": {"source": "B"},
        "c": {"source": "C"},
    }

    audit = cli.build_coverage_audit(rows, runs)
    assert audit["aggregate"] == {
        "canonical_total": 5,
        "single_source_canonical": 3,
        "multi_source_canonical": 2,
        "actionable_total": 3,
        "single_source_actionable": 2,
        "multi_source_actionable": 1,
        "unattributed_canonical": 0,
        "sources_measured": 3,
    }

    a = audit["per_source"]["a"]
    assert a["canonical_covered"] == 3
    assert a["exclusive_canonical"] == 1
    assert a["overlapping_canonical"] == 2
    assert a["actionable_covered"] == 2
    assert a["exclusive_actionable"] == 1
    assert a["overlapping_actionable"] == 1
    assert a["exclusive_apply_or_strong"] == 1
    assert a["overlap_partners"] == {"B": 1, "C": 1}
    assert a["actionable_overlap_partners"] == {"B": 1}

    c = audit["per_source"]["c"]
    assert c["exclusive_actionable"] == 1
    assert c["exclusive_detail_review"] == 1

    assert audit["pairwise_overlaps"] == [
        {
            "source_a_key": "a", "source_a": "A", "source_b_key": "b", "source_b": "B",
            "canonical_overlap": 1, "actionable_overlap": 1,
        },
        {
            "source_a_key": "a", "source_a": "A", "source_b_key": "c", "source_b": "C",
            "canonical_overlap": 1, "actionable_overlap": 0,
        },
    ]


def test_v157_run_writes_coverage_outputs_and_exposes_marginal_counts(tmp_path, monkeypatch):
    common_detail = (
        "Research coordination role involving human studies, project management, data quality, "
        "stakeholder collaboration, scientific communication and grant reporting."
    )
    a = {
        "source": "Biocat", "id": "A1", "title": "Research Project Manager", "company": "Institute",
        "location": "Barcelona", "url": "https://example.org/jobs/42",
        "full_detail": common_detail, "detail_status": "OK_HTML",
        "source_application_status": "OPEN", "source_status_evidence": "current board",
        "source_provenance": [{"source": "Biocat", "id": "A1", "url": "https://example.org/jobs/42", "detail_status": "OK_HTML"}],
    }
    b = {
        "source": "EURAXESS", "id": "B1", "title": "Research Project Manager", "company": "Institute",
        "location": "Barcelona", "url": "https://example.org/jobs/42?utm_source=x",
        "full_detail": common_detail + " Additional employer boilerplate.", "detail_status": "OK_HTML",
        "source_application_status": "OPEN", "source_status_evidence": "current board",
        "source_provenance": [{"source": "EURAXESS", "id": "B1", "url": "https://example.org/jobs/42?utm_source=x", "detail_status": "OK_HTML"}],
    }

    def fake_collect_sources(args, out_dir):
        return {
            "jobs": [a, b],
            "errors": [], "warnings": [],
            "diagnostics": {"biocat": {}, "euraxess": {}},
            "source_runs": {
                "biocat": {"source": "Biocat", "status": "OK", "jobs_collected": 1, "coverage_complete": True,
                            "detail_resolution_complete": True, "detail_success": 1, "detail_failed": 0,
                            "truncated": 0, "error": "", "warnings": []},
                "euraxess": {"source": "EURAXESS", "status": "OK", "jobs_collected": 1, "coverage_complete": True,
                              "detail_resolution_complete": True, "detail_success": 1, "detail_failed": 0,
                              "truncated": 0, "error": "", "warnings": []},
            },
            "selected_sources": ["biocat", "euraxess"],
            "euraxess_audit": [],
        }

    monkeypatch.setattr(cli, "collect_sources", fake_collect_sources)
    args = cli.build_parser().parse_args(["--source", "all", "--no-state", "--as-of", "2026-08-29", "--out", str(tmp_path)])
    summary = cli.run(args)

    assert summary["unique"] == 1
    assert summary["duplicates_removed"] == 1
    assert summary["coverage_audit"]["aggregate"]["multi_source_canonical"] == 1
    assert summary["source_runs"]["biocat"]["exclusive_canonical"] == 0
    assert summary["source_runs"]["euraxess"]["overlapping_canonical"] == 1
    assert (tmp_path / "coverage_contribution.csv").exists()
    assert (tmp_path / "source_overlap.csv").exists()
    assert (tmp_path / "coverage_audit.json").exists()


def test_v157_scoring_freeze_still_matches_v136():
    root = Path(__file__).resolve().parents[1]
    result = verify_scoring_freeze(root)
    assert result["ok"] is True
    assert result["mismatches"] == []
