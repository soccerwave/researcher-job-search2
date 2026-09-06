from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .normalize import normalize


_VALID_DETAIL_STATUSES = {
    "OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "CACHE", "OK"
}


def _detail_ok(job: dict) -> bool:
    status = str(job.get("detail_status") or "")
    detail = str(job.get("full_detail") or "").strip()
    return bool(detail) and status in _VALID_DETAIL_STATUSES


_IDENTITY_QUERY_KEYS = {
    "id", "jobid", "job_id", "job-id", "vacancyid", "vacancy_id",
    "offerid", "offer_id", "ofertaid", "oferta_id", "idoferta", "id_oferta", "convocatoriaid",
    "convocatoria_id", "positionid", "position_id", "requisitionid",
    "requisition_id", "reqid", "req_id",
}


def _normalized_url(job: dict) -> str:
    raw = str(job.get("url") or "").strip()
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

    # Most query parameters are tracking/filter/pagination noise. Preserve only
    # explicit vacancy-identity keys. This is required for portals whose detail
    # endpoint is shared and the actual vacancy identity lives in ?id=... .
    identity_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        if key.lower() in _IDENTITY_QUERY_KEYS and str(value).strip():
            identity_pairs.append((key.lower(), str(value).strip().lower()))
    identity_pairs.sort()
    query = urlencode(identity_pairs)

    # Hash-routed SPAs can also carry job identity in the fragment. Madrid POEM
    # is one such case: /poem_webapp/#/ver-oferta/63661.
    fragment = ""
    m = re.search(r"(?:^|/)ver-oferta/(\d+)(?:$|[/?])", parts.fragment or "", re.I)
    if m:
        fragment = f"/ver-oferta/{m.group(1)}"

    normalized = urlunsplit((scheme, netloc, path + fragment, query, ""))
    return normalized.rstrip("/")


def _word_shingles(text: str, size: int = 5) -> set[tuple[str, ...]]:
    words = normalize(text).split()
    if len(words) < size:
        return set()
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def _detail_containment(a: dict, b: dict) -> float:
    """Containment of the smaller JD in the larger JD.

    This is intentionally used only after both collectors have validated the pages as
    real job descriptions. It is robust to portal wrappers and employer boilerplate,
    while avoiding fuzzy matching on generic career/index pages.
    """
    if not (_detail_ok(a) and _detail_ok(b)):
        return 0.0
    sa = _word_shingles(str(a.get("full_detail") or ""))
    sb = _word_shingles(str(b.get("full_detail") or ""))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def _reference_tokens(title: str) -> set[str]:
    """Extract reference-like IDs that distinguish parallel vacancies.

    Example: HRER2026/329-159 and HRER2026/328-158 are separate positions even
    though the surrounding title and most project boilerplate are nearly identical.
    """
    raw = str(title or "").upper()
    patterns = [
        r"\b\d{2,4}[/-]\d{2,4}(?:[-_/][A-Z0-9]{1,12})+\b",
        r"\b[A-Z]{2,12}\d{2,4}[/-]\d{2,4}(?:[-_/][A-Z0-9]{1,12})*\b",
        r"\b(?:REF(?:ERENCE)?[.: _-]*)[A-Z0-9][A-Z0-9/_-]{3,}\b",
    ]
    out: set[str] = set()
    for pat in patterns:
        for token in re.findall(pat, raw):
            out.add(re.sub(r"\s+", "", token))
    return out


