from __future__ import annotations

import math
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "IR Sant Pau"
COMPANY = "Fundació Institut de Recerca de l'Hospital de la Santa Creu i Sant Pau"
DEFAULT_LOCATION = "Barcelona, Spain"
BOARD_BASE = "https://www.recercasantpau.cat/en/join-our-team"

REF_RE = re.compile(r"\b(20\d{2})[/_](\d{2,4})\b", re.I)
SHOWING_RE = re.compile(r"Showing\s+\d+\s+to\s+\d+\s+of\s+(\d+)\s+entries", re.I)
DETAIL_PATH_RE = re.compile(r"/(?:en/)?w/[^?#]+", re.I)
OPEN_PREFIX_RE = re.compile(r"^\s*Open\b", re.I)
INTERNAL_RE = re.compile(r"\bInternal\s+Promotion\b", re.I)
CUT_RE = re.compile(
    r"\b(?:Call\s+for\s+(?:applications?|a)|Convocat[oò]ria\s+per|Convocatoria\s+para)\b",
    re.I,
)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "gener": 1, "febrer": 2, "març": 3, "marc": 3, "abril": 4, "maig": 5, "juny": 6,
    "juliol": 7, "agost": 8, "setembre": 9, "octubre": 10, "novembre": 11, "desembre": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

OK_DETAIL_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _canonical_ref(text: str) -> str:
    m = REF_RE.search(text or "")
    return f"{m.group(1)}_{int(m.group(2)):03d}" if m else ""


