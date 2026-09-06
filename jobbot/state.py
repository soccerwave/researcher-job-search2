from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .normalize import normalize

STATE_VERSION = "V1.39_SEEN_HISTORY_V2"
LEGACY_STATE_VERSIONS = {"V1.38_SEEN_HISTORY_V1"}
VALID_DETAIL_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "CACHE", "OK"}
OPEN_STATUSES = {"OPEN", "OPEN_UNTIL_FILLED"}


def _norm_text(value) -> str:
    return normalize(str(value or "")).strip()


def _normalized_url(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.lower().rstrip("/")
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = f"{host}:{port}" if port else host
    path = re.sub(r"/{2,}", "/", parts.path or "/").rstrip("/") or "/"
    # Preserve identity-bearing SPA routes, but drop normal tracking fragments/query.
    fragment = ""
    m = re.search(r"(?:^|/)ver-oferta/(\d+)(?:$|[/?])", parts.fragment or "", re.I)
    if m:
        fragment = f"/ver-oferta/{m.group(1)}"
    return urlunsplit((scheme, netloc, path + fragment, "", "")).rstrip("/")


def _is_generic_listing_url(url: str) -> bool:
    if not url:
        return False
    try:
        path = urlsplit(url).path.lower().rstrip("/")
    except ValueError:
        path = url.lower().rstrip("/")
    generic_endings = (
        "/jobs", "/job", "/careers", "/career", "/vacancies", "/vacancy",
        "/job-openings", "/job-opportunities", "/employment", "/opportunities",
    )
    return path in {"", "/"} or path.endswith(generic_endings)


def _source_token(value) -> str:
    return _norm_text(value).replace(" ", "_")


def _aliases(job: dict) -> list[tuple[int, str]]:
    """Return conservative state aliases ordered strongest to weakest.

    Generic careers/listing URLs are never a standalone alias because several distinct
    vacancies can legitimately share them. They are paired with the title instead.
    """
    aliases: list[tuple[int, str]] = []

    provenance = job.get("source_provenance") or []
    records = [p for p in provenance if isinstance(p, dict)]
    if not records:
        records = [{"source": job.get("source"), "id": job.get("id"), "url": job.get("url")}]

    for record in records:
        source = _source_token(record.get("source"))
        stable_id = str(record.get("id") or "").strip()
        if source and stable_id:
            aliases.append((0, f"source_id:{source}:{stable_id.lower()}"))

    urls: list[str] = []
    for value in [job.get("url"), job.get("trusted_full_detail_url"), *(job.get("alternate_urls") or [])]:
        normalized = _normalized_url(value)
        if normalized and normalized not in urls:
            urls.append(normalized)
    for record in records:
        normalized = _normalized_url(record.get("url"))
        if normalized and normalized not in urls:
            urls.append(normalized)

    title = _norm_text(job.get("title"))
    for url in urls:
        if _is_generic_listing_url(url):
            if title:
                aliases.append((2, f"listing_title:{url}:{title}"))
        else:
            aliases.append((1, f"url:{url}"))

    company = _norm_text(job.get("company"))
    location = _norm_text(job.get("location"))
    if title and company:
        aliases.append((3, f"ctl:{company}:{title}:{location}"))

    seen: set[str] = set()
    out: list[tuple[int, str]] = []
    for rank, alias in sorted(aliases, key=lambda item: item[0]):
        if alias and alias not in seen:
            seen.add(alias)
            out.append((rank, alias))
    return out


def _state_id_for_alias(alias: str) -> str:
    return "job_" + hashlib.sha1(alias.encode("utf-8")).hexdigest()[:20]


def _detail_simhash(detail: str) -> str:
    tokens = _norm_text(detail).split()
    if len(tokens) < 25:
        return ""
    shingles = [" ".join(tokens[i:i + 3]) for i in range(len(tokens) - 2)]
    vector = [0] * 64
    for shingle in shingles:
        digest = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            vector[bit] += 1 if (value >> bit) & 1 else -1
    result = 0
    for bit, score in enumerate(vector):
        if score >= 0:
            result |= 1 << bit
    return f"{result:016x}"


def _snapshot(job: dict) -> dict:
    detail_status = str(job.get("detail_status") or "")
    detail = str(job.get("full_detail") or "") if detail_status in VALID_DETAIL_STATUSES else ""
    score = job.get("score")
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = None
    return {
        "title": _norm_text(job.get("title")),
        "company": _norm_text(job.get("company")),
        "location": _norm_text(job.get("location")),
        "modality": _norm_text(job.get("modality")),
        "application_deadline": str(job.get("application_deadline") or "").strip(),
        "application_status": str(job.get("application_status") or "UNKNOWN").strip().upper(),
        "recommendation": str(job.get("recommendation") or "").strip(),
        "score": score,
        "detail_status": detail_status,
        "detail_simhash": _detail_simhash(detail),
        "detail_words": len(_norm_text(detail).split()) if detail else 0,
    }


def _simhash_distance(a: str, b: str) -> int:
    if not a or not b:
        return 0
    return (int(a, 16) ^ int(b, 16)).bit_count()


def _detail_resolved(snapshot: dict) -> bool:
    return (
        str(snapshot.get("detail_status") or "") in VALID_DETAIL_STATUSES
        and int(snapshot.get("detail_words") or 0) > 0
    )


def _quality_events(previous: dict, current: dict) -> list[str]:
    old_resolved = _detail_resolved(previous)
    new_resolved = _detail_resolved(current)
    if not old_resolved and new_resolved:
        return ["DETAIL_RESOLVED"]
    if old_resolved and not new_resolved:
        return ["DETAIL_UNRESOLVED"]
    return []


def _change_reasons(previous: dict, current: dict) -> list[str]:
    """Return vacancy-level material changes, excluding fetch-quality noise.

    A transient Full-JD resolution failure/recovery is a collection-quality event, not a
    change to the vacancy itself. When a previously resolved vacancy becomes unresolved,
    detail-derived metadata can fall back to weaker listing values (for example a generic
    location, a missing deadline, or a default OPEN status). Those degradations must not
    be reported as vacancy changes. Title/company remain comparable because they are the
    stable listing identity fields used by collectors even when detail resolution fails.
    """
    reasons: list[str] = []
    detail_degraded = _detail_resolved(previous) and not _detail_resolved(current)
    fields = ("title", "company") if detail_degraded else (
        "title", "company", "location", "modality", "application_deadline", "application_status"
    )
    for field in fields:
        old = previous.get(field)
        new = current.get(field)
        if old != new and (old or new):
            reasons.append(field)

    if _detail_resolved(previous) and _detail_resolved(current):
        old_rec = str(previous.get("recommendation") or "")
        new_rec = str(current.get("recommendation") or "")
        if old_rec and new_rec and old_rec != new_rec:
            reasons.append("recommendation")

        old_hash = str(previous.get("detail_simhash") or "")
        new_hash = str(current.get("detail_simhash") or "")
        if old_hash and new_hash and _simhash_distance(old_hash, new_hash) >= 14:
            reasons.append("full_detail")

    return reasons


def _snapshot_for_storage(previous: dict, current: dict) -> dict:
    """Retain the last trustworthy enriched snapshot across a transient detail failure."""
    if not previous or _detail_resolved(current) or not _detail_resolved(previous):
        return current
    merged = dict(current)
    # These fields may be enriched or availability-derived from Full JD. If resolution
    # temporarily fails, storing weaker fallback values would create false changes on this
    # run and again when detail later recovers. Keep the last resolved values instead.
    for field in (
        "location", "modality", "application_deadline", "application_status",
        "recommendation", "score", "detail_status", "detail_simhash", "detail_words",
    ):
        merged[field] = previous.get(field)
    # Never replace a known identity value with an empty fallback on a degraded fetch.
    for field in ("title", "company"):
        if not merged.get(field) and previous.get(field):
            merged[field] = previous.get(field)
    return merged


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"state_version": STATE_VERSION, "updated_at": None, "jobs": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Seen-state file is unreadable/corrupt: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
        raise RuntimeError(f"Seen-state file has invalid schema: {path}")
    version = str(data.get("state_version") or "")
    if version and version != STATE_VERSION and version not in LEGACY_STATE_VERSIONS:
        raise RuntimeError(f"Unsupported seen-state version {version!r}; expected {STATE_VERSION!r}")
    # V1.38 -> V1.39 is schema-compatible. Upgrade in memory and persist atomically
    # after the next successful production run; users do not need to delete/reseed state.
    data["state_version"] = STATE_VERSION
    return data


def _alias_index(jobs: dict) -> dict[str, str | None]:
    index: dict[str, str | None] = {}
    for state_id, entry in jobs.items():
        for alias in entry.get("aliases") or []:
            if alias in index and index[alias] != state_id:
                index[alias] = None  # ambiguous aliases must never merge state records
            else:
                index[alias] = state_id
    return index


def apply_seen_state(rows: list[dict], state_path: Path, as_of: str) -> dict:
    """Annotate canonical rows and atomically persist seen/history state."""
    state = load_state(state_path)
    jobs = state["jobs"]
    index = _alias_index(jobs)

    counts = {"NEW": 0, "SEEN": 0, "MATERIALLY_CHANGED": 0, "REOPENED": 0}

    for row in rows:
        quality_events: list[str] = []
        aliases_ranked = _aliases(row)
        aliases = [alias for _, alias in aliases_ranked]
        matched_id = None
        for _, alias in aliases_ranked:
            candidate = index.get(alias)
            if candidate:
                matched_id = candidate
                break

        current_snapshot = _snapshot(row)
        if matched_id is None:
            seed = aliases[0] if aliases else "fallback:" + hashlib.sha1(json.dumps(current_snapshot, sort_keys=True).encode()).hexdigest()
            matched_id = _state_id_for_alias(seed)
            suffix = 1
            base_id = matched_id
            while matched_id in jobs:
                matched_id = f"{base_id}_{suffix}"
                suffix += 1
            entry = {
                "aliases": aliases,
                "first_seen": as_of,
                "last_seen": as_of,
                "times_seen": 1,
                "last_snapshot": current_snapshot,
            }
            jobs[matched_id] = entry
            status = "NEW"
            reasons: list[str] = []
        else:
            entry = jobs[matched_id]
            previous = entry.get("last_snapshot") or {}
            reasons = _change_reasons(previous, current_snapshot)
            quality_events = _quality_events(previous, current_snapshot)
            was_closed = str(previous.get("application_status") or "").upper() == "CLOSED"
            now_open = current_snapshot.get("application_status") in OPEN_STATUSES
            detail_degraded = "DETAIL_UNRESOLVED" in quality_events
            if was_closed and now_open and not detail_degraded:
                status = "REOPENED"
                if "application_status" not in reasons:
                    reasons.insert(0, "application_status")
            elif reasons:
                status = "MATERIALLY_CHANGED"
            else:
                status = "SEEN"

            merged_aliases = list(entry.get("aliases") or [])
            for alias in aliases:
                if alias not in merged_aliases:
                    merged_aliases.append(alias)
                    if alias not in index:
                        index[alias] = matched_id
            entry.update({
                "aliases": merged_aliases,
                "last_seen": as_of,
                "times_seen": int(entry.get("times_seen", 0) or 0) + 1,
                "last_snapshot": _snapshot_for_storage(previous, current_snapshot),
            })

        counts[status] += 1
        entry = jobs[matched_id]
        row["seen_status"] = status
        row["change_reasons"] = reasons
        row["state_events"] = quality_events
        row["first_seen"] = entry.get("first_seen") or as_of
        row["last_seen"] = as_of
        row["times_seen"] = entry.get("times_seen", 1)
        row["state_id"] = matched_id

    state["updated_at"] = as_of
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temp_path, state_path)

    detail_resolved = sum("DETAIL_RESOLVED" in (row.get("state_events") or []) for row in rows)
    detail_unresolved = sum("DETAIL_UNRESOLVED" in (row.get("state_events") or []) for row in rows)
    return {
        **counts,
        "DETAIL_RESOLVED": detail_resolved,
        "DETAIL_UNRESOLVED": detail_unresolved,
        "state_jobs": len(jobs),
        "state_file": str(state_path),
    }