def _same_job(a: dict, b: dict) -> bool:
    """Conservative cross-source identity test.

    Strong rules only. Distinct reference IDs always prevent a fuzzy merge. Validated
    JD overlap is required whenever two resolved postings do not share the same URL;
    this protects parallel vacancies with similar institutional/project boilerplate.
    """
    ua, ub = _normalized_url(a), _normalized_url(b)
    if ua and ub and ua == ub:
        return True

    # Distinct stable IDs from the *same source* are strong evidence that the portal
    # considers these separate postings. Do not collapse them merely because titles,
    # employers and Full-JD boilerplate are highly similar. This is especially
    # important for public research boards where parallel/reposted vacancies can share
    # most of their text. Cross-source records remain eligible for conservative merging.
    source_a = str(a.get("source") or "").strip().lower()
    source_b = str(b.get("source") or "").strip().lower()
    id_a = str(a.get("id") or "").strip()
    id_b = str(b.get("id") or "").strip()
    if source_a and source_a == source_b and id_a and id_b and id_a != id_b:
        return False

    ta, tb = normalize(a.get("title", "")), normalize(b.get("title", ""))
    if not ta or not tb:
        return False

    refs_a = _reference_tokens(str(a.get("title") or ""))
    refs_b = _reference_tokens(str(b.get("title") or ""))
    if refs_a and refs_b and refs_a.isdisjoint(refs_b):
        return False

    title_exact = ta == tb
    title_ratio = SequenceMatcher(None, ta, tb).ratio()
    if not title_exact and title_ratio < 0.92:
        return False

    ca, cb = normalize(a.get("company", "")), normalize(b.get("company", ""))
    company_close = False
    if ca and cb:
        company_ratio = SequenceMatcher(None, ca, cb).ratio()
        company_close = ca == cb or company_ratio >= 0.90

    both_resolved = _detail_ok(a) and _detail_ok(b)
    containment = _detail_containment(a, b) if both_resolved else 0.0

    # Same title + same/near employer: resolved records still need JD agreement.
    if title_exact and company_close:
        if both_resolved:
            return containment >= 0.55
        # Allow enrichment of an unresolved record only across different sources and
        # only when location is not contradictory.
        if str(a.get("source") or "") != str(b.get("source") or ""):
            la, lb = normalize(a.get("location", "")), normalize(b.get("location", ""))
            return not (la and lb and la != lb)
        return False

    # Legal/short organisation names can differ a lot; identical titles plus highly
    # overlapping validated JDs are sufficient without a company alias dictionary.
    if title_exact and containment >= 0.70:
        return True

    # Fuzzy titles are deliberately stricter.
    if title_ratio >= 0.96 and containment >= 0.78:
        return True
    return False

def _quality(job: dict) -> tuple[int, int, int]:
    """Prefer resolved/richer records when two sources describe the same job."""
    detail = str(job.get("full_detail") or "").strip()
    metadata = sum(bool(str(job.get(k) or "").strip()) for k in ("company", "location", "date"))
    return (1 if _detail_ok(job) else 0, len(detail), metadata)


def _merge_jobs(a: dict, b: dict) -> dict:
    best, other = (a, b) if _quality(a) >= _quality(b) else (b, a)
    merged = dict(best)

    # Fill missing metadata without replacing the richer source's values.
    for key in ("company", "location", "date", "modality", "description", "search_query"):
        if not str(merged.get(key) or "").strip() and str(other.get(key) or "").strip():
            merged[key] = other.get(key)

    sources = []
    for src in (a.get("source"), b.get("source")):
        src = str(src or "").strip()
        if src and src not in sources:
            sources.append(src)
    if len(sources) > 1:
        merged["source"] = "+".join(sources)
        merged["also_seen_in"] = sources

    urls = []
    for u in (a.get("url"), b.get("url")):
        u = str(u or "").strip()
        if u and u not in urls:
            urls.append(u)
    if len(urls) > 1:
        merged["alternate_urls"] = urls

    # V1.37 production metadata only: preserve where each representation came from
    # and which source supplied the canonical Full JD. This does not change identity
    # matching, quality ranking, or any scoring input.
    provenance = []
    for record in (a, b):
        entries = record.get("source_provenance") or [{
            "source": str(record.get("source") or ""),
            "id": str(record.get("id") or ""),
            "url": str(record.get("url") or ""),
            "detail_status": str(record.get("detail_status") or ""),
        }]
        for entry in entries:
            if entry not in provenance:
                provenance.append(entry)
    if provenance:
        merged["source_provenance"] = provenance

    if _detail_ok(best):
        merged["trusted_full_detail_source"] = best.get("trusted_full_detail_source") or best.get("source")
        merged["trusted_full_detail_url"] = best.get("trusted_full_detail_url") or best.get("url")

    return merged


def fingerprint(job: dict) -> str:
    """Stable fallback fingerprint; identity matching itself is handled in deduplicate."""
    url = _normalized_url(job)
    if url:
        base = url
    else:
        base = "::".join([
            normalize(job.get("company", "")),
            normalize(job.get("title", "")),
            normalize(job.get("location", "")),
        ])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def deduplicate(jobs: list[dict]) -> tuple[list[dict], int]:
    """Conservatively deduplicate both within and across sources, enriching duplicates."""
    unique: list[dict] = []
    removed = 0

    for incoming in jobs:
        job = dict(incoming)
        match_index = None
        for i, existing in enumerate(unique):
            if _same_job(existing, job):
                match_index = i
                break
        if match_index is None:
            unique.append(job)
        else:
            unique[match_index] = _merge_jobs(unique[match_index], job)
            removed += 1

    return unique, removed
