import csv
import json
import zipfile
from pathlib import Path

from jobbot.production import PRODUCTION_VERSION
from scripts.build_cloud_report import _is_madrid_needs_detail, build_report
from scripts.telegram_notify import format_summary


def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0].keys()) if rows else ["source", "title"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def test_v182_production_version():
    assert PRODUCTION_VERSION == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"


def test_madrid_needs_detail_classifier_is_narrow():
    assert _is_madrid_needs_detail({"source": "Madrid I+D+i", "recommendation": "NEEDS_DETAIL_REVIEW"})
    assert not _is_madrid_needs_detail({"source": "Madrid I+D+i", "recommendation": "REVIEW"})
    assert not _is_madrid_needs_detail({"source": "Biocat", "recommendation": "NEEDS_DETAIL_REVIEW"})


def test_report_has_separate_madrid_needs_detail_sheet(tmp_path):
    out = tmp_path / "live_output"
    out.mkdir()
    summary = {
        "production_version": PRODUCTION_VERSION,
        "availability_as_of": "2026-08-30",
        "configured_sources": ["madrid", "biocat"],
        "raw": 2,
        "unique": 2,
        "current_actionable": 2,
        "daily_actionable": 0,
        "new_actionable": 0,
        "changed_or_reopened_actionable": 0,
        "needs_detail_review": 2,
        "seen_state_jobs": 10,
        "errors": [],
        "warnings": [],
        "recommendations": {"STRONG_APPLY": 0, "APPLY": 0, "REVIEW": 0, "LOW_PRIORITY": 0, "SKIP": 0},
        "source_runs": {
            "madrid": {"status": "PARTIAL", "needs_detail_review": 1},
            "biocat": {"status": "PARTIAL", "needs_detail_review": 1},
        },
    }
    (out / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    madrid = {"source": "Madrid I+D+i", "title": "Madrid unresolved", "recommendation": "NEEDS_DETAIL_REVIEW"}
    biocat = {"source": "Biocat", "title": "Biocat unresolved", "recommendation": "NEEDS_DETAIL_REVIEW"}
    for name, rows in {
        "actionable.csv": [madrid, biocat],
        "daily_actionable.csv": [],
        "actionable_primary.csv": [],
        "actionable_low.csv": [],
        "needs_detail_review.csv": [madrid, biocat],
        "source_summary.csv": [],
    }.items():
        _write_csv(out / name, rows)

    report = build_report(out, out / "job_search_report.xlsx")
    with zipfile.ZipFile(report) as zf:
        workbook_xml = zf.read("xl/workbook.xml").decode("utf-8")
        assert "NEEDS_DETAIL" in workbook_xml
        assert "MADRID_NEEDS_DETAIL" in workbook_xml


def test_telegram_summary_exposes_madrid_needs_detail_count():
    text = format_summary({
        "availability_as_of": "2026-08-30",
        "current_actionable": 72,
        "daily_actionable": 0,
        "new_actionable": 0,
        "changed_or_reopened_actionable": 0,
        "needs_detail_review": 41,
        "recommendations": {"APPLY": 2, "REVIEW": 8, "LOW_PRIORITY": 29},
        "source_runs": {
            "madrid": {"status": "PARTIAL", "needs_detail_review": 36},
            "biocat": {"status": "PARTIAL", "needs_detail_review": 4},
            "idibaps": {"status": "PARTIAL", "needs_detail_review": 1},
        },
    })
    assert "Needs detail: 41 | Madrid: 36 | Other: 5" in text
