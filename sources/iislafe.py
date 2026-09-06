from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "IIS La Fe"
COMPANY = "Instituto de Investigación Sanitaria La Fe"
DEFAULT_LOCATION = "Valencia, Spain"
BOARD_URL = "https://www.iislafe.es/es/talento/empleo/"

JOB_DETAIL_RE = re.compile(r"/es/talento/empleo/(\d+)/[^?#]+", re.I)
REF_RE = re.compile(r"n[uú]mero\s+de\s+referencia\s*:?\s*([0-9]+\s*/\s*[0-9]{4})", re.I)
DEADLINE_RE = re.compile(r"plazo\s+de\s+presentaci[oó]n\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
STATE_PATTERNS = (
    "Cerrada pendiente de evaluar",
    "Cerrado pendiente de evaluar",
    "Abierta",
    "Abierto",
    "Resuelta",
    "Resuelto",
    "Cancelada",
    "Cancelado",
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def page_url(page: int) -> str:
    page = max(1, int(page))
    return BOARD_URL if page == 1 else urljoin(BOARD_URL, f"page/{page}")


def _canonical(url: str) -> str:
    return str(url or "").split("#", 1)[0].rstrip("/")


def _portal_state(text: str) -> str:
    clean = _clean(text)
    for state in STATE_PATTERNS:
        if re.search(rf"\b{re.escape(state)}\b", clean, re.I):
            return state
    return ""


def _nearest_job_container(anchor):
    """Find the smallest ancestor that owns one IIS La Fe vacancy block.

    The site does not need a stable CSS class for this parser.  We stop at the first
    ancestor containing the vacancy metadata while avoiding an ancestor that contains
    several different job-detail links.
    """
    node = anchor.parent
    best = anchor.parent
    for _ in range(8):
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        links = set()
        for a in node.find_all("a", href=True):
            href = a.get("href", "")
            m = JOB_DETAIL_RE.search(urlparse(urljoin(BOARD_URL, href)).path)
            if m:
                links.add(m.group(1))
        if "Número de referencia".lower() in text.lower() and "Plazo de presentación".lower() in text.lower():
            best = node
            if len(links) <= 1:
                return node
        node = node.parent
    return best


def _metadata_from_container(container, base_url: str) -> dict:
    if container is None:
        return {"reference": "", "deadline": "", "portal_state": "", "bases_url": ""}
    text = _clean(container.get_text(" ", strip=True))
    refm = REF_RE.search(text)
    deadm = DEADLINE_RE.search(text)
    bases_url = ""
    for a in container.find_all("a", href=True):
        label = _clean(a.get_text(" ", strip=True)).lower()
        if label == "bases" or label.startswith("bases "):
            bases_url = _canonical(urljoin(base_url, a.get("href", "")))
            break
    return {
        "reference": _clean(refm.group(1)).replace(" ", "") if refm else "",
        "deadline": deadm.group(1) if deadm else "",
        "portal_state": _portal_state(text),
        "bases_url": bases_url,
    }


def parse_board_html(html: str, board_url: str = BOARD_URL) -> list[dict]:
    """Parse every IIS La Fe vacancy on a listing page, with no relevance filter."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = _canonical(urljoin(board_url, a.get("href", "")))
        m = JOB_DETAIL_RE.search(urlparse(href).path)
        if not m or href in seen:
            continue
        title = _clean(a.get_text(" ", strip=True))
        if not title or not re.search(r"contrataci[oó]n", title, re.I):
            continue
        seen.add(href)
        meta = _metadata_from_container(_nearest_job_container(a), board_url)
        desc_parts = []
        if meta["portal_state"]:
            desc_parts.append(f"Portal state: {meta['portal_state']}")
        if meta["deadline"]:
            desc_parts.append(f"Application deadline: {meta['deadline']}")
        row = JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=meta["deadline"],
            url=href,
            id=f"iislafe-{m.group(1)}",
            description=". ".join(desc_parts),
            search_query="iislafe_newest_pages",
        ).to_dict()
        row.update({
            "portal_convocation_id": m.group(1),
            "job_reference": meta["reference"],
            "portal_state": meta["portal_state"],
            "bases_url": meta["bases_url"],
        })
        out.append(row)
    return out


def parse_detail_html(html: str, detail_url: str) -> dict:
    """Extract identity/deadline/Bases metadata from one IIS La Fe vacancy page."""
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = _clean(root.get_text(" ", strip=True))
    h1 = root.find("h1") or soup.find("h1")
    title = _clean(h1.get_text(" ", strip=True)) if h1 else ""
    refm = REF_RE.search(text)
    deadm = DEADLINE_RE.search(text)
    bases_url = ""
    for a in root.find_all("a", href=True):
        label = _clean(a.get_text(" ", strip=True)).lower()
        if label == "bases" or label.startswith("bases "):
            bases_url = _canonical(urljoin(detail_url, a.get("href", "")))
            break
    return {
        "title": title,
        "reference": _clean(refm.group(1)).replace(" ", "") if refm else "",
        "deadline": deadm.group(1) if deadm else "",
        "portal_state": _portal_state(text),
        "bases_url": bases_url,
    }


def _merge_detail_metadata(job: dict, meta: dict) -> None:
    if meta.get("title"):
        job["title"] = meta["title"]
    if meta.get("reference"):
        job["job_reference"] = meta["reference"]
    if meta.get("portal_state"):
        job["portal_state"] = meta["portal_state"]
    if meta.get("bases_url"):
        job["bases_url"] = meta["bases_url"]
    if meta.get("deadline"):
        job["date"] = meta["deadline"]
    desc_parts = []
    if job.get("portal_state"):
        desc_parts.append(f"Portal state: {job['portal_state']}")
    if job.get("date"):
        desc_parts.append(f"Application deadline: {job['date']}")
    job["description"] = ". ".join(desc_parts)


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_pages: int = 3,
    max_jobs: int = 30,
) -> list[dict]:
    """Collect the newest IIS La Fe employment pages and resolve official Bases.

    This source deliberately carries *all* vacancies from the requested newest pages,
    including recently closed calls. Availability is a separate downstream gate. This
    makes the source useful both operationally and as a broader blind scoring holdout.
    The collector does not claim full historical portal coverage.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_iislafe_newest_pages",
        "coverage_scope": "newest_requested_pages",
        "portal_full_coverage": False,
        "pages_requested": int(max_pages),
        "pages_fetched": 0,
        "page_errors": [],
        "page_job_counts": [],
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_page_attempts": 0,
        "detail_page_success": 0,
        "detail_page_failed": 0,
        "bases_links_found": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "coverage_complete": False,
        "coverage_warning": "",
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    try:
        jobs: list[dict] = []
        for pageno in range(1, int(max_pages) + 1):
            url = page_url(pageno)
            try:
                r = session.get(url, timeout=timeout, allow_redirects=True)
                r.raise_for_status()
                page_rows = parse_board_html(r.text, r.url)
                diag["pages_fetched"] += 1
                diag["page_job_counts"].append(len(page_rows))
                jobs.extend(page_rows)
            except Exception as exc:
                diag["page_errors"].append({"page": pageno, "error": f"{type(exc).__name__}: {exc}"})

        diag["parsed_jobs"] = len(jobs)
        unique: list[dict] = []
        seen: set[str] = set()
        for job in jobs:
            key = _canonical(job.get("url", ""))
            if key and key not in seen:
                seen.add(key)
                unique.append(job)
        diag["unique_jobs"] = len(unique)

        if len(unique) > int(max_jobs):
            diag["truncated"] = len(unique) - int(max_jobs)
            unique = unique[: int(max_jobs)]

        if enrich_detail:
            ok_statuses = {"OK_PDF", "OK_HTML", "OK", "OK_ATTACHMENT", "OK_PDF_ATTACHMENT"}
            for job in unique:
                # Always resolve the canonical vacancy page before trusting its Bases link.
                diag["detail_page_attempts"] += 1
                try:
                    r = session.get(job.get("url", ""), timeout=timeout, allow_redirects=True)
                    r.raise_for_status()
                    meta = parse_detail_html(r.text, r.url)
                    _merge_detail_metadata(job, meta)
                    diag["detail_page_success"] += 1
                except Exception as exc:
                    diag["detail_page_failed"] += 1
                    job["detail_page_error"] = f"{type(exc).__name__}: {exc}"

                bases_url = _clean(job.get("bases_url"))
                if bases_url:
                    diag["bases_links_found"] += 1
                else:
                    job["full_detail"] = ""
                    job["detail_status"] = "ATTACHMENT_UNRESOLVED"
                    diag["detail_attempts"] += 1
                    diag["detail_failed"] += 1
                    counts = diag["detail_status_counts"]
                    counts["ATTACHMENT_UNRESOLVED"] = int(counts.get("ATTACHMENT_UNRESOLVED", 0)) + 1
                    continue

                diag["detail_attempts"] += 1
                detail, status = fetch_url_text(
                    bases_url,
                    timeout=(10, 45),
                    title_hint=job.get("title", ""),
                    session=session,
                    follow_job_attachments=False,
                )
                # Preserve the semantic fact that the scored text came from Bases.
                if status == "OK_PDF":
                    public_status = "OK_PDF_ATTACHMENT"
                elif status in {"OK_HTML", "OK"}:
                    public_status = "OK_ATTACHMENT"
                else:
                    public_status = status
                job["full_detail"] = detail
                job["detail_status"] = public_status
                counts = diag["detail_status_counts"]
                counts[public_status] = int(counts.get(public_status, 0)) + 1
                if detail and (status in ok_statuses):
                    diag["detail_success"] += 1
                else:
                    diag["detail_failed"] += 1

        coverage_ok = (
            diag["pages_fetched"] == int(max_pages)
            and not diag["page_errors"]
            and diag["truncated"] == 0
        )
        diag["coverage_complete"] = bool(coverage_ok)
        if diag["page_errors"]:
            diag["coverage_warning"] = f"IIS La Fe page coverage incomplete: {len(diag['page_errors'])} requested page(s) failed"
        elif diag["truncated"]:
            diag["coverage_warning"] = f"IIS La Fe newest-page set truncated by max_jobs={max_jobs}: {diag['truncated']} listing(s) omitted"
        elif diag["pages_fetched"] == int(max_pages) and diag["page_job_counts"] and diag["page_job_counts"][0] == 0:
            diag["coverage_complete"] = False
            diag["coverage_warning"] = "IIS La Fe first requested page parsed zero vacancies; page structure may have changed"
        return unique
    finally:
        try:
            session.close()
        except Exception:
            pass
