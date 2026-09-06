from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "FISABIO"
COMPANY = "Fundación Fisabio"
DEFAULT_LOCATION = "Valencia, Spain"
BOARD_URL = (
    "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/"
    "DetalleTipoConvocatoria/EMPLEO?Estado=A"
)
DETAIL_RE = re.compile(r"/Convocatorias/VerConvocatoria/(\d+)(?:[/?#]|$)", re.I)
REF_RE = re.compile(r"\b(20\d{2})\s*[/_-]\s*(\d{1,4})\b")
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})(?:\s+\d{1,2}:\d{2})?\b")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_ref(text: str) -> str:
    m = REF_RE.search(_clean(text))
    return f"{m.group(1)}/{int(m.group(2))}" if m else ""


def _canonical(url: str) -> str:
    return str(url or "").split("#", 1)[0].rstrip("/")


def _find_bases_url(html: str, detail_url: str) -> str:
    """Return FISABIO's official vacancy-bases document URL from a Fundanet shell.

    The public VerConvocatoria page is only an application wrapper.  It must never be
    treated as a Full JD merely because it contains a lot of generic instructions.
    Prefer Fundanet's stable DescargarDocumentoBases route, with the visible
    ``Bases de la Convocatoria`` label as a conservative fallback.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    labeled: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(detail_url, a.get("href", ""))
        label = _clean(a.get_text(" ", strip=True)).lower()
        path = urlparse(href).path.lower()
        if "/convocatorias/descargardocumentobases/" in path:
            return href
        if "bases de la convocatoria" in label or "bases convocatoria" in label:
            labeled.append(href)
    return labeled[0] if labeled else ""


def _resolve_bases_detail(job: dict, session, timeout=(10, 45)) -> tuple[str, str, str]:
    """Resolve one FISABIO vacancy to its official Bases document.

    Returns ``(text, status, bases_url)``.  The HTML application shell is deliberately
    never returned as job detail.
    """
    detail_url = job.get("url", "")
    if not detail_url:
        return "", "NO_URL", ""
    try:
        r = session.get(detail_url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
    except Exception as exc:
        return "", f"FISABIO_DETAIL_PAGE_FETCH_FAILED: {exc}", ""

    bases_url = _find_bases_url(r.text, r.url)
    if not bases_url:
        return "", "FISABIO_BASES_LINK_NOT_FOUND", ""

    text, status = fetch_url_text(
        bases_url,
        timeout=timeout,
        title_hint=job.get("title", ""),
        session=session,
        follow_job_attachments=False,
    )
    if not text or status not in {"OK_PDF", "OK_HTML", "OK"}:
        return "", f"FISABIO_BASES_{status}", bases_url
    final_status = "OK_PDF_ATTACHMENT" if status == "OK_PDF" else "OK_ATTACHMENT"
    return text, final_status, bases_url


def _row_dates(row) -> tuple[str, str]:
    cells = row.find_all(["td", "th"]) if row is not None else []
    if len(cells) >= 3:
        start = _clean(cells[1].get_text(" ", strip=True))
        end = _clean(cells[2].get_text(" ", strip=True))
        return start, end
    text = _clean(row.get_text(" ", strip=True) if row is not None else "")
    dates = DATE_RE.findall(text)
    return (dates[0] if dates else "", dates[1] if len(dates) > 1 else "")


def parse_board_html(html: str, board_url: str = BOARD_URL) -> list[dict]:
    """Parse FISABIO's public Fundanet active-vacancy table.

    The parser keys on Fundanet's stable ``VerConvocatoria/<numeric-id>`` route rather
    than presentation classes. Card/table text is metadata only; scoring always uses
    the full vacancy bases resolved from the detail page/attached PDF.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(board_url, a.get("href", ""))
        match = DETAIL_RE.search(urlparse(href).path)
        if not match:
            continue
        url = _canonical(href)
        if url in seen:
            continue
        title = _clean(a.get_text(" ", strip=True))
        if not title:
            continue
        seen.add(url)
        row = a.find_parent("tr")
        start, end = _row_dates(row)
        ref = _normalize_ref(title)
        desc_parts = []
        if start:
            desc_parts.append(f"Application opens: {start}")
        if end:
            desc_parts.append(f"Application deadline: {end.split()[0]}")
        out.append(JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=start,
            url=url,
            id=ref or match.group(1),
            description=". ".join(desc_parts),
            search_query="fundanet_active_employment",
        ).to_dict())
    return out


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 50,
) -> list[dict]:
    """Collect all currently open FISABIO employment calls from the public portal.

    No title/domain relevance filter is applied. The Fundanet ``VerConvocatoria`` page
    is an application wrapper and is never scored. Each vacancy must resolve to the
    official ``Bases de la Convocatoria`` document before deterministic scoring runs.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "fundanet_active_employment",
        "board_fetched": False,
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "bases_links_found": 0,
        "bases_fetch_success": 0,
        "bases_fetch_failed": 0,
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
            diag["coverage_warning"] = f"FISABIO active board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_jobs"] = len(jobs)
        unique: list[dict] = []
        seen: set[str] = set()
        for job in jobs:
            key = _canonical(job.get("url", ""))
            if key and key not in seen:
                seen.add(key)
                unique.append(job)
        diag["unique_jobs"] = len(unique)

        if len(unique) > max_jobs:
            diag["truncated"] = len(unique) - max_jobs
            unique = unique[:max_jobs]
            diag["coverage_warning"] = (
                f"FISABIO active listing set truncated by max_jobs={max_jobs}; "
                f"{diag['truncated']} listing(s) not processed"
            )

        if enrich_detail:
            ok_statuses = {"OK_PDF_ATTACHMENT", "OK_ATTACHMENT"}
            for job in unique:
                diag["detail_attempts"] += 1
                detail, status, bases_url = _resolve_bases_detail(job, session, timeout=(10, 45))
                job["bases_url"] = bases_url
                job["full_detail"] = detail
                job["detail_status"] = status
                if bases_url:
                    diag["bases_links_found"] += 1
                counts = diag["detail_status_counts"]
                counts[status] = int(counts.get(status, 0)) + 1
                if detail and status in ok_statuses:
                    diag["detail_success"] += 1
                    diag["bases_fetch_success"] += 1
                else:
                    diag["detail_failed"] += 1
                    diag["bases_fetch_failed"] += 1

        diag["coverage_complete"] = bool(diag["board_fetched"] and diag["truncated"] == 0)
        return unique
    finally:
        try:
            session.close()
        except Exception:
            pass
