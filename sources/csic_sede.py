from __future__ import annotations

import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from sources.common import JobRecord
from sources.fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "CSIC Sede"
BOARD_URL = "https://sede.csic.gob.es/tramites/convocatorias-de-personal"


def _relay_config() -> tuple[str, str]:
    """Return the optional fixed-purpose CSIC Cloudflare relay configuration.

    Local/direct collection remains unchanged when both values are absent.  When a
    relay is configured, only the hard-coded board/detail routes are used; the
    public canonical CSIC URLs stored on JobRecord objects never change.
    """
    base = str(os.getenv("CSIC_RELAY_URL") or "").strip().rstrip("/")
    token = str(os.getenv("CSIC_RELAY_TOKEN") or "").strip()
    return base, token


def _relay_board_url(base: str, page: int) -> str:
    return f"{base}/board?page={int(page)}"


def _relay_detail_url(base: str, vacancy_id: str) -> str:
    return f"{base}/convocatoria/{vacancy_id}"
_DETAIL_RE = re.compile(r"/tramites/convocatorias-de-personal/convocatoria/(\d+)(?:$|[?#/])", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _listing_date(anchor) -> str:
    """Return the publication date attached to one CSIC listing.

    The Sede currently renders a date immediately before each vacancy link.  We
    deliberately search only a short local neighbourhood so dates from adjacent
    vacancies/navigation cannot leak into this record.
    """
    for parent_name in ("li", "article", "section", "div"):
        parent = anchor.find_parent(parent_name)
        if parent is None:
            continue
        text = _clean(parent.get_text(" ", strip=True))
        m = _DATE_RE.search(text)
        if m and len(text) <= 1800:
            return m.group(1)

    prev = anchor
    for _ in range(6):
        prev = prev.previous_element
        if prev is None:
            break
        text = _clean(getattr(prev, "get_text", lambda *a, **k: str(prev))(" ", strip=True) if hasattr(prev, "get_text") else str(prev))
        m = _DATE_RE.search(text)
        if m:
            return m.group(1)
    return ""


def parse_board_html(html: str, search_query: str = "csic_sede_personal") -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = urljoin(BOARD_URL, anchor.get("href", ""))
        m = _DETAIL_RE.search(href)
        if not m:
            continue
        vacancy_id = m.group(1)
        if vacancy_id in seen_ids:
            continue
        title = _clean(anchor.get_text(" ", strip=True))
        if len(title) < 8:
            continue
        seen_ids.add(vacancy_id)
        pub_date = _listing_date(anchor)
        jobs.append(JobRecord(
            source=SOURCE_NAME,
            title=title,
            company="CSIC",
            location="",
            date=pub_date,
            url=href,
            id=vacancy_id,
            description=(
                f"Official CSIC Sede personnel/employment call. Publication date: {pub_date}."
                if pub_date else "Official CSIC Sede personnel/employment call."
            ),
            search_query=search_query,
        ).to_dict())
    return jobs


def collect(
    max_pages: int = 3,
    max_jobs: int = 100,
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_csic_sede_newest_pages",
        "coverage_scope": "newest_requested_pages",
        "portal_full_coverage": False,
        "pages_requested": max_pages,
        "pages_fetched": 0,
        "page_errors": [],
        "page_job_counts": [],
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "coverage_complete": False,
        "coverage_warning": "",
    })

    relay_base, relay_token = _relay_config()
    relay_requested = bool(relay_base or relay_token)
    relay_configured = bool(relay_base and relay_token)
    diag["relay_configured"] = relay_configured
    diag["relay_configuration_incomplete"] = relay_requested and not relay_configured
    diag["board_transport"] = "cloudflare_relay" if relay_configured else "direct"
    diag["detail_transport_counts"] = {"cloudflare_relay": 0, "direct": 0}

    if diag["relay_configuration_incomplete"]:
        diag["coverage_warning"] = "CSIC relay configuration incomplete: both CSIC_RELAY_URL and CSIC_RELAY_TOKEN are required"
        return []

    # Direct mode preserves the original bounded retry policy.  Relay mode performs
    # one GitHub-side attempt; the Worker owns its own bounded upstream timeout.
    session = make_retry_session(
        total_retries=0 if relay_configured else 3,
        backoff_factor=0.0 if relay_configured else 1.2,
    )
    if relay_configured and hasattr(session, "headers"):
        session.headers.update({"Authorization": f"Bearer {relay_token}"})

    try:
        collected: list[dict] = []
        seen_ids: set[str] = set()
        for page in range(max(1, int(max_pages))):
            canonical_url = BOARD_URL if page == 0 else f"{BOARD_URL}?page={page}"
            transport_url = _relay_board_url(relay_base, page) if relay_configured else canonical_url
            try:
                response = session.get(transport_url, timeout=timeout, allow_redirects=True)
                response.raise_for_status()
            except Exception as exc:
                diag["page_errors"].append({"page": page, "url": canonical_url, "transport_url": transport_url, "error": f"{type(exc).__name__}: {exc}"})
                if page == 0:
                    break
                continue

            rows = parse_board_html(response.text)
            diag["pages_fetched"] += 1
            diag["page_job_counts"].append(len(rows))
            if not rows:
                # End of listing is valid full coverage for the requested newest-page scan.
                break

            new_on_page = 0
            for row in rows:
                rid = str(row.get("id") or "")
                if rid and rid in seen_ids:
                    continue
                if rid:
                    seen_ids.add(rid)
                collected.append(row)
                new_on_page += 1
            if new_on_page == 0:
                break

        diag["unique_jobs"] = len(collected)
        if len(collected) > max_jobs:
            diag["truncated"] = len(collected) - max_jobs
            collected = collected[:max_jobs]
        diag["parsed_jobs"] = len(collected)
        diag["coverage_complete"] = diag["pages_fetched"] > 0 and not diag["page_errors"] and diag["truncated"] == 0
        if not diag["coverage_complete"]:
            if diag["page_errors"]:
                diag["coverage_warning"] = "CSIC Sede newest-page scan incomplete because one or more requested pages failed"
            elif diag["truncated"]:
                diag["coverage_warning"] = f"CSIC Sede listing set truncated by max_jobs ({diag['truncated']} omitted)"

        if enrich_detail:
            for job in collected:
                diag["detail_attempts"] += 1
                vacancy_id = str(job.get("id") or "")
                transport_url = (
                    _relay_detail_url(relay_base, vacancy_id)
                    if relay_configured and vacancy_id
                    else job.get("url", "")
                )
                transport_key = "cloudflare_relay" if relay_configured and vacancy_id else "direct"
                diag["detail_transport_counts"][transport_key] += 1
                detail, status = fetch_url_text(
                    transport_url,
                    timeout=(10, 45),
                    title_hint=job.get("title", ""),
                    session=session,
                    # Relay responses preserve the official CSIC HTML body, but relative
                    # attachment URLs should not be resolved against the Worker origin.
                    # The official vacancy page itself is therefore the integrity source.
                    follow_job_attachments=not relay_configured,
                )
                job["full_detail"] = detail
                job["detail_status"] = status
                if detail and status in {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}:
                    diag["detail_success"] += 1
                else:
                    diag["detail_failed"] += 1

        return collected
    finally:
        session.close()
