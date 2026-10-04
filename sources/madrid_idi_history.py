from __future__ import annotations

import csv
import gzip
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import madrid_idi as base

HISTORICAL_DETAIL_MAX_AGE_DAYS = 2
VALID_DETAIL_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}
LATEST_CANONICAL_KEY = "latest/all_canonical.csv.gz"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    import unicodedata
    import re

    text = unicodedata.normalize("NFKD", _clean(value).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _normalized_url(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.lower().rstrip("/")
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parts.path or "/").rstrip("/")
    fragment = (parts.fragment or "").rstrip("/")
    joined = urlunsplit(((parts.scheme or "https").lower(), host, path, "", fragment))
    return joined.lower().rstrip("/")


def _identity_key(row: dict) -> tuple[str, str]:
    stable_id = _clean(row.get("id")).lower()
    if stable_id:
        return ("id", stable_id)
    url = _normalized_url(row.get("url"))
    return ("url", url) if url else ("", "")


def _snapshot_day(row: dict) -> date | None:
    for key in ("availability_as_of", "last_seen"):
        raw = _clean(row.get(key))
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw[:10]).date()
        except ValueError:
            continue
    return None


def _download_latest_canonical() -> Path | None:
    explicit = _clean(os.environ.get("MADRID_HISTORY_CANONICAL_PATH"))
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None

    required = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    if not all(_clean(os.environ.get(name)) for name in required):
        return None

    try:
        import boto3

        account_id = _clean(os.environ.get("R2_ACCOUNT_ID"))
        endpoint = _clean(os.environ.get("R2_ENDPOINT"))
        if not endpoint and account_id:
            endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        if not endpoint:
            return None

        target = Path(tempfile.gettempdir()) / "madrid_previous_all_canonical.csv.gz"
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
        s3.download_file(os.environ["R2_BUCKET"], LATEST_CANONICAL_KEY, str(target))
        return target
    except Exception:
        return None


def _load_cache(path: Path | None, as_of: date | None = None) -> tuple[dict[tuple[str, str], dict], dict]:
    diag = {
        "historical_detail_cache_path": str(path or ""),
        "historical_detail_cache_loaded": 0,
        "historical_detail_cache_eligible": 0,
        "historical_detail_cache_error": "",
        "historical_detail_cache_expired": 0,
        "historical_detail_cache_carried_age": 0,
    }
    if not path or not path.exists():
        return {}, diag

    today = as_of or date.today()
    cache: dict[tuple[str, str], dict] = {}
    try:
        opener = gzip.open if path.suffix.lower() == ".gz" else open
        with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                diag["historical_detail_cache_loaded"] += 1
                if "Madrid I+D+i" not in _clean(row.get("source")):
                    continue
                detail = str(row.get("full_detail") or "").strip()
                if not detail or _clean(row.get("detail_status")) not in VALID_DETAIL_STATUSES:
                    continue
                snapshot_day = _snapshot_day(row)
                if snapshot_day is None:
                    continue
                snapshot_age_days = (today - snapshot_day).days
                if snapshot_age_days < 0:
                    continue

                # CACHE rows may themselves have been created from an older fallback.
                # Carry forward the original detail age instead of resetting freshness
                # to the date of the most recent canonical snapshot.
                prior_detail_age = 0
                if _clean(row.get("detail_status")) == "CACHE":
                    try:
                        prior_detail_age = max(0, int(float(_clean(row.get("detail_age_days")) or 0)))
                    except (TypeError, ValueError):
                        prior_detail_age = 0
                age_days = snapshot_age_days + prior_detail_age
                if prior_detail_age:
                    diag["historical_detail_cache_carried_age"] += 1
                if age_days > HISTORICAL_DETAIL_MAX_AGE_DAYS:
                    diag["historical_detail_cache_expired"] += 1
                    continue
                key = _identity_key(row)
                if not key[0]:
                    continue
                cached = dict(row)
                cached["_detail_age_days"] = age_days
                prior = cache.get(key)
                if prior is None or age_days < int(prior.get("_detail_age_days") or 999):
                    cache[key] = cached
        diag["historical_detail_cache_eligible"] = len(cache)
    except Exception as exc:
        diag["historical_detail_cache_error"] = f"{type(exc).__name__}: {exc}"
        return {}, diag
    return cache, diag


def _match_current_to_history(row: dict, cache: dict[tuple[str, str], dict]) -> dict | None:
    key = _identity_key(row)
    if not key[0]:
        return None
    previous = cache.get(key)
    if not previous:
        return None

    current_title = _norm(row.get("title"))
    previous_title = _norm(previous.get("title"))
    if not current_title or not previous_title or current_title != previous_title:
        return None

    current_company = _norm(row.get("company"))
    previous_company = _norm(previous.get("company"))
    if current_company and previous_company and current_company != previous_company:
        return None
    return previous


