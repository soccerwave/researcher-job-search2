from __future__ import annotations

import re
from collections import OrderedDict
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "Ikerbasque Calls"
BOARD_URL = "https://www.ikerbasque.net/en/calls"
DEFAULT_MAX_CALLS = 20
OK_DETAIL_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK"}

_GENERIC_LINK_LABELS = {
    "read more",
    "more info",
    "learn more",
    "apply",
    "application",
    "calls",
    "evaluation",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _canonical_call_url(href: str, base_url: str = BOARD_URL) -> str:
    url = urljoin(base_url, href or "")
    parsed = urlparse(url)
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}" if parsed.scheme and parsed.netloc else url


def _is_call_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").rstrip("/")
    if host not in {"ikerbasque.net", "www.ikerbasque.net"}:
        return False
    if not path.startswith("/en/calls/"):
        return False
    slug = path.rsplit("/", 1)[-1].lower()
    if not slug or slug in {"evaluation", "calls"}:
        return False
    return True


def _status_from_text(text: str) -> str:
    text = _clean(text)
    if re.search(r"\bclosed\b", text, re.I):
        return "CLOSED"
    if re.search(r"\bopen\b", text, re.I):
        return "OPEN"
    return ""


def _best_container_text(anchor) -> str:
    """Prefer a local call card carrying one call's status, never page-wide text."""
    node = anchor
    for _ in range(7):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if not text:
            continue
        if _status_from_text(text):
            # Navigation/main/body wrappers can contain several calls and therefore
            # both Open and Closed words. Treat status as authoritative only when the
            # local ancestor refers to exactly one distinct call detail URL.
            call_urls = {
                _canonical_call_url(a.get("href", ""))
                for a in node.find_all("a", href=True)
                if _is_call_detail_url(_canonical_call_url(a.get("href", "")))
            }
            if len(call_urls) == 1 and len(text) <= 2400:
                return text
        if len(text) > 6000:
            break
    return ""


def _title_candidate(anchor, container_text: str) -> str:
    label = _clean(anchor.get_text(" ", strip=True))
    if label and label.lower() not in _GENERIC_LINK_LABELS and len(label) >= 4:
        return label

    # Common Drupal/card layouts put the call title in a nearby heading while the
    # clickable CTA itself says "Read more".
    node = anchor
    for _ in range(5):
        node = getattr(node, "parent", None)
        if node is None:
            break
        heading = node.find(["h2", "h3", "h4"])
        if heading:
            text = _clean(heading.get_text(" ", strip=True))
            if text and text.lower() not in _GENERIC_LINK_LABELS:
                return text

    # Last conservative fallback: strip the status/CTA from a compact card text.
    text = re.sub(r"\b(?:Open|Closed)\b", " ", container_text or "", flags=re.I)
    text = re.sub(r"\bRead more\b", " ", text, flags=re.I)
    text = _clean(text)
    return text[:220] if text else label


def parse_board_html(html: str, base_url: str = BOARD_URL) -> list[dict]:
    """Parse the public Ikerbasque calls index into one row per call.

    The page repeats call links in navigation and in each content card. We deduplicate
    by the official detail URL and prefer the occurrence carrying a local Open/Closed
    board marker. No relevance filtering is applied here: the frozen scorer decides fit.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    by_url: OrderedDict[str, dict] = OrderedDict()

    for anchor in soup.find_all("a", href=True):
        url = _canonical_call_url(anchor.get("href", ""), base_url)
        if not _is_call_detail_url(url):
            continue

        container_text = _best_container_text(anchor)
        status = _status_from_text(container_text)
        title = _title_candidate(anchor, container_text)
        if not title:
            continue

        parsed = urlparse(url)
        call_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        summary = container_text
        existing = by_url.get(url)

        candidate = {
            "source": SOURCE_NAME,
            "title": title,
            "company": "Ikerbasque",
            "location": "Basque Country, Spain",
            "date": "",
            "url": url,
            "id": call_id,
            "description": summary,
            "call_status": status,
        }
        if status:
            candidate["source_application_status"] = status
            candidate["source_status_evidence"] = f"Official Ikerbasque calls board status: {status.title()}"

        if existing is None:
            by_url[url] = candidate
            continue

        # Prefer a content-card occurrence that has an explicit status. Otherwise keep
        # the better title/summary from duplicate navigation/content links.
        existing_status = str(existing.get("call_status") or "")
        if status and not existing_status:
            by_url[url] = candidate
        else:
            if len(title) > len(str(existing.get("title") or "")) and title.lower() not in _GENERIC_LINK_LABELS:
                existing["title"] = title
            if len(summary) > len(str(existing.get("description") or "")) and len(summary) <= 2400:
                existing["description"] = summary
            if status and existing_status == status:
                existing["source_application_status"] = status
                existing["source_status_evidence"] = f"Official Ikerbasque calls board status: {status.title()}"

    return list(by_url.values())


def collect(
    diagnostics=None,
    max_calls: int = DEFAULT_MAX_CALLS,
    enrich_detail: bool = True,
    timeout=(10, 45),
    session=None,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_ikerbasque_calls_lightweight_monitor",
        "board_fetched": False,
        "parsed_calls": 0,
        "unique_calls": 0,
        "open_calls": 0,
        "closed_calls": 0,
        "status_unknown": 0,
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
            rows = parse_board_html(response.text, base_url=response.url or BOARD_URL)
        except Exception as exc:
            diag["coverage_warning"] = f"Ikerbasque calls board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_calls"] = len(rows)
        diag["unique_calls"] = len(rows)
        diag["open_calls"] = sum(r.get("call_status") == "OPEN" for r in rows)
        diag["closed_calls"] = sum(r.get("call_status") == "CLOSED" for r in rows)
        diag["status_unknown"] = sum(not r.get("call_status") for r in rows)

        if len(rows) > max_calls:
            diag["truncated"] = len(rows) - max_calls
            rows = rows[:max_calls]
            diag["coverage_warning"] = (
                f"Ikerbasque call set truncated by max_calls={max_calls}; "
                f"{diag['truncated']} call(s) not processed"
            )

        if enrich_detail:
            for job in rows:
                diag["detail_attempts"] += 1
                detail, status = fetch_url_text(
                    job.get("url", ""),
                    timeout=timeout,
                    title_hint=job.get("title", ""),
                    session=session,
                    follow_job_attachments=True,
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
            diag["coverage_warning"] = "Ikerbasque calls coverage incomplete"
        return rows
    finally:
        if own_session and session is not None:
            try:
                session.close()
            except Exception:
                pass
