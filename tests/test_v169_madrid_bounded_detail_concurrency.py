from __future__ import annotations

import time

from sources import madrid_idi


def test_madrid_parallel_detail_enrichment_preserves_order_and_counts(monkeypatch):
    rows = [
        {"id": str(i), "title": f"Job {i}", "company": "Org", "url": f"https://example.org/{i}"}
        for i in range(6)
    ]

    class DummySession:
        def close(self):
            pass

    monkeypatch.setattr(madrid_idi, "make_retry_session", lambda *a, **k: DummySession())

    def fake_fetch(row, session, timeout):
        time.sleep(0.05)
        row["poem_api_url"] = f"https://api.example/{row['id']}"
        return f"detail-{row['id']}", "OK", row["url"], "poem_api"

    monkeypatch.setattr(madrid_idi, "_fetch_detail_candidates", fake_fetch)
    diag = {
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "detail_resolved_via_external": 0,
        "detail_resolved_via_poem": 0,
        "detail_resolved_via_poem_api": 0,
        "detail_resolved_via_external_api_link": 0,
        "poem_api_success": 0,
        "poem_api_failed": 0,
        "poem_api_partial": 0,
        "external_detail_mismatches": 0,
    }

    started = time.monotonic()
    madrid_idi._enrich_detail_rows(rows, diag, timeout=(1, 1), detail_workers=3)
    elapsed = time.monotonic() - started

    assert [row["full_detail"] for row in rows] == [f"detail-{i}" for i in range(6)]
    assert diag["detail_workers"] == 3
    assert diag["detail_attempts"] == 6
    assert diag["detail_success"] == 6
    assert diag["detail_failed"] == 0
    assert diag["poem_api_success"] == 6
    assert diag["detail_resolved_via_poem_api"] == 6
    # Six 50ms tasks would take ~300ms sequentially; bounded concurrency should be
    # comfortably below that while remaining deterministic in output order.
    assert elapsed < 0.24


def test_production_madrid_defaults_to_six_detail_workers():
    import run_live_sample
    parser = run_live_sample.build_parser()
    args = parser.parse_args(["--source", "madrid", "--no-state"])
    assert args.madrid_detail_workers == 6