def _apply_historical_fallback(rows: list[dict], diagnostics: dict) -> None:
    path = _download_latest_canonical()
    cache, cache_diag = _load_cache(path)
    diagnostics.update(cache_diag)
    diagnostics["historical_fallback_attempted"] = 0
    diagnostics["historical_fallback_used"] = 0
    diagnostics["historical_fallback_rejected"] = 0
    recovered_fetch_statuses = []

    if not cache:
        return

    for row in rows:
        detail = str(row.get("full_detail") or "").strip()
        status = _clean(row.get("detail_status"))
        if detail and status in VALID_DETAIL_STATUSES:
            continue

        diagnostics["historical_fallback_attempted"] += 1
        previous = _match_current_to_history(row, cache)
        if not previous:
            diagnostics["historical_fallback_rejected"] += 1
            continue

        previous_detail = str(previous.get("full_detail") or "").strip()
        if not previous_detail:
            diagnostics["historical_fallback_rejected"] += 1
            continue

        fresh_status = status
        resolved_url = (
            _clean(previous.get("detail_resolved_url"))
            or _clean(previous.get("trusted_full_detail_url"))
            or _clean(previous.get("url"))
        )
        row["full_detail"] = previous_detail
        row["detail_fetch_status"] = fresh_status
        recovered_fetch_statuses.append(fresh_status)
        row["detail_status"] = "CACHE"
        row["detail_source"] = "historical_fallback"
        row["detail_resolution_method"] = "historical_fallback"
        row["detail_age_days"] = int(previous.get("_detail_age_days") or 0)
        row["trusted_full_detail_source"] = "Madrid I+D+i historical fallback"
        if resolved_url:
            row["detail_resolved_url"] = resolved_url
            row["trusted_full_detail_url"] = resolved_url
        diagnostics["historical_fallback_used"] += 1

    used = int(diagnostics.get("historical_fallback_used", 0) or 0)
    if used:
        diagnostics["fresh_detail_failed"] = int(diagnostics.get("detail_failed", 0) or 0)
        diagnostics["detail_failed"] = max(0, int(diagnostics.get("detail_failed", 0) or 0) - used)
        diagnostics["detail_success"] = int(diagnostics.get("detail_success", 0) or 0) + used
        counts = dict(diagnostics.get("detail_status_counts") or {})
        for fresh_status in recovered_fetch_statuses:
            if fresh_status in counts:
                counts[fresh_status] = max(0, int(counts.get(fresh_status, 0) or 0) - 1)
                if counts[fresh_status] == 0:
                    counts.pop(fresh_status, None)
        counts["CACHE"] = int(counts.get("CACHE", 0) or 0) + used
        diagnostics["detail_status_counts"] = counts


def _prefill_recent_history(rows: list[dict], diagnostics: dict) -> tuple[list[dict], list[dict]]:
    """Reuse strict recent Full JD cache before the fragile POEM relay.

    Only the same stable vacancy identity with the same normalized title and company is
    eligible, and the existing two-day effective-age policy still applies. Cache hits
    remain explicitly CACHE, never masquerading as fresh network fetches.
    """
    path = _download_latest_canonical()
    cache, cache_diag = _load_cache(path)
    diagnostics.update(cache_diag)
    diagnostics["historical_prefill_attempted"] = len(rows)
    diagnostics["historical_prefill_used"] = 0
    diagnostics["historical_prefill_rejected"] = 0
    hits, misses = [], []
    for row in rows:
        previous = _match_current_to_history(row, cache) if cache else None
        previous_detail = str((previous or {}).get("full_detail") or "").strip()
        if not previous or not previous_detail:
            diagnostics["historical_prefill_rejected"] += 1
            misses.append(row)
            continue
        resolved_url = (
            _clean(previous.get("detail_resolved_url"))
            or _clean(previous.get("trusted_full_detail_url"))
            or _clean(previous.get("url"))
        )
        row["full_detail"] = previous_detail
        row["detail_status"] = "CACHE"
        row["detail_fetch_status"] = "CACHE_PREFILL"
        row["detail_source"] = "historical_prefill"
        row["detail_resolution_method"] = "historical_prefill"
        row["detail_age_days"] = int(previous.get("_detail_age_days") or 0)
        row["trusted_full_detail_source"] = "Madrid I+D+i historical prefill"
        if resolved_url:
            row["detail_resolved_url"] = resolved_url
            row["trusted_full_detail_url"] = resolved_url
        diagnostics["historical_prefill_used"] += 1
        hits.append(row)
    return hits, misses


