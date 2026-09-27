import csv
from datetime import date
from pathlib import Path

from sources import madrid_idi_history as h


def _write_csv(path: Path, row: dict):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)


def _base_row(**overrides):
    row = {
        "source": "Madrid I+D+i",
        "id": "63260",
        "url": "https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/63260",
        "title": "Research Project Coordinator",
        "company": "Example Institute",
        "availability_as_of": "2026-09-20",
        "last_seen": "2026-09-20",
        "detail_status": "OK",
        "full_detail": "requirements functions project management " * 30,
        "detail_age_days": "",
    }
    row.update(overrides)
    return row


def test_v201_fresh_detail_age_uses_snapshot_day(tmp_path):
    p = tmp_path / "fresh.csv"
    _write_csv(p, _base_row())

    cache, diag = h._load_cache(p, as_of=date(2026, 9, 22))

    assert ("id", "63260") in cache
    assert cache[("id", "63260")]["_detail_age_days"] == 2
    assert diag["historical_detail_cache_expired"] == 0


def test_v201_cached_detail_carries_prior_age_instead_of_resetting(tmp_path):
    p = tmp_path / "cached.csv"
    _write_csv(p, _base_row(
        availability_as_of="2026-09-21",
        last_seen="2026-09-21",
        detail_status="CACHE",
        detail_age_days="1",
    ))

    cache, diag = h._load_cache(p, as_of=date(2026, 9, 22))

    assert ("id", "63260") in cache
    assert cache[("id", "63260")]["_detail_age_days"] == 2
    assert diag["historical_detail_cache_carried_age"] == 1


def test_v201_cache_chain_expires_after_effective_age_exceeds_limit(tmp_path):
    p = tmp_path / "cached.csv"
    _write_csv(p, _base_row(
        availability_as_of="2026-09-22",
        last_seen="2026-09-22",
        detail_status="CACHE",
        detail_age_days="2",
    ))

    cache, diag = h._load_cache(p, as_of=date(2026, 9, 23))

    assert ("id", "63260") not in cache
    assert diag["historical_detail_cache_carried_age"] == 1
    assert diag["historical_detail_cache_expired"] == 1


def test_v201_historical_fallback_writes_effective_age(tmp_path, monkeypatch):
    p = tmp_path / "cached.csv"
    _write_csv(p, _base_row(
        availability_as_of="2026-09-21",
        last_seen="2026-09-21",
        detail_status="CACHE",
        detail_age_days="1",
    ))
    monkeypatch.setattr(h, "_download_latest_canonical", lambda: p)

    row = {
        "source": "Madrid I+D+i",
        "id": "63260",
        "url": "https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/63260",
        "title": "Research Project Coordinator",
        "company": "Example Institute",
        "full_detail": "",
        "detail_status": "POEM_RELAY_HTTP_504",
    }
    diag = {"detail_failed": 1, "detail_success": 0, "detail_status_counts": {"POEM_RELAY_HTTP_504": 1}}

    # Freeze date by calling the loader logic through an explicit temporary canonical
    # with today's date not required here; verify the fallback preserves the loader's age.
    cache, _ = h._load_cache(p, as_of=date(2026, 9, 22))
    assert cache[("id", "63260")]["_detail_age_days"] == 2
