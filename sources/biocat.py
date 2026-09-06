from __future__ import annotations
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

BASE_URL = "https://www.biocat.cat"
BOARD_URL = f"{BASE_URL}/en/job-board"


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_board_html(html: str, search_query: str = "") -> list[dict]:
    """Parse Biocat's public job-board page conservatively.

    The page structure can change, so this parser deliberately relies on text labels
    (Entity, Sector, Location, Ends) rather than one brittle CSS selector.
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []

    # Candidate headings are job titles on the board. We walk up to a compact parent
    # containing the metadata labels, which is more robust than depending on Drupal classes.
    for heading in soup.find_all(["h2", "h3", "h4"]):
        title = _clean(heading.get_text(" ", strip=True))
        if not title or title.lower() in {"all offers", "search and filters"}:
            continue

        parent = heading
        block = ""
        chosen = None
        for _ in range(6):
            parent = parent.parent
            if parent is None:
                break
            text = _clean(parent.get_text(" ", strip=True))
            if "Location:" in text and ("Entity:" in text or "Sector:" in text or "Ends:" in text):
                block = text
                chosen = parent
                break
        if not chosen:
            continue

        # Avoid treating section headings as jobs.
        if len(title) < 4:
            continue

        company = ""
        # On Biocat, employer/category text commonly appears immediately before the title.
        prev = heading.find_previous(string=True)
        if prev:
            prev_txt = _clean(str(prev))
            if prev_txt and prev_txt != title and len(prev_txt) < 180:
                company = re.sub(r"\s*[-–—]\s*(?:Postdoc|Researcher|Technical|Executive|Predoc|Others)\s*$", "", prev_txt, flags=re.I)

        def field(label: str) -> str:
            m = re.search(rf"{re.escape(label)}:\s*(.*?)(?=\s+(?:Entity|Sector|Location|Ends):|$)", block, re.I)
            return _clean(m.group(1)) if m else ""

        location = field("Location")
        ends = field("Ends")
        sector = field("Sector")
        entity = field("Entity")

        link = heading.find("a", href=True) or (chosen.find("a", href=True) if chosen else None)
        url = urljoin(BASE_URL, link["href"]) if link else BOARD_URL

        description = "; ".join(x for x in [f"Entity: {entity}" if entity else "", f"Sector: {sector}" if sector else ""] if x)
        jobs.append(JobRecord(
            source="Biocat",
            title=title,
            company=company,
            location=location,
            date=ends,
            url=url,
            description=description,
            search_query=search_query,
        ).to_dict())

    # De-duplicate parser artefacts by title/company/location.
    dedup = {}
    for job in jobs:
        key = (job["title"].lower(), job["company"].lower(), job["location"].lower())
        dedup.setdefault(key, job)
    return list(dedup.values())


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
) -> list[dict]:
    """Collect Biocat jobs with retry handling for transient timeouts.

    Diagnostics are optional and do not change the return type used by the rest of the bot.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": "Biocat",
        "board_url": BOARD_URL,
        "board_fetch": "NOT_ATTEMPTED",
        "parsed_jobs": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.2)
    try:
        try:
            response = session.get(BOARD_URL, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            diag["board_fetch"] = "OK"
            diag["final_url"] = response.url
        except Exception as exc:
            diag["board_fetch"] = "FAILED"
            diag["board_error"] = f"{type(exc).__name__}: {exc}"
            raise

        jobs = parse_board_html(response.text)
        diag["parsed_jobs"] = len(jobs)

        if enrich_detail:
            for job in jobs:
                diag["detail_attempts"] += 1
                detail, status = fetch_url_text(
                    job.get("url", ""),
                    timeout=(10, 45),
                    title_hint=job.get("title", ""),
                    session=session,
                )
                job["full_detail"] = detail
                job["detail_status"] = status
                if detail and status in {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}:
                    diag["detail_success"] += 1
                else:
                    diag["detail_failed"] += 1

        return jobs
    finally:
        session.close()