def _rescue_remaining_fresh_misses(rows: list[dict], diagnostics: dict) -> None:
    """One bounded third attempt only for transient no-cache relay failures."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = [
        row for row in rows
        if base._is_retryable_relay_failure(_clean(row.get("detail_status")))
    ]
    diagnostics["final_rescue_candidates"] = len(candidates)
    diagnostics["final_rescue_attempts"] = 0
    diagnostics["final_rescue_workers"] = 0
    diagnostics["final_rescue_success"] = 0
    diagnostics["final_rescue_failed"] = 0
    if not candidates:
        return

    time.sleep(2.0)
    diagnostics["final_rescue_attempts"] = len(candidates)
    workers = min(2, len(candidates))
    diagnostics["final_rescue_workers"] = workers
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="madrid-final-rescue") as pool:
        futures = {
            pool.submit(base._resolve_detail_row, i, row, (10, 45)): row
            for i, row in enumerate(candidates)
        }
        for future in as_completed(futures):
            row = futures[future]
            old_status = _clean(row.get("detail_status"))
            try:
                _, detail, status, resolved_url, method = future.result()
            except Exception as exc:
                detail = ""
                status = f"DETAIL_WORKER_FAILED: {type(exc).__name__}: {exc}"
                resolved_url = ""
                method = "worker_failed"

            row["full_detail"] = detail
            row["detail_status"] = status
            row["detail_resolution_method"] = method
            row["final_rescue_attempted"] = True
            if resolved_url:
                row["detail_resolved_url"] = resolved_url

            if detail and status in base._OK_DETAIL_STATUSES:
                diagnostics["final_rescue_success"] += 1
                diagnostics["detail_failed"] = max(0, int(diagnostics.get("detail_failed", 0) or 0) - 1)
                diagnostics["detail_success"] = int(diagnostics.get("detail_success", 0) or 0) + 1
                if method == "poem_api":
                    diagnostics["poem_api_success"] = int(diagnostics.get("poem_api_success", 0) or 0) + 1
                    diagnostics["detail_resolved_via_poem_api"] = int(diagnostics.get("detail_resolved_via_poem_api", 0) or 0) + 1
                    diagnostics["detail_resolved_via_poem"] = int(diagnostics.get("detail_resolved_via_poem", 0) or 0) + 1
                elif method == "external_from_poem_api":
                    diagnostics["detail_resolved_via_external_api_link"] = int(diagnostics.get("detail_resolved_via_external_api_link", 0) or 0) + 1
                    diagnostics["detail_resolved_via_external"] = int(diagnostics.get("detail_resolved_via_external", 0) or 0) + 1

                counts = dict(diagnostics.get("detail_status_counts") or {})
                if old_status in counts:
                    counts[old_status] = max(0, int(counts.get(old_status, 0) or 0) - 1)
                    if counts[old_status] == 0:
                        counts.pop(old_status, None)
                counts[status] = int(counts.get(status, 0) or 0) + 1
                diagnostics["detail_status_counts"] = counts
            else:
                diagnostics["final_rescue_failed"] += 1


def collect(*args, diagnostics: dict | None = None, **kwargs) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    enrich_detail = bool(kwargs.pop("enrich_detail", True))
    if not enrich_detail:
        return base.collect(*args, diagnostics=diag, enrich_detail=False, **kwargs)

    rows = base.collect(*args, diagnostics=diag, enrich_detail=False, **kwargs)
    hits, misses = _prefill_recent_history(rows, diag)
    cache_count = len(hits)

    diag["detail_success"] = 0
    diag["detail_failed"] = 0
    diag["detail_attempts"] = 0
    diag["detail_status_counts"] = {}
    diag["fresh_detail_attempts"] = len(misses)

    if misses:
        workers = int(kwargs.get("detail_workers", 1) or 1)
        base._enrich_detail_rows(misses, diag, timeout=(10, 45), detail_workers=workers)
        _rescue_remaining_fresh_misses(misses, diag)

    counts = dict(diag.get("detail_status_counts") or {})
    if cache_count:
        counts["CACHE"] = int(counts.get("CACHE", 0) or 0) + cache_count
    diag["detail_status_counts"] = counts
    diag["detail_success"] = int(diag.get("detail_success", 0) or 0) + cache_count
    diag["fresh_detail_failed"] = int(diag.get("detail_failed", 0) or 0)

    _apply_historical_fallback(rows, diag)
    return rows
