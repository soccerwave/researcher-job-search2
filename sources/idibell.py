from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "IDIBELL Job Offers"
COMPANY = "IDIBELL"
DEFAULT_LOCATION = "L'Hospitalet de Llobregat, Barcelona, Spain"
BOARD_URL = "https://idibell.fundanetsuite.com/convocatoriaspropias/en/Convocatorias/DetalleTipoConvocatoria/OE"
DETAIL_RE = re.compile(r"/Convocatorias/VerConvocatoria/(\d+)(?:[/?#]|$)", re.I)
REF_RE = re.compile(r"\b(\d{2}-\d{3}_[A-Z]{2}_[A-Z]{2}|\d{2}-\d{3}_[A-Z]{2}_[A-Z]{2}_[A-Z]{2})\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})(?:\s+\d{1,2}:\d{2})?\b")
OK_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _canonical(url: str) -> str:
    return (url or "").split("#", 1)[0].rstrip("/")


def _reference(title: str) -> str:
    m = REF_RE.search(_clean(title))
    return m.group(1).upper() if m else ""


def _row_dates(row) -> tuple[str, str]:
    cells = row.find_all(["td", "th"]) if row is not None else []
    if len(cells) >= 3:
        return _clean(cells[1].get_text(" ", strip=True)), _clean(cells[2].get_text(" ", strip=True))
    text = _clean(row.get_text(" ", strip=True) if row is not None else "")
    dates = DATE_RE.findall(text)
    return (dates[0] if dates else "", dates[1] if len(dates) > 1 else "")


def parse_board_html(html: str, board_url: str = BOARD_URL) -> list[dict]:
    """Parse the official IDIBELL Fundanet JOB OFFERS table.

    The board currently exposes active calls with start/deadline dates and links to the
    vacancy-specific VerConvocatoria page. No relevance filtering is applied here.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = _canonical(urljoin(board_url, a.get("href", "")))
        match = DETAIL_RE.search(urlparse(href).path)
        if not match:
            continue
        title = _clean(a.get_text(" ", strip=True))
        if not title:
            continue
        key = href.lower()
        if key in seen:
            continue
        seen.add(key)
        row = a.find_parent("tr")
        start, deadline = _row_dates(row)
        desc = ["Official IDIBELL JOB OFFERS listing."]
        if start:
            desc.append(f"Application opens: {start.split()[0]}.")
        if deadline:
            desc.append(f"Application deadline: {deadline.split()[0]}.")
        jobs.append(JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=deadline.split()[0] if deadline else "",
            url=href,
            id=_reference(title) or match.group(1),
            description=" ".join(desc),
            search_query="idibell_active_job_offers",
        ).to_dict())
    return jobs


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 80,
) -> list[dict]:
    """Collect current IDIBELL job offers and resolve each official call page as Full JD."""
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_idibell_fundanet_active_job_offers",
        "board_fetched": False,
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "coverage_complete": False,
        "coverage_warning": "",
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    try:
        try:
            r = session.get(BOARD_URL, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            diag["board_fetched"] = True
            jobs = parse_board_html(r.text, r.url)
        except Exception as exc:
            diag["coverage_warning"] = f"IDIBELL active board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_jobs"] = len(jobs)
        unique: list[dict] = []
        seen: set[str] = set()
        for job in jobs:
            key = _canonical(job.get("url", "")).lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(job)
        diag["unique_jobs"] = len(unique)

        if len(unique) > max_jobs:
            diag["truncated"] = len(unique) - max_jobs
            unique = unique[:max_jobs]
            diag["coverage_warning"] = (
                f"IDIBELL active listing set truncated by max_jobs={max_jobs}; "
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
                else:
                    diag["detail_failed"] += 1

        diag["coverage_complete"] = bool(diag["board_fetched"] and diag["truncated"] == 0)
        return unique
    finally:
        try:
            session.close()
        except Exception:
            pass
