from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from sources.common import JobRecord
from sources.fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "CSIC Barcelona Institutes"

ICM_BOARD_URL = "https://www.icm.csic.es/es/ofertas-de-trabajo"
IQAC_BOARD_URL = "https://www.iqac.csic.es/en/join-us/"
IMB_CNM_BOARD_URL = "https://www.imb-cnm.csic.es/es/investigacion/carrera-investigadora/ofertas-abiertas"

_VALID_DETAIL_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}
_SPACE_RE = re.compile(r"\s+")
_DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")


def _clean(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def _stable_id(institute: str, url: str) -> str:
    digest = hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:16]
    return f"{institute}:{digest}"


def _nearby_date(anchor) -> str:
    for parent_name in ("article", "li", "section", "div"):
        parent = anchor.find_parent(parent_name)
        if parent is None:
            continue
        text = _clean(parent.get_text(" ", strip=True))
        if len(text) > 3000:
            continue
        time_tag = parent.find("time")
        if time_tag is not None:
            value = _clean(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))
            if value:
                return value
        match = _DATE_NUMERIC_RE.search(text)
        if match:
            return match.group(1)
    return ""


def _job_record(*, institute: str, company: str, location: str, title: str, url: str, date: str = "") -> dict:
    return JobRecord(
        source=SOURCE_NAME,
        title=_clean(title),
        company=company,
        location=location,
        date=_clean(date),
        url=url,
        id=_stable_id(institute, url),
        description=f"Official {company} job listing collected from its institute careers board.",
        search_query=f"csic_institutes_{institute}",
    ).to_dict()


def parse_icm_board_html(html: str) -> list[dict]:
    """Parse only the ICM current-job board, never its closed-job archive."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup
    jobs: list[dict] = []
    seen: set[str] = set()
    for anchor in root.find_all("a", href=True):
        href = urljoin(ICM_BOARD_URL, anchor.get("href", ""))
        path = urlparse(href).path.lower()
        if not re.search(r"/(?:es|en|ca)/(?:oferta-trabajo|oferta-treball|calls)/[^/]+/?$", path):
            continue
        title = _clean(anchor.get_text(" ", strip=True))
        if len(title) < 6 or href in seen:
            continue
        seen.add(href)
        jobs.append(_job_record(
            institute="icm",
            company="ICM-CSIC",
            location="Barcelona, Spain",
            title=title,
            url=href,
            date=_nearby_date(anchor),
        ))
    return jobs


def parse_iqac_board_html(html: str) -> list[dict]:
    """Parse IQAC job-offer cards from the official Join us page."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup
    jobs: list[dict] = []
    seen: set[str] = set()
    for anchor in root.find_all("a", href=True):
        href = urljoin(IQAC_BOARD_URL, anchor.get("href", ""))
        path = urlparse(href).path.lower()
        if "/join-iqac/" not in path:
            continue
        title = _clean(anchor.get_text(" ", strip=True))
        if len(title) < 6 or href in seen:
            continue
        seen.add(href)
        jobs.append(_job_record(
            institute="iqac",
            company="IQAC-CSIC",
            location="Barcelona, Spain",
            title=title,
            url=href,
            date=_nearby_date(anchor),
        ))
    return jobs


def parse_imb_cnm_board_html(html: str) -> list[dict]:
    """Parse only IMB-CNM's open employment section.

    The same page also contains TFG/TFM opportunities and a closed/evaluation section.
    Collection deliberately stops at the next H2 so those records never enter the
    production vacancy set.
    """
    soup = BeautifulSoup(html, "html.parser")
    heading = None
    for h2 in soup.find_all("h2"):
        if "ofertas de trabajo" in _clean(h2.get_text(" ", strip=True)).lower():
            heading = h2
            break
    if heading is None:
        return []

    jobs: list[dict] = []
    seen: set[str] = set()
    for node in heading.find_all_next():
        if node is not heading and getattr(node, "name", None) == "h2":
            break
        if getattr(node, "name", None) != "a" or not node.get("href"):
            continue
        href = urljoin(IMB_CNM_BOARD_URL, node.get("href", ""))
        if href.startswith("mailto:") or href in seen:
            continue
        title = _clean(node.get_text(" ", strip=True))
        if len(title) < 6:
            continue
        seen.add(href)
        jobs.append(_job_record(
            institute="imb_cnm",
            company="IMB-CNM-CSIC",
            location="Cerdanyola del Vallès, Barcelona, Spain",
            title=title,
            url=href,
            date=_nearby_date(node),
        ))
    return jobs


