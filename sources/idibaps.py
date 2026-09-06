from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "FRCB-IDIBAPS Job Offers"
COMPANY = "FRCB-IDIBAPS"
DEFAULT_LOCATION = "Barcelona, Spain"
BOARD_URL = "https://www.clinicbarcelona.org/en/idibaps/working-idibaps/job-offers"

CALL_REF_RE = re.compile(r"\b([A-Z]{1,8}-\d{1,5}/20\d{2})\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{1,2}-\d{1,2})\b")
DEADLINE_LABEL_RE = re.compile(
    r"(?:deadline|closing\s+date|fecha\s+l[ií]mite|fecha\s+cierre)\s*:?[\s\-]*"
    r"(\d{1,2}/\d{1,2}/20\d{2}|20\d{2}-\d{1,2}-\d{1,2})",
    re.I,
)
STATUS_LABEL_RE = re.compile(
    r"(?:state|estado)\s*:?[\s\-]*(open|closed|abiertas?|cerradas?)\b",
    re.I,
)
OK_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _canonical(url: str) -> str:
    return (url or "").split("#", 1)[0].strip()


def _normalize_date(raw: str) -> str:
    raw = _clean(raw)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(20\d{2})", raw)
    if m:
        d, mo, y = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    m = re.fullmatch(r"(20\d{2})-(\d{1,2})-(\d{1,2})", raw)
    if m:
        y, mo, d = m.groups()
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    return raw


def _is_official_detail(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host not in {"clinicbarcelona.org", "www.clinicbarcelona.org"}:
        return False
    low = urlparse(url).path.lower()
    return low.endswith(".pdf") or "/uploads/media/" in low


def _context_for_anchor(a: Tag, ref: str) -> str:
    """Return the smallest vacancy block carrying deadline/state metadata.

    The public board renders each vacancy as a title link followed by deadline and state.
    We deliberately select the smallest ancestor containing only this call reference so a
    neighbouring vacancy cannot donate its deadline/status after a layout change.
    """
    fallback = ""
    node: Tag | None = a
    for _ in range(8):
        if node is None or node.parent is None or not isinstance(node.parent, Tag):
            break
        node = node.parent
        text = _clean(node.get_text(" ", strip=True))
        refs = {x.upper() for x in CALL_REF_RE.findall(text)}
        if ref.upper() not in refs:
            continue
        if len(refs) == 1:
            fallback = text
            if DEADLINE_LABEL_RE.search(text) or STATUS_LABEL_RE.search(text):
                return text
        elif fallback:
            break
    return fallback


def _metadata(context: str) -> tuple[str, str]:
    deadline = ""
    state = ""
    dm = DEADLINE_LABEL_RE.search(context or "")
    if dm:
        deadline = _normalize_date(dm.group(1))
    sm = STATUS_LABEL_RE.search(context or "")
    if sm:
        raw = sm.group(1).lower()
        if raw.startswith("open") or raw.startswith("abiert"):
            state = "OPEN"
        elif raw.startswith("closed") or raw.startswith("cerrad"):
            state = "CLOSED"
    return deadline, state


def parse_board_html(html: str, board_url: str = BOARD_URL) -> list[dict]:
    """Parse official IDIBAPS vacancy links from the current job-offers page.

    No role/domain prefilter is applied. Open and recently closed calls are both retained;
    the official board state is recorded separately so availability stays source-grounded.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        title = _clean(a.get_text(" ", strip=True))
        ref_m = CALL_REF_RE.search(title)
        if not ref_m:
            continue
        href = _canonical(urljoin(board_url, str(a.get("href") or "")))
        if not href or not _is_official_detail(href):
            continue
        ref = ref_m.group(1).upper()
        identity = ref or href.lower()
        if identity in seen:
            continue
        seen.add(identity)

        context = _context_for_anchor(a, ref)
        deadline, state = _metadata(context)
        desc = ["Official FRCB-IDIBAPS job listing."]
        if deadline:
            desc.append(f"Application deadline: {deadline}.")
        if state:
            desc.append(f"Portal status: {state}.")
            if state == "CLOSED":
                desc.append("Applications closed.")

        row = JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=deadline,
            url=href,
            id=ref,
            description=" ".join(desc),
            search_query="idibaps_official_job_offers",
        ).to_dict()
        row["call_reference"] = ref
        row["portal_status"] = state
        row["application_deadline_source"] = deadline
        if state:
            row["source_application_status"] = state
            row["source_status_evidence"] = f"Official IDIBAPS board state: {state}"
        rows.append(row)
    return rows


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 100,
) -> list[dict]:
    """Collect current official FRCB-IDIBAPS calls and resolve the linked call PDF."""
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_idibaps_current_job_offers",
        "coverage_scope": "official_current_job_offers_page",
        "portal_full_history_coverage": False,
        "board_fetch": "NOT_ATTEMPTED",
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
            diag["board_fetch"] = "OK"
            diag["final_url"] = r.url
            jobs = parse_board_html(r.text, r.url)
        except Exception as exc:
            diag["board_fetch"] = "FAILED"
            diag["coverage_warning"] = f"IDIBAPS job board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_jobs"] = len(jobs)
        diag["unique_jobs"] = len(jobs)
        if len(jobs) > max_jobs:
            diag["truncated"] = len(jobs) - max_jobs
            jobs = jobs[:max_jobs]
            diag["coverage_warning"] = (
                f"IDIBAPS current listing set truncated by max_jobs={max_jobs}; "
                f"{diag['truncated']} listing(s) not processed"
            )

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
                if detail and status in OK_STATUSES:
                    diag["detail_success"] += 1
                    job["trusted_full_detail_source"] = SOURCE_NAME
                    job["trusted_full_detail_url"] = job.get("url", "")
                else:
                    diag["detail_failed"] += 1

        diag["coverage_complete"] = bool(diag["board_fetch"] == "OK" and diag["truncated"] == 0)
        return jobs
    finally:
        try:
            session.close()
        except Exception:
            pass
