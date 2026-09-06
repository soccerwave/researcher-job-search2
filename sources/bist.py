from __future__ import annotations

import html as html_lib
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

BASE_URL = "https://bist.eu"
BOARD_URL = f"{BASE_URL}/jobs/"
REST_ENDPOINT = f"{BASE_URL}/wp-json/wp/v2/job-listings"
AJAX_ENDPOINT = f"{BASE_URL}/jm-ajax/get_listings/"
ADMIN_AJAX_ENDPOINT = f"{BASE_URL}/wp-admin/admin-ajax.php"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = str(value)
    return re.sub(r"\s+", " ", html_lib.unescape(str(value))).strip()


def _text_from_html(value: str | None) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    return _clean(soup.get_text(" ", strip=True))


def _nested_get(data: dict, *paths: tuple[str, ...] | str) -> str:
    """Return the first non-empty value from common WP Job Manager response shapes."""
    for path in paths:
        if isinstance(path, str):
            path = (path,)
        cur: Any = data
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, "", [], {}):
            if isinstance(cur, dict) and "rendered" in cur:
                cur = cur.get("rendered")
            return _clean(cur)
    return ""


def _meta_value(item: dict, *keys: str) -> str:
    """Read public WPJM meta when the site exposes it; missing meta is normal."""
    containers = [item.get("meta") or {}, item.get("job_meta") or {}, item]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if isinstance(value, list) and value:
                value = value[0]
            if value not in (None, "", [], {}):
                return _clean(value)
    return ""


def parse_rest_payload(payload: list[dict], search_query: str = "") -> list[dict]:
    """Parse the public WP Job Manager REST collection returned by BIST.

    WP Job Manager's documented REST base is ``/wp-json/wp/v2/job-listings``.
    Public meta exposure varies by site/version, so title/link/content are primary and
    employer/location/expiry are opportunistically read when exposed.
    """
    jobs: list[dict] = []
    seen: set[str] = set()
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        title_html = _nested_get(item, ("title", "rendered"), "title")
        title = _text_from_html(title_html) if "<" in title_html else _clean(title_html)
        url = _nested_get(item, "link", "url")
        if not title or not url or "/job/" not in url:
            continue
        url = url.split("#", 1)[0]
        if url in seen:
            continue
        seen.add(url)

        content_html = _nested_get(item, ("content", "rendered"), ("excerpt", "rendered"))
        content_text = _text_from_html(content_html)
        company = _meta_value(item, "_company_name", "company_name", "company")
        location = _meta_value(item, "_job_location", "job_location", "location")
        expires = _meta_value(item, "_job_expires", "job_expires", "expires", "closing_date")
        remote = _meta_value(item, "_remote_position", "remote_position")
        posted = _nested_get(item, "date", "date_gmt")
        jid = _clean(item.get("id"))

        description_parts = []
        if content_text:
            description_parts.append(content_text[:1600])
        if expires:
            description_parts.append(f"Closing date: {expires}")

        jobs.append(JobRecord(
            source="BIST",
            title=title,
            company=company,
            location=location,
            date=posted,
            url=url,
            id=jid,
            modality="Remote" if remote.lower() in {"1", "true", "yes"} else "",
            description=" ".join(description_parts),
            search_query=search_query,
        ).to_dict())
    return jobs


def parse_ajax_html(fragment: str, search_query: str = "") -> list[dict]:
    """Parse standard WP Job Manager listing-card HTML from the BIST AJAX endpoint."""
    soup = BeautifulSoup(fragment or "", "html.parser")
    jobs: list[dict] = []
    seen: set[str] = set()

    candidates = soup.select("li.job_listing, article.job_listing, div.job_listing")
    if not candidates:
        # Conservative fallback: anchors to BIST /job/ pages in an AJAX fragment.
        candidates = []
        for a in soup.find_all("a", href=True):
            href = urljoin(BASE_URL, a.get("href", ""))
            if "/job/" not in href:
                continue
            parent = a
            for _ in range(4):
                if parent.parent is None:
                    break
                parent = parent.parent
                if len(_clean(parent.get_text(" ", strip=True))) >= 80:
                    break
            candidates.append(parent)

    for block in candidates:
        a = block.find("a", href=True)
        if not a:
            continue
        url = urljoin(BASE_URL, a.get("href", "")).split("#", 1)[0]
        if "/job/" not in url or url in seen:
            continue

        title_tag = block.find(["h2", "h3", "h4"]) or a
        title = _clean(title_tag.get_text(" ", strip=True))
        if not title:
            continue
        seen.add(url)

        company_tag = block.select_one(".company, .job_listing-company, [class*='company']")
        location_tag = block.select_one(".location, .job_listing-location, [class*='location']")
        date_tag = block.select_one(".date, time, [class*='date']")
        company = _clean(company_tag.get_text(" ", strip=True)) if company_tag else ""
        location = _clean(location_tag.get_text(" ", strip=True)) if location_tag else ""
        time_tag = date_tag.find("time") if date_tag and getattr(date_tag, "find", None) else None
        if time_tag and time_tag.has_attr("datetime"):
            posted = _clean(time_tag.get("datetime"))
        elif date_tag and date_tag.has_attr("datetime"):
            posted = _clean(date_tag.get("datetime"))
        else:
            posted = _clean(date_tag.get_text(" ", strip=True) if date_tag else "")
        text = _clean(block.get_text(" ", strip=True))

        jobs.append(JobRecord(
            source="BIST",
            title=title,
            company=company,
            location=location,
            date=posted,
            url=url,
            description=text[:1600],
            search_query=search_query,
        ).to_dict())
    return jobs


