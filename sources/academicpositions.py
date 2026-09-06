from __future__ import annotations

import html as html_lib
import json
import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from sources.common import JobRecord
from sources.fetch_detail import make_retry_session

SOURCE_NAME = "AcademicPositions"
BOARD_URLS = (
    ("international_en", "https://academicpositions.com/jobs/country/spain"),
    ("spain_es", "https://academicpositions.es/jobs/country/spain"),
)
AD_PATH_RE = re.compile(r"^/ad/[^?#]+/(\d+)(?:[/?#]|$)", re.I)
COUNT_RE = re.compile(r"\b(\d+)\s+(?:jobs?|trabajos?)\s+(?:in|en)\s+(?:spain|españa)\b", re.I)
CLOSED_RE = re.compile(
    r"(?:applications?\s+(?:are|is)\s+(?:now\s+)?closed|position\s+(?:has\s+been\s+)?filled|"
    r"vacancy\s+(?:has\s+been\s+)?closed|convocatoria\s+cerrada|proceso\s+(?:de\s+selecci[oó]n\s+)?finalizado)",
    re.I,
)
BLOCK_MARKERS = (
    "just a moment...",
    "checking your browser",
    "verify you are human",
    "cf-chl-",
    "cloudflare ray id",
)
STOP_MARKERS = (
    "Jobs from this employer",
    "About the employer",
    "Find similar jobs",
    "This might interest you",
    "Trabajos de este empleador",
    "Acerca del empleador",
    "Buscar trabajos similares",
    "Esto podría interesarte",
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_blocked_html(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in BLOCK_MARKERS)


def _ad_id_from_url(url: str) -> str:
    try:
        path = urlparse(url).path
    except Exception:
        return ""
    m = AD_PATH_RE.match(path)
    return m.group(1) if m else ""


def _declared_count(soup: BeautifulSoup) -> int | None:
    for heading in soup.find_all(["h1", "h2"]):
        m = COUNT_RE.search(_clean(heading.get_text(" ", strip=True)))
        if m:
            return int(m.group(1))
    return None


def parse_listing(html: str, base_url: str) -> tuple[list[dict], int | None]:
    """Parse only AcademicPositions ad URLs from a Spain country listing.

    The country page can contain navigation/category links but genuine vacancies have
    stable /ad/<employer>/<year>/<slug>/<numeric-id> URLs. We deliberately collect the
    job identity/title here and obtain authoritative metadata/full JD from each detail
    page, avoiding brittle card-layout assumptions.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    declared = _declared_count(soup)
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href", ""))
        job_id = _ad_id_from_url(href)
        if not job_id:
            continue
        label = _clean(a.get_text(" ", strip=True))
        if not label:
            # Image wrappers often point to the same ad; the textual title link is kept.
            continue
        current = by_id.get(job_id)
        if current is None:
            current = {"id": job_id, "title": label, "urls": [href]}
            by_id[job_id] = current
            order.append(job_id)
        else:
            if href not in current["urls"]:
                current["urls"].append(href)
            if len(label) > len(current.get("title", "")):
                current["title"] = label
    return [by_id[job_id] for job_id in order], declared


def _jsonld_objects(soup: BeautifulSoup) -> list[dict]:
    found: list[dict] = []

    def walk(value):
        if isinstance(value, dict):
            found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for node in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = node.string or node.get_text() or ""
        if not raw.strip():
            continue
        try:
            walk(json.loads(raw))
        except Exception:
            continue
    return found


def _jobposting_jsonld(soup: BeautifulSoup) -> dict:
    for obj in _jsonld_objects(soup):
        kind = obj.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(str(k).lower() == "jobposting" for k in kinds if k):
            return obj
    return {}


def _strip_html(value: Any) -> str:
    raw = html_lib.unescape(str(value or ""))
    return _clean(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True))


def _organization_name(obj: dict) -> str:
    org = obj.get("hiringOrganization") or {}
    if isinstance(org, dict):
        return _clean(org.get("name"))
    return _clean(org)


def _location_from_jsonld(obj: dict) -> str:
    raw = obj.get("jobLocation")
    items = raw if isinstance(raw, list) else [raw]
    locations: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        address = item.get("address") or {}
        if not isinstance(address, dict):
            continue
        parts = []
        for key in ("addressLocality", "addressRegion", "addressCountry"):
            val = address.get(key)
            if isinstance(val, dict):
                val = val.get("name")
            val = _clean(val)
            if val and val not in parts:
                parts.append(val)
        if parts:
            locations.append(", ".join(parts))
    return "; ".join(dict.fromkeys(locations))


def _first_employer_link(soup: BeautifulSoup) -> str:
    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "")
        if "/employer/" in href or "/institution/" in href:
            text = _clean(a.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _extract_body(soup: BeautifulSoup, title: str, jsonld: dict) -> str:
    description = _strip_html(jsonld.get("description")) if jsonld else ""
    if len(description) >= 250:
        return description

    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form", "button"]):
        tag.decompose()
    root = clone.find("main") or clone.find("article") or clone.find(attrs={"role": "main"}) or clone.body or clone
    text = _clean(root.get_text(" ", strip=True))
    # Keep only the current vacancy; avoid "similar jobs" contaminating frozen scoring.
    cut = len(text)
    for marker in STOP_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            cut = min(cut, idx)
    text = text[:cut].strip()
    if title:
        idx = text.lower().find(title.lower())
        if idx >= 0:
            text = text[idx:]
    return _clean(text)


def _exact_date_from_text(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        m = re.search(rf"{label}\s*:?\s*(\d{{4}}-\d{{2}}-\d{{2}})", text, re.I)
        if m:
            return m.group(1)
    return ""


def parse_detail(html: str, url: str, fallback_title: str = "") -> tuple[dict, str]:
    if _is_blocked_html(html):
        return {}, "ACADEMICPOSITIONS_ACCESS_BLOCKED"
    soup = BeautifulSoup(html or "", "html.parser")
    jsonld = _jobposting_jsonld(soup)

    h1 = soup.find("h1")
    title = _clean(jsonld.get("title")) or (_clean(h1.get_text(" ", strip=True)) if h1 else "") or fallback_title
    employer = _organization_name(jsonld) or _first_employer_link(soup)
    location = _location_from_jsonld(jsonld)
    body = _extract_body(soup, title, jsonld)
    page_text = _clean(soup.get_text(" ", strip=True))

    date_posted = _clean(jsonld.get("datePosted"))[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_posted):
        date_posted = _exact_date_from_text(page_text, (r"Published", r"Publicado"))

    deadline = _clean(jsonld.get("validThrough"))[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline):
        deadline = _exact_date_from_text(page_text, (r"Application deadline", r"Fecha l[ií]mite"))

    if not location:
        # Conservative fallback: detail pages expose a location immediately below h1.
        country = "Spain" if re.search(r"\b(?:Spain|España)\b", page_text, re.I) else ""
        city = ""
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            if "/jobs/city/" in href:
                city = _clean(a.get_text(" ", strip=True)).rstrip(",")
                if city:
                    break
        location = ", ".join([p for p in (city, country) if p])

    if not body or len(body) < 180:
        return {
            "title": title,
            "company": employer,
            "location": location,
            "date": date_posted,
            "deadline": deadline,
        }, "ACADEMICPOSITIONS_DETAIL_TOO_THIN"

    metadata_lines = [
        f"Title: {title}" if title else "",
        f"Employer: {employer}" if employer else "",
        f"Location: {location}" if location else "",
        f"Published: {date_posted}" if date_posted else "",
        f"Application deadline: {deadline}" if deadline else "",
    ]
    full_detail = _clean("\n".join([line for line in metadata_lines if line] + [body]))
    return {
        "title": title,
        "company": employer,
        "location": location,
        "date": date_posted,
        "deadline": deadline,
        "full_detail": full_detail,
    }, "OK_HTML"


def classify_source_status(detail: str) -> tuple[str, str]:
    m = CLOSED_RE.search(detail or "")
    if m:
        return "CLOSED", _clean(m.group(0))
    # Do not infer OPEN from mere presence on AcademicPositions: expired listings can
    # remain visible. The frozen availability parser should decide from explicit dates.
    return "", ""


def collect(
    diagnostics: dict | None = None,
    max_jobs: int = 80,
    session=None,
    board_urls: tuple[tuple[str, str], ...] = BOARD_URLS,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "feed_mode": "academicpositions_public_spain_bilingual_direct",
        "board_urls": {name: url for name, url in board_urls},
        "boards_requested": len(board_urls),
        "boards_fetched": 0,
        "board_errors": [],
        "board_declared_counts": {},
        "board_parsed_job_counts": {},
        "raw_job_links": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_fallback_attempts": 0,
        "detail_fallback_success": 0,
        "access_blocked": 0,
        "detail_status_counts": {},
        "coverage_complete": False,
        "coverage_warning": "",
    })

    own_session = session is None
    s = session or make_retry_session(total_retries=2, backoff_factor=0.75)
    by_id: dict[str, dict] = {}
    order: list[str] = []
    try:
        for board_name, board_url in board_urls:
            try:
                r = s.get(board_url, timeout=(10, 45), allow_redirects=True)
                r.raise_for_status()
                if _is_blocked_html(r.text):
                    raise RuntimeError("AcademicPositions access challenge detected")
                jobs, declared = parse_listing(r.text, r.url)
                diag["boards_fetched"] += 1
                diag["board_declared_counts"][board_name] = declared
                diag["board_parsed_job_counts"][board_name] = len(jobs)
                diag["raw_job_links"] += len(jobs)
                for item in jobs:
                    job_id = item["id"]
                    current = by_id.get(job_id)
                    if current is None:
                        current = {
                            "id": job_id,
                            "title": item.get("title", ""),
                            "urls": list(item.get("urls") or []),
                            "boards_seen": [board_name],
                        }
                        by_id[job_id] = current
                        order.append(job_id)
                    else:
                        for url in item.get("urls") or []:
                            if url not in current["urls"]:
                                current["urls"].append(url)
                        if board_name not in current["boards_seen"]:
                            current["boards_seen"].append(board_name)
                        if len(item.get("title", "")) > len(current.get("title", "")):
                            current["title"] = item["title"]
            except Exception as exc:
                diag["board_errors"].append({"board": board_name, "url": board_url, "error": f"{type(exc).__name__}: {exc}"})

        candidates = [by_id[job_id] for job_id in order]
        diag["unique_jobs"] = len(candidates)
        if len(candidates) > max_jobs:
            diag["truncated"] = len(candidates) - max_jobs
            candidates = candidates[:max_jobs]

        rows: list[dict] = []
        status_counter: Counter[str] = Counter()
        for candidate in candidates:
            urls = list(candidate.get("urls") or [])
            # Prefer international English detail, then Spanish mirror.
            urls.sort(key=lambda u: (0 if urlparse(u).netloc.endswith("academicpositions.com") else 1, u))
            chosen_url = urls[0] if urls else ""
            detail_meta: dict = {}
            detail_status = "ACADEMICPOSITIONS_NO_DETAIL_URL"
            detail_error = ""
            used_url = chosen_url
            for idx, detail_url in enumerate(urls):
                diag["detail_attempts"] += 1
                if idx > 0:
                    diag["detail_fallback_attempts"] += 1
                try:
                    r = s.get(detail_url, timeout=(10, 45), allow_redirects=True)
                    r.raise_for_status()
                    parsed, status = parse_detail(r.text, r.url, candidate.get("title", ""))
                    if status == "ACADEMICPOSITIONS_ACCESS_BLOCKED":
                        diag["access_blocked"] += 1
                    if status == "OK_HTML" and parsed.get("full_detail"):
                        detail_meta = parsed
                        detail_status = status
                        used_url = r.url
                        if idx > 0:
                            diag["detail_fallback_success"] += 1
                        break
                    detail_meta = parsed
                    detail_status = status
                    detail_error = status
                except Exception as exc:
                    detail_status = "ACADEMICPOSITIONS_DETAIL_FETCH_FAILED"
                    detail_error = f"{type(exc).__name__}: {exc}"
                    continue

            status_counter[detail_status] += 1
            if detail_status == "OK_HTML" and detail_meta.get("full_detail"):
                diag["detail_success"] += 1
            else:
                diag["detail_failed"] += 1

            title = detail_meta.get("title") or candidate.get("title", "")
            company = detail_meta.get("company", "")
            location = detail_meta.get("location", "") or "Spain"
            row = JobRecord(
                source=SOURCE_NAME,
                title=title,
                company=company,
                location=location,
                date=detail_meta.get("date", ""),
                url=used_url or chosen_url,
                id=candidate["id"],
                modality="",
                description="AcademicPositions Spain public country board.",
                search_query="academicpositions_spain",
            ).to_dict()
            row["boards_seen"] = "; ".join(candidate.get("boards_seen") or [])
            row["urls_seen"] = "; ".join(urls)
            row["full_detail"] = detail_meta.get("full_detail", "")
            row["detail_status"] = detail_status
            row["detail_error"] = detail_error
            if detail_meta.get("deadline"):
                row["source_deadline"] = detail_meta["deadline"]
            if row["full_detail"]:
                row["trusted_full_detail_source"] = SOURCE_NAME
                row["trusted_full_detail_url"] = row["url"]
            source_status, evidence = classify_source_status(row["full_detail"])
            row["source_application_status"] = source_status
            row["source_status_evidence"] = evidence
            rows.append(row)

        diag["detail_status_counts"] = dict(status_counter)
        all_boards_clean = diag["boards_fetched"] == diag["boards_requested"] and not diag["board_errors"]
        counts_consistent = True
        for board_name, declared in diag["board_declared_counts"].items():
            parsed = int(diag["board_parsed_job_counts"].get(board_name, 0) or 0)
            if declared is not None and parsed < declared:
                counts_consistent = False
        diag["coverage_complete"] = bool(all_boards_clean and counts_consistent and diag["truncated"] == 0)
        if not diag["coverage_complete"]:
            reasons = []
            if diag["board_errors"]:
                reasons.append("one or more public country boards failed")
            if not counts_consistent:
                reasons.append("parsed job count was lower than a board-declared count")
            if diag["truncated"]:
                reasons.append(f"candidate set truncated by {diag['truncated']}")
            diag["coverage_warning"] = "AcademicPositions coverage incomplete: " + "; ".join(reasons or ["unknown reason"])
        return rows
    finally:
        if own_session:
            try:
                s.close()
            except Exception:
                pass
