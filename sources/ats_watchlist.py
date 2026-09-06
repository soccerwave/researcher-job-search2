from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE = "Research Employer ATS Watchlist"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "ats_watchlist.json"
TEAMTAILOR_JOB_RE = re.compile(r"/jobs/(\d+)(?:[-/?#]|$)", re.I)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _html_text(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    return _clean(soup.get_text(" ", strip=True))


def _load_watchlist(config_path: str | Path | None = None) -> list[dict]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("employers") or []
    if not isinstance(rows, list):
        raise ValueError("ats_watchlist.json employers must be a list")
    return [dict(x) for x in rows if isinstance(x, dict) and x.get("name") and x.get("platform") and x.get("board_url")]


def parse_teamtailor_listing(html: str, board_url: str, employer: dict) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(board_url, str(a.get("href") or ""))
        m = TEAMTAILOR_JOB_RE.search(urlparse(href).path)
        if not m:
            continue
        url = href.split("#", 1)[0].rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        title = ""
        for root in (a, a.parent):
            if root is None:
                continue
            h = root.find(["h1", "h2", "h3", "h4", "h5"])
            if h:
                title = _clean(h.get_text(" ", strip=True))
                if title:
                    break
        if not title:
            slug = urlparse(url).path.rstrip("/").split("/")[-1]
            title = _clean(re.sub(r"^\d+-", "", slug).replace("-", " "))
        location = ""
        block = a.parent
        if block:
            for sel in ("[class*='location']", "[data-testid*='location']", "[class*='job-location']"):
                tag = block.select_one(sel)
                if tag:
                    location = _clean(tag.get_text(" ", strip=True))
                    if location:
                        break
        out.append(JobRecord(
            source=SOURCE,
            title=title,
            company=str(employer["name"]),
            location=location or str(employer.get("default_location") or ""),
            url=url,
            id=m.group(1),
            search_query="ats_watchlist:teamtailor",
        ).to_dict())
    return out


def parse_personio_xml(xml_text: str, employer: dict) -> list[dict]:
    root = ET.fromstring(xml_text)
    base = str(employer["board_url"]).rstrip("/")
    language = str(employer.get("language") or "en")
    out: list[dict] = []
    for pos in root.findall(".//position"):
        jid = _clean(pos.findtext("id"))
        title = _clean(pos.findtext("name"))
        if not jid or not title:
            continue
        # "RESOLUCIONES DE CONVOCATORIAS" entries are result notices, not open vacancies.
        if "resoluciones de convocatorias" in title.lower():
            continue
        office = _clean(pos.findtext("office"))
        department = _clean(pos.findtext("department"))
        parts = []
        for item in pos.findall("./jobDescriptions/jobDescription"):
            heading = _clean(item.findtext("name"))
            body = _html_text(item.findtext("value") or "")
            if heading and body:
                parts.append(f"{heading}: {body}")
            elif body:
                parts.append(body)
        full_detail = _clean("\n".join(parts))
        meta = " ".join(x for x in [department, _clean(pos.findtext("employmentType")), _clean(pos.findtext("schedule"))] if x)
        row = JobRecord(
            source=SOURCE,
            title=title,
            company=str(employer["name"]),
            location=office or str(employer.get("default_location") or ""),
            url=f"{base}/job/{jid}?language={language}",
            id=jid,
            description=meta,
            search_query="ats_watchlist:personio",
        ).to_dict()
        row["full_detail"] = full_detail
        row["detail_status"] = "OK" if full_detail else "PERSONIO_XML_DETAIL_EMPTY"
        row["source_application_status"] = "OPEN"
        row["source_status_evidence"] = "Published in Personio open-position XML feed"
        out.append(row)
    return out


def collect(
    diagnostics: dict | None = None,
    config_path: str | Path | None = None,
    max_jobs_per_employer: int = 100,
    timeout: int | tuple[int, int] = (10, 45),
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    employers = _load_watchlist(config_path)
    diag.update({
        "source": SOURCE,
        "feed_mode": "research_employer_ats_watchlist",
        "watchlist_path": str(Path(config_path) if config_path else DEFAULT_CONFIG),
        "employers_requested": len(employers),
        "employers_fetched": 0,
        "employer_errors": [],
        "platform_counts": {},
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "truncated": 0,
        "employers": {},
    })
    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    all_jobs: list[dict] = []
    try:
        for employer in employers:
            name = str(employer["name"])
            platform = str(employer["platform"]).lower()
            board_url = str(employer["board_url"])
            ediag = {"platform": platform, "board_url": board_url, "jobs": 0, "detail_success": 0, "detail_failed": 0, "error": ""}
            diag["platform_counts"][platform] = int(diag["platform_counts"].get(platform, 0)) + 1
            jobs: list[dict] = []
            try:
                if platform == "teamtailor":
                    r = session.get(board_url, timeout=timeout, allow_redirects=True)
                    r.raise_for_status()
                    jobs = parse_teamtailor_listing(r.text, r.url, employer)
                    for job in jobs:
                        diag["detail_attempts"] += 1
                        detail, status = fetch_url_text(job["url"], timeout=timeout, title_hint=job.get("title", ""), session=session)
                        job["full_detail"] = detail
                        job["detail_status"] = status
                        job["source_application_status"] = "OPEN"
                        job["source_status_evidence"] = "Listed on current Teamtailor jobs board"
                        if detail and status in {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "CACHE", "OK"}:
                            diag["detail_success"] += 1; ediag["detail_success"] += 1
                        else:
                            diag["detail_failed"] += 1; ediag["detail_failed"] += 1
                elif platform == "personio":
                    language = str(employer.get("language") or "en")
                    xml_url = board_url.rstrip("/") + f"/xml?language={language}"
                    r = session.get(xml_url, timeout=timeout, allow_redirects=True)
                    r.raise_for_status()
                    jobs = parse_personio_xml(r.text, employer)
                    ediag["xml_detail_success"] = 0
                    ediag["detail_page_fallback_attempts"] = 0
                    ediag["detail_page_fallback_success"] = 0
                    ediag["detail_page_fallback_failed"] = 0
                    for job in jobs:
                        diag["detail_attempts"] += 1
                        if job.get("full_detail") and job.get("detail_status") == "OK":
                            ediag["xml_detail_success"] += 1
                            diag["detail_success"] += 1; ediag["detail_success"] += 1
                            continue

                        # Personio's public XML feed is authoritative for discovery/open-listing
                        # membership, but some tenants omit jobDescriptions for most positions.
                        # Fall back to the public job page for the Full JD rather than
                        # quarantining an otherwise resolvable vacancy.
                        ediag["detail_page_fallback_attempts"] += 1
                        detail, status = fetch_url_text(
                            job["url"],
                            timeout=timeout,
                            title_hint=job.get("title", ""),
                            session=session,
                        )
                        if detail and status in {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "CACHE", "OK"}:
                            job["full_detail"] = detail
                            job["detail_status"] = status
                            ediag["detail_page_fallback_success"] += 1
                            diag["detail_success"] += 1; ediag["detail_success"] += 1
                        else:
                            job["detail_status"] = status or job.get("detail_status") or "PERSONIO_DETAIL_UNRESOLVED"
                            ediag["detail_page_fallback_failed"] += 1
                            diag["detail_failed"] += 1; ediag["detail_failed"] += 1
                else:
                    raise ValueError(f"Unsupported ATS platform: {platform}")
                diag["employers_fetched"] += 1
            except Exception as exc:
                ediag["error"] = f"{type(exc).__name__}: {exc}"
                diag["employer_errors"].append({"employer": name, "platform": platform, "error": ediag["error"]})
            if len(jobs) > max_jobs_per_employer:
                omitted = len(jobs) - max_jobs_per_employer
                diag["truncated"] += omitted
                jobs = jobs[:max_jobs_per_employer]
            ediag["jobs"] = len(jobs)
            diag["employers"][name] = ediag
            all_jobs.extend(jobs)

        # URL identity is authoritative inside the watchlist collector.
        unique: list[dict] = []
        seen: set[str] = set()
        for job in all_jobs:
            key = str(job.get("url") or "")
            if key and key not in seen:
                seen.add(key); unique.append(job)
        diag["parsed_jobs"] = len(all_jobs)
        diag["unique_jobs"] = len(unique)
        diag["coverage_complete"] = not diag["employer_errors"] and diag["truncated"] == 0
        diag["coverage_warning"] = "" if diag["coverage_complete"] else (
            f"ATS watchlist coverage incomplete: {len(diag['employer_errors'])} employer(s) failed" if diag["employer_errors"] else "ATS watchlist truncated"
        )
        return unique
    finally:
        session.close()