def _collect_rest(session, timeout, max_pages: int, per_page: int, diag: dict) -> list[dict]:
    jobs: list[dict] = []
    pages_fetched = 0
    total_pages = None
    for page in range(1, max_pages + 1):
        r = session.get(
            REST_ENDPOINT,
            params={"per_page": per_page, "page": page, "orderby": "date", "order": "desc"},
            timeout=timeout,
            allow_redirects=True,
        )
        if r.status_code in {400, 404} and page > 1:
            break
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "json" not in ctype:
            raise ValueError(f"BIST REST endpoint returned non-JSON content type: {ctype or 'unknown'}")
        payload = r.json()
        if not isinstance(payload, list):
            raise ValueError("BIST REST endpoint did not return a listing array")
        pages_fetched += 1
        jobs.extend(parse_rest_payload(payload))
        try:
            total_pages = int(r.headers.get("X-WP-TotalPages") or 0) or total_pages
        except Exception:
            pass
        if not payload or (total_pages and page >= total_pages) or len(payload) < per_page:
            break
    diag["rest_pages_fetched"] = pages_fetched
    diag["rest_total_pages"] = total_pages
    return jobs


def _post_ajax(session, endpoint: str, page: int, per_page: int, timeout, admin_ajax: bool = False) -> dict:
    data = {
        "page": page,
        "per_page": per_page,
        "orderby": "date",
        "order": "DESC",
        "show_pagination": "false",
        "search_keywords": "",
        "search_location": "",
        "remote_position": "",
    }
    if admin_ajax:
        data["action"] = "job_manager_get_listings"
    r = session.post(endpoint, data=data, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, dict) or "html" not in payload:
        raise ValueError("BIST WP Job Manager AJAX endpoint returned unexpected JSON")
    return payload


def _collect_ajax(session, timeout, max_pages: int, per_page: int, diag: dict) -> tuple[list[dict], str]:
    last_error = None
    for endpoint, admin in ((AJAX_ENDPOINT, False), (ADMIN_AJAX_ENDPOINT, True)):
        try:
            jobs: list[dict] = []
            pages_fetched = 0
            max_num_pages = 1
            for page in range(1, max_pages + 1):
                payload = _post_ajax(session, endpoint, page, per_page, timeout, admin_ajax=admin)
                pages_fetched += 1
                jobs.extend(parse_ajax_html(str(payload.get("html") or "")))
                try:
                    max_num_pages = max(1, int(payload.get("max_num_pages") or 1))
                except Exception:
                    max_num_pages = 1
                if page >= max_num_pages:
                    break
            diag["ajax_pages_fetched"] = pages_fetched
            diag["ajax_max_num_pages"] = max_num_pages
            return jobs, ("admin_ajax" if admin else "jm_ajax")
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"BIST AJAX collection failed: {last_error}")


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_pages: int = 5,
    per_page: int = 100,
    max_jobs: int = 100,
) -> list[dict]:
    """Collect public BIST job-board listings without browser automation.

    Preferred path: WP Job Manager's documented WordPress REST endpoint.
    Fallback: WP Job Manager's public ``get_listings`` AJAX endpoint. This avoids
    scraping a JavaScript-rendered board and keeps source collection reproducible.
    All BIST listings are allowed through to the frozen evaluator; no BIST-specific fit
    rules are introduced here.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": "BIST",
        "board_url": BOARD_URL,
        "feed_mode": None,
        "feed_fetch": "NOT_ATTEMPTED",
        "parsed_jobs": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "max_jobs": max_jobs,
        "truncated": 0,
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.2)
    try:
        jobs: list[dict] = []
        rest_error = None
        try:
            jobs = _collect_rest(session, timeout, max_pages=max_pages, per_page=min(100, max(1, per_page)), diag=diag)
            if not jobs:
                raise ValueError("BIST REST feed returned zero usable /job/ listings")
            diag["feed_mode"] = "wp_rest"
            diag["feed_fetch"] = "OK"
        except Exception as exc:
            rest_error = f"{type(exc).__name__}: {exc}"
            diag["rest_error"] = rest_error
            jobs, ajax_mode = _collect_ajax(session, timeout, max_pages=max_pages, per_page=min(100, max(1, per_page)), diag=diag)
            if not jobs:
                raise ValueError("BIST AJAX feed returned zero usable job listings")
            diag["feed_mode"] = ajax_mode
            diag["feed_fetch"] = "OK"

        # De-duplicate feed artefacts by canonical URL before detail requests.
        by_url: dict[str, dict] = {}
        for job in jobs:
            url = str(job.get("url") or "").strip().rstrip("/")
            if url and url not in by_url:
                by_url[url] = job
        jobs = list(by_url.values())
        diag["parsed_jobs_before_limit"] = len(jobs)
        if len(jobs) > max_jobs:
            diag["truncated"] = len(jobs) - max_jobs
            jobs = jobs[:max_jobs]
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
