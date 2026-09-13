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
                age_days = (today - snapshot_day).days
                if age_days < 0 or age_days > HISTORICAL_DETAIL_MAX_AGE_DAYS:
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


def collect(*args, diagnostics: dict | None = None, **kwargs) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    rows = base.collect(*args, diagnostics=diag, **kwargs)
    _apply_historical_fallback(rows, diag)
    return rows