def _parse_deadline(text: str) -> str:
    clean = _clean(text).replace("’", "'")
    # ISO/numeric first.
    m = re.search(r"(?:Application deadline|Deadline|Termini|Plazo).{0,120}?(\d{4}-\d{1,2}-\d{1,2})", clean, re.I)
    if m:
        y, mo, d = (int(x) for x in m.group(1).split("-"))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return ""
    m = re.search(r"(?:Application deadline|Deadline|Termini|Plazo).{0,120}?(\d{1,2})[./-](\d{1,2})[./-](\d{4})", clean, re.I)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return ""

    # English/Catalan/Spanish month names, including Catalan d'agost / d’agost.
    m = re.search(
        r"(?:Application deadline|Deadline|Termini|Plazo).{0,140}?"
        r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:d['’]|de\s+)?"
        r"([A-Za-zÀ-ÿçÇ]+)(?:\s+de)?\s+(\d{4})",
        clean,
        re.I,
    )
    if not m:
        return ""
    d, month_name, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    month = MONTHS.get(month_name)
    if not month:
        return ""
    try:
        return date(y, month, d).isoformat()
    except ValueError:
        return ""


def _title_from_card(text: str, ref: str) -> str:
    value = _clean(text)
    value = OPEN_PREFIX_RE.sub("", value, count=1).strip()
    value = re.sub(r"^Ref\.\s*20\d{2}[/_]\d{2,4}\s*", "", value, flags=re.I)
    # Some cards repeat the reference as "2026/121:" before the title.
    value = re.sub(r"^20\d{2}[/_]\d{2,4}\s*:\s*", "", value, flags=re.I)
    value = re.sub(r"^\d+\s+", "", value)
    cut = CUT_RE.search(value)
    if cut:
        value = value[:cut.start()]
    # A few cards have a duplicated status/ref string or trailing action label.
    value = re.sub(r"\s+Join\s*$", "", value, flags=re.I)
    value = _clean(value.strip(" :-–—"))
    return value or ref


def parse_board_html(html: str, base_url: str = BOARD_BASE) -> tuple[list[dict], int | None]:
    """Return board-labelled open/external calls only.

    IR Sant Pau keeps closed historical calls on the same paginated board. We therefore
    use the board's explicit Open/Closed label only to decide which records deserve a
    detail fetch. Final availability is still decided by the frozen deadline parser,
    because the board can lag by a few days after a deadline passes.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    page_text = _clean(soup.get_text(" ", strip=True))
    total_match = SHOWING_RE.search(page_text)
    total = int(total_match.group(1)) if total_match else None

    rows: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, str(a.get("href") or ""))
        if not DETAIL_PATH_RE.search(href):
            continue
        text = _clean(a.get_text(" ", strip=True))
        if not OPEN_PREFIX_RE.search(text):
            continue
        if INTERNAL_RE.search(text):
            continue
        ref = _canonical_ref(text)
        if not ref or ref in seen:
            continue
        title = _title_from_card(text, ref)
        deadline = _parse_deadline(text)
        description = f"Official IR Sant Pau job board listing. Reference: {ref}."
        if deadline:
            description += f" Application deadline: {deadline}."
        rows.append(JobRecord(
            source=SOURCE_NAME,
            id=ref,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=deadline,
            url=href,
            description=description,
            search_query="ir_sant_pau_open_jobs",
        ).to_dict())
        rows[-1]["board_status"] = "OPEN"
        rows[-1]["board_text"] = text
        seen.add(ref)
    return rows, total


def collect(
    diagnostics: dict | None = None,
    max_pages: int = 3,
    max_jobs: int = 60,
    timeout: int | tuple[int, int] = (10, 20),
    enrich_detail: bool = True,
    session=None,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_BASE,
        "feed_mode": "official_ir_sant_pau_open_calls",
        "pages_requested": 0,
        "pages_fetched": 0,
        "page_errors": [],
        "page_job_counts": [],
        "board_total_reported": None,
        "parsed_open_jobs": 0,
        "unique_jobs": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "truncated": 0,
        "coverage_complete": False,
        "coverage_warning": "",
        "board_timeout_seconds": 20,
        "transport_retries": 1,
    })

    own_session = session is None
    session = session or make_retry_session(total_retries=1, backoff_factor=1.0)
    try:
        by_ref: dict[str, dict] = {}
        total_reported: int | None = None
        pages_needed = max(1, max_pages)
        page = 1
        while page <= pages_needed and page <= max_pages:
            url = f"{BOARD_BASE}?delta=60&start={page}"
            diag["pages_requested"] += 1
            try:
                response = session.get(url, timeout=timeout, allow_redirects=True)
                response.raise_for_status()
            except Exception as exc:
                diag["page_errors"].append({"page": page, "error": f"{type(exc).__name__}: {exc}"})
                break

            diag["pages_fetched"] += 1
            rows, declared = parse_board_html(response.text, getattr(response, "url", url) or url)
            diag["page_job_counts"].append(len(rows))
            if declared is not None:
                total_reported = max(total_reported or 0, declared)
                diag["board_total_reported"] = total_reported
                pages_needed = min(max_pages, max(1, math.ceil(total_reported / 60)))

            new_refs = 0
            for row in rows:
                ref = row.get("id", "")
                if ref and ref not in by_ref:
                    by_ref[ref] = row
                    new_refs += 1
            # If pagination metadata is absent, stop on an empty/no-new page.
            if declared is None and (not rows or new_refs == 0):
                break
            page += 1

        all_rows = list(by_ref.values())
        diag["parsed_open_jobs"] = len(all_rows)
        diag["unique_jobs"] = min(len(all_rows), max_jobs)
        diag["truncated"] = max(0, len(all_rows) - max_jobs)
        jobs = all_rows[:max_jobs]

        if enrich_detail:
            for job in jobs:
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

        expected_pages = math.ceil(total_reported / 60) if total_reported else diag["pages_fetched"]
        complete = (
            diag["pages_fetched"] > 0
            and not diag["page_errors"]
            and diag["truncated"] == 0
            and (not total_reported or diag["pages_fetched"] >= min(expected_pages, max_pages))
        )
        # If the historical board needs more pages than the configured cap, this does not
        # reduce current-open coverage as long as all board-labelled open calls are already
        # on fetched pages. Still surface the scope truthfully when the cap cuts pagination.
        if total_reported and expected_pages > max_pages:
            complete = False
            diag["coverage_warning"] = (
                f"IR Sant Pau board has {total_reported} total historical entries; "
                f"configured max_pages={max_pages} did not scan every historical page"
            )
        diag["coverage_complete"] = complete
        return jobs
    finally:
        if own_session:
            try:
                session.close()
            except Exception:
                pass
