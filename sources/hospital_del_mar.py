from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "Hospital del Mar Research Institute"
COMPANY = "Hospital del Mar Research Institute"
DEFAULT_LOCATION = "Barcelona, Spain"
BOARD_URL = "https://researchmar.net/ofertes/en_convocatories-temporals.html"
DETAIL_PATH_RE = re.compile(r"/ofertes/en_detall-oferta-temporals\.html$", re.I)
REF_RE = re.compile(r"\b(?:Ref\.?\s*:?\s*)?(FIMIM\d{4}-[A-ZÀ-ÖØ-Ý0-9_-]+)\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}-\d{1,2}-\d{4})\b")
OK_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}

# The official Hospital del Mar detail page keeps a closed vacancy visible on the
# Temporary Calls board and appends an explicit selection-process-ended marker.
# English pages currently expose the marker in Catalan, but keep multilingual
# variants so the status parser is resilient to locale changes.
SELECTION_ENDED_RE = re.compile(
    r"(?:"
    r"aquest\s+proc[eé]s\s+de\s+selecci[oó]\s+ha\s+finalitzat"
    r"|este\s+proceso\s+de\s+selecci[oó]n\s+ha\s+finalizado"
    r"|this\s+selection\s+process\s+(?:has\s+)?(?:ended|finished|closed)"
    r"|selection\s+process\s+(?:has\s+)?(?:ended|finished|closed)"
    r")"
    r"(?:\s+(?:en\s+data|en\s+fecha|on)\s+(\d{1,2}[./-]\d{1,2}[./-]\d{4}))?",
    re.I,
)


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _canonical(url: str) -> str:
    return (url or "").split("#", 1)[0].rstrip("/")


def _detail_id(url: str) -> str:
    parsed = urlparse(url)
    if not DETAIL_PATH_RE.search(parsed.path):
        return ""
    return (parse_qs(parsed.query).get("id") or [""])[0].strip()


def _context_for_anchor(a) -> str:
    """Return the smallest nearby block carrying the vacancy's date/reference metadata."""
    node = a
    best = _clean(a.get_text(" ", strip=True))
    for _ in range(7):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if not text:
            continue
        best = text
        # The official listing prints a posting date and FIMIM reference with each call.
        if DATE_RE.search(text) and REF_RE.search(text):
            return text
    return best


def parse_board_html(html: str, board_url: str = BOARD_URL) -> list[dict]:
    """Parse vacancy-specific links from the official Temporary Calls board.

    The board does not publish an explicit application deadline in the listing. The
    visible date is retained as the posting date only; availability is therefore not
    inferred from that date.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = _canonical(urljoin(board_url, a.get("href", "")))
        detail_id = _detail_id(href)
        if not detail_id:
            continue
        title = _clean(a.get_text(" ", strip=True))
        if not title:
            continue
        key = href.lower()
        if key in seen:
            continue
        seen.add(key)

        context = _context_for_anchor(a)
        ref_match = REF_RE.search(context)
        date_match = DATE_RE.search(context)
        reference = ref_match.group(1).upper() if ref_match else detail_id
        posted = date_match.group(1) if date_match else ""

        desc = ["Official Hospital del Mar Research Institute temporary call."]
        if posted:
            desc.append(f"Posted: {posted}.")
        if reference and reference != detail_id:
            desc.append(f"Reference: {reference}.")

        # JobRecord.date is intentionally blank: the existing availability parser
        # treats date-like metadata as candidate deadlines. The board date is a
        # publication date, not an application deadline.
        jobs.append(JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date="",
            url=href,
            id=reference,
            description=" ".join(desc),
            search_query="hospital_del_mar_temporary_calls",
        ).to_dict())
        jobs[-1]["posted_date"] = posted

    return jobs


def classify_selection_status(detail: str, detail_status: str = "OK_HTML") -> tuple[str, str, str]:
    """Return source-authoritative application status from a resolved detail page.

    Hospital del Mar does not publish an application deadline on this board. Instead,
    completed calls remain listed and their detail page receives an explicit
    selection-process-ended marker. A successfully resolved vacancy page without that
    marker is therefore treated as currently open on this source. Failed/unresolved
    details remain unknown rather than being guessed.
    """
    clean = _clean(detail)
    if not clean or detail_status not in OK_STATUSES:
        return "", "", ""
    match = SELECTION_ENDED_RE.search(clean)
    if match:
        closed_date = (match.group(1) or "").strip()
        evidence = _clean(match.group(0))
        return "CLOSED", evidence or "Official detail page states the selection process has ended", closed_date
    return (
        "OPEN",
        "Listed on the current official Temporary Calls board; resolved detail page has no selection-process-ended marker",
        "",
    )


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 100,
) -> list[dict]:
    """Collect official temporary calls and use each vacancy-specific page as Full JD."""
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_hospital_del_mar_temporary_calls",
        "board_fetch": "FAILED",
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "source_status_open": 0,
        "source_status_closed": 0,
        "source_status_unknown": 0,
        "coverage_complete": False,
        "coverage_warning": "",
        "final_url": BOARD_URL,
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    try:
        try:
            r = session.get(BOARD_URL, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            diag["board_fetch"] = "OK"
            diag["final_url"] = getattr(r, "url", BOARD_URL) or BOARD_URL
            jobs = parse_board_html(r.text, diag["final_url"])
        except Exception as exc:
            diag["coverage_warning"] = f"Hospital del Mar temporary-calls board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_jobs"] = len(jobs)
        unique: list[dict] = []
        seen: set[str] = set()
        for job in jobs:
            key = (_detail_id(job.get("url", "")) or _canonical(job.get("url", ""))).lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(job)
        diag["unique_jobs"] = len(unique)

        if len(unique) > max_jobs:
            diag["truncated"] = len(unique) - max_jobs
            unique = unique[:max_jobs]
            diag["coverage_warning"] = (
                f"Hospital del Mar temporary-call listing truncated by max_jobs={max_jobs}; "
                f"{diag['truncated']} listing(s) not processed"
            )

        if enrich_detail:
            for job in unique:
                diag["detail_attempts"] += 1
                detail, status = fetch_url_text(
                    job.get("url", ""),
                    timeout=(10, 45),
                    title_hint=job.get("title", ""),
                    session=session,
                    follow_job_attachments=False,
                )
                job["full_detail"] = detail
                job["detail_status"] = status
                counts = diag["detail_status_counts"]
                counts[status] = int(counts.get(status, 0)) + 1
                if detail and status in OK_STATUSES:
                    diag["detail_success"] += 1
                    job["trusted_full_detail_source"] = SOURCE_NAME
                    job["trusted_full_detail_url"] = job.get("url", "")
                    source_status, source_evidence, closed_date = classify_selection_status(detail, status)
                    job["source_application_status"] = source_status
                    job["source_status_evidence"] = source_evidence
                    job["source_closed_date"] = closed_date
                    if source_status == "OPEN":
                        diag["source_status_open"] += 1
                    elif source_status == "CLOSED":
                        diag["source_status_closed"] += 1
                    else:
                        diag["source_status_unknown"] += 1
                else:
                    diag["detail_failed"] += 1
                    job["source_application_status"] = ""
                    job["source_status_evidence"] = ""
                    job["source_closed_date"] = ""
                    diag["source_status_unknown"] += 1

        diag["coverage_complete"] = bool(diag["board_fetch"] == "OK" and diag["truncated"] == 0)
        return unique
    finally:
        try:
            session.close()
        except Exception:
            pass
