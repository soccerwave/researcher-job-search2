from pathlib import Path

history = Path("sources/madrid_idi_history.py")
text = history.read_text(encoding="utf-8")
old = '''def collect(*args, diagnostics: dict | None = None, **kwargs) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    rows = base.collect(*args, diagnostics=diag, **kwargs)
    _apply_historical_fallback(rows, diag)
    return rows
'''
new = '''def _prefill_recent_history(rows: list[dict], diagnostics: dict) -> tuple[list[dict], list[dict]]:
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
'''
assert text.count(old) == 1, "unexpected madrid_idi_history.py collect() shape"
history.write_text(text.replace(old, new), encoding="utf-8")

relay = Path("cloudflare-madrid-relay/src/index.js")
relay_text = relay.read_text(encoding="utf-8")
assert relay_text.count("const UPSTREAM_TIMEOUT_MS = 6000;") == 1
relay.write_text(
    relay_text.replace("const UPSTREAM_TIMEOUT_MS = 6000;", "const UPSTREAM_TIMEOUT_MS = 12000;"),
    encoding="utf-8",
)

for name in (
    "tests/test_v172_madrid_relay_backpressure.py",
    "tests/test_v173_madrid_deferred_relay_recovery.py",
):
    path = Path(name)
    value = path.read_text(encoding="utf-8")
    assert value.count('const UPSTREAM_TIMEOUT_MS = 6000;') == 1
    path.write_text(value.replace('const UPSTREAM_TIMEOUT_MS = 6000;', 'const UPSTREAM_TIMEOUT_MS = 12000;'), encoding="utf-8")
