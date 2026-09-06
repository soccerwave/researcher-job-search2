from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "Fundació Bosch i Gimpera (UB)"
COMPANY = "Fundació Bosch i Gimpera - Universitat de Barcelona"
DEFAULT_LOCATION = "Barcelona, Spain"
BOARD_URL = "https://extractes.fbg.ub.edu/extractes/frameofertes.jsp"
DETAIL_BASE = "https://extractes.fbg.ub.edu/extractes/getOfertaRRHHWeb"
CODE_RE = re.compile(r"\b20\d{7}\b")
DATE_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
OK_DETAIL_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "CACHE", "OK"}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _iso_date(value: str) -> str:
    m = DATE_RE.search(_clean(value))
    if not m:
        return ""
    d, mo, y = map(int, m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def _detail_url(code: str) -> str:
    return f"{DETAIL_BASE}?idoferta={code}&oferta{code}="


def parse_board_html(html: str) -> list[dict]:
    """Parse FBG/UB's official current-offers table without title filtering.

    `frameofertes.jsp` is explicitly the current active-offers view. The vacancy code is
    the stable identity; detail pages are available through FBG's public
    `getOfertaRRHHWeb` route. Deadlines are normalized from the board and remain
    authoritative for availability through the frozen generic parser.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    jobs: list[dict] = []
    seen: set[str] = set()

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 5:
            continue
        values = [_clean(c.get_text(" ", strip=True)) for c in cells]
        code_match = CODE_RE.search(values[0] if values else "")
        if not code_match:
            continue
        code = code_match.group(0)
        if code in seen:
            continue

        director = values[1] if len(values) > 1 else ""
        title = values[2] if len(values) > 2 else ""
        start = _iso_date(values[3] if len(values) > 3 else "")
        deadline = _iso_date(values[4] if len(values) > 4 else "")
        if not title:
            continue

        desc = [f"Official FBG/UB current job offer. Vacancy code: {code}."]
        if director:
            desc.append(f"Project director: {director}.")
        if start:
            desc.append(f"Start date: {start}.")
        if deadline:
            desc.append(f"Application deadline: {deadline}.")

        row = JobRecord(
            source=SOURCE_NAME,
            id=code,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=deadline,
            url=_detail_url(code),
            description=" ".join(desc),
            search_query="fbg_ub_current_offers",
        ).to_dict()
        row["source_application_status"] = "OPEN"
        row["source_status_evidence"] = "Listed on FBG/UB official Ofertes actuals board"
        row["director"] = director
        row["start_date"] = start
        row["application_deadline"] = deadline
        jobs.append(row)
        seen.add(code)

    return jobs


def collect(
    diagnostics: dict | None = None,
    max_jobs: int = 50,
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    session=None,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_fbg_ub_current_offers",
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

    own_session = session is None
    session = session or make_retry_session(total_retries=3, backoff_factor=1.0)
    try:
        try:
            response = session.get(BOARD_URL, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            diag["board_fetched"] = True
            rows = parse_board_html(response.text)
        except Exception as exc:
            diag["coverage_warning"] = f"FBG/UB current-offers board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_jobs"] = len(rows)
        diag["unique_jobs"] = len(rows)
        if len(rows) > max_jobs:
            diag["truncated"] = len(rows) - max_jobs
            rows = rows[:max_jobs]
            diag["coverage_warning"] = (
                f"FBG/UB current-offers listing set truncated by max_jobs={max_jobs}; "
                f"{diag['truncated']} listing(s) not processed"
            )

        if enrich_detail:
            for job in rows:
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
                if detail and status in OK_DETAIL_STATUSES:
                    diag["detail_success"] += 1
                    job["trusted_full_detail_source"] = SOURCE_NAME
                    job["trusted_full_detail_url"] = job.get("url", "")
                else:
                    diag["detail_failed"] += 1

        diag["coverage_complete"] = bool(diag["board_fetched"] and diag["truncated"] == 0)
        if not diag["coverage_complete"] and not diag["coverage_warning"]:
            diag["coverage_warning"] = "FBG/UB current-offers coverage incomplete"
        return rows
    finally:
        if own_session and session is not None:
            try:
                session.close()
            except Exception:
                pass