_BOARDS = (
    ("icm", "ICM-CSIC", ICM_BOARD_URL, parse_icm_board_html),
    ("iqac", "IQAC-CSIC", IQAC_BOARD_URL, parse_iqac_board_html),
    ("imb_cnm", "IMB-CNM-CSIC", IMB_CNM_BOARD_URL, parse_imb_cnm_board_html),
)


def collect(
    max_jobs: int = 100,
    timeout: int | tuple[int, int] = (10, 30),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
) -> list[dict]:
    """Collect a curated set of official Barcelona-area CSIC institute boards.

    This intentionally does *not* claim all-CSIC coverage. It replaces the unreliable
    central Sede transport with three public institute boards chosen for local research
    and research/project-management relevance. Each board fails soft independently.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "feed_mode": "official_csic_barcelona_institute_boards",
        "coverage_scope": "curated_official_barcelona_institute_boards",
        "portal_full_coverage": False,
        "institutes_requested": [key for key, *_ in _BOARDS],
        "boards_requested": len(_BOARDS),
        "boards_fetched": 0,
        "board_errors": [],
        "board_job_counts": {},
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "coverage_complete": False,
        "coverage_warning": "",
        "per_board": {},
    })

    session = make_retry_session(total_retries=2, backoff_factor=0.8)
    try:
        collected: list[dict] = []
        seen_urls: set[str] = set()

        for key, company, board_url, parser in _BOARDS:
            board_diag = {
                "company": company,
                "board_url": board_url,
                "board_fetched": False,
                "jobs_parsed": 0,
                "error": "",
            }
            diag["per_board"][key] = board_diag
            try:
                response = session.get(board_url, timeout=timeout, allow_redirects=True)
                response.raise_for_status()
                rows = parser(response.text)
                board_diag["board_fetched"] = True
                board_diag["jobs_parsed"] = len(rows)
                diag["boards_fetched"] += 1
                diag["board_job_counts"][key] = len(rows)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                board_diag["error"] = error
                diag["board_errors"].append({"institute": key, "url": board_url, "error": error})
                diag["board_job_counts"][key] = 0
                continue

            for row in rows:
                url = str(row.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                collected.append(row)

        diag["unique_jobs"] = len(collected)
        limit = max(0, int(max_jobs))
        if limit and len(collected) > limit:
            diag["truncated"] = len(collected) - limit
            collected = collected[:limit]
        diag["parsed_jobs"] = len(collected)

        diag["coverage_complete"] = (
            diag["boards_fetched"] == diag["boards_requested"]
            and not diag["board_errors"]
            and diag["truncated"] == 0
        )
        if diag["board_errors"]:
            diag["coverage_warning"] = (
                "CSIC institute coverage incomplete: "
                f"{len(diag['board_errors'])} of {diag['boards_requested']} official institute board(s) failed"
            )
        elif diag["truncated"]:
            diag["coverage_warning"] = f"CSIC institute listing set truncated by max_jobs ({diag['truncated']} omitted)"

        if enrich_detail:
            for job in collected:
                diag["detail_attempts"] += 1
                detail, status = fetch_url_text(
                    str(job.get("url") or ""),
                    timeout=(10, 45),
                    title_hint=str(job.get("title") or ""),
                    session=session,
                    follow_job_attachments=True,
                )
                job["full_detail"] = detail
                job["detail_status"] = status
                if detail and status in _VALID_DETAIL_STATUSES:
                    diag["detail_success"] += 1
                else:
                    diag["detail_failed"] += 1

        return collected
    finally:
        session.close()
