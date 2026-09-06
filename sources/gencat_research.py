from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "Gencat Research Staff"
BOARD_URL = (
    "https://web.gencat.cat/es/generalitat/com-ens-organitzem/departaments/"
    "recerca-universitats/ofertes-feina-pdi-centres-recerca-universitats/personal-investigador"
)

_VALIDITY_MARKER = re.compile(
    r"(?:per[ií]odo|per[ií]ode)\s+de\s+vig[eè]ncia|validity\s+period",
    re.I,
)
_UNTIL_MARKER = re.compile(r"\b(?:hasta|fins(?:\s+el)?|until)\b\s*(.+)$", re.I)
_FILLED_MARKER = re.compile(
    r"(?:su\s+cobertura|la\s+seva\s+cobertura|position\s+is\s+filled|filled|until\s+filled)",
    re.I,
)

_DOMAIN_COMPANIES = {
    "ieec.cat": "IEEC",
    "ibecbarcelona.eu": "IBEC",
    "icra.cat": "ICRA",
    "iciq.org": "ICIQ",
    "icfo.eu": "ICFO",
    "icn2.cat": "ICN2",
}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _is_candidate_link(href: str, title: str) -> bool:
    if not href or href.startswith(("mailto:", "javascript:", "#")):
        return False
    if len(title) < 12:
        return False
    low = title.lower()
    if low in {"más información", "more information", "més informació", "accesibilidad", "accessibility"}:
        return False
    try:
        host = urlparse(href).netloc.lower()
    except Exception:
        host = ""
    # Actual vacancies on this government aggregator link to the hiring institution.
    # Keep same-host links only if they are not generic Gencat navigation.
    if host.endswith("gencat.cat") and "/personal-investigador" not in href:
        return False
    return True


def _nearby_validity_text(anchor: Tag) -> str:
    """Return the compact listing block associated with a vacancy anchor.

    Gencat has changed markup over time. Prefer semantic list/container ancestors, then
    fall back to nearby document-order text. A candidate is accepted only when a
    validity-period marker is present, which prevents navigation links becoming jobs.
    """
    for parent_name in ("li", "article", "section", "div"):
        parent = anchor.find_parent(parent_name)
        if parent is None:
            continue
        text = _clean(parent.get_text(" ", strip=True))
        if _VALIDITY_MARKER.search(text) and len(text) <= 3500:
            return text

    parts: list[str] = []
    for node in anchor.next_elements:
        if node is anchor:
            continue
        if isinstance(node, Tag) and node.name == "a" and node is not anchor:
            # Once another substantial anchor begins, this vacancy's local block is over.
            other = _clean(node.get_text(" ", strip=True))
            if len(other) >= 12:
                break
        if isinstance(node, NavigableString):
            text = _clean(str(node))
            if text and text != _clean(anchor.get_text(" ", strip=True)):
                parts.append(text)
                joined = _clean(" ".join(parts))
                if _VALIDITY_MARKER.search(joined) and len(joined) >= 20:
                    # Capture a little extra context after the marker, but avoid wandering.
                    if _UNTIL_MARKER.search(joined) or len(joined) > 280:
                        return joined[:1200]
        if len(parts) >= 14:
            break
    return _clean(" ".join(parts))


def _validity_value(block: str) -> tuple[str, bool]:
    if not block or not _VALIDITY_MARKER.search(block):
        return "", False
    # Focus on the text after the validity-period label before extracting "until".
    marker = _VALIDITY_MARKER.search(block)
    tail = block[marker.end():] if marker else block
    m = _UNTIL_MARKER.search(tail)
    if not m:
        return "", False
    raw = _clean(m.group(1))
    # Parent containers can contain the next vacancy too; stop at a likely next marker.
    raw = re.split(r"\s+(?:(?:per[ií]odo|per[ií]ode)\s+de\s+vig[eè]ncia|validity\s+period)\s*:", raw, maxsplit=1, flags=re.I)[0]
    raw = raw.strip(" .;–—-")
    is_filled = bool(_FILLED_MARKER.search(raw))
    if is_filled:
        return "", True

    # Keep only a plausible date phrase. The source currently publishes day + month + year.
    dm = re.search(
        r"(\d{1,2}(?:\s+de)?\s+[A-Za-zÁÉÍÓÚÀÈÒáéíóúàèòñÑçÇ]+(?:\s+de)?\s+\d{4}|"
        r"\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2})",
        raw,
        re.I,
    )
    return (_clean(dm.group(1)) if dm else ""), False


def _company_from_title_url(title: str, url: str) -> str:
    # Gencat normally appends the hiring-centre acronym to the vacancy title.
    m = re.search(r"\(\s*([A-Z][A-Z0-9-]{1,14})\s*\)\s*[.]?$", title)
    if m:
        return m.group(1)
    host = urlparse(url).netloc.lower().split(":", 1)[0]
    host = host[4:] if host.startswith("www.") else host
    for domain, company in _DOMAIN_COMPANIES.items():
        if host == domain or host.endswith("." + domain):
            return company
    return ""


def _detail_title_hint(title: str) -> str:
    # Do not make title-identity validation depend on the aggregator's trailing org tag.
    return _clean(re.sub(r"\s*\(\s*[A-Z][A-Z0-9-]{1,14}\s*\)\s*[.]?$", "", title))


def parse_board_html(html: str, search_query: str = "gencat_research_staff") -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "aside"]):
        tag.decompose()

    jobs: list[dict] = []
    for anchor in soup.find_all("a", href=True):
        title = _clean(anchor.get_text(" ", strip=True))
        href = urljoin(BOARD_URL, anchor.get("href", ""))
        if not _is_candidate_link(href, title):
            continue
        block = _nearby_validity_text(anchor)
        deadline, until_filled = _validity_value(block)
        if not (deadline or until_filled):
            continue

        company = _company_from_title_url(title, href)
        if until_filled:
            description = "Official Gencat research-staff listing. Applications open until the position is filled."
            date_value = ""
        else:
            # Spanish wording is intentionally explicit so the existing availability parser
            # can consume it without any source-specific scoring/availability modification.
            description = f"Official Gencat research-staff listing. Fecha límite: {deadline}."
            date_value = deadline

        jobs.append(JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=company,
            location="",
            date=date_value,
            url=href,
            description=description,
            search_query=search_query,
        ).to_dict())

    # URL is strongest here because the aggregator links directly to the employer vacancy.
    dedup: dict[tuple[str, str], dict] = {}
    for job in jobs:
        key = (job["url"].rstrip("/").lower(), job["title"].lower())
        dedup.setdefault(key, job)
    return list(dedup.values())


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    max_jobs: int = 100,
    diagnostics: dict | None = None,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_gencat_research_staff",
        "board_fetch": "NOT_ATTEMPTED",
        "parsed_jobs": 0,
        "parsed_jobs_before_limit": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "truncated": 0,
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

        all_jobs = parse_board_html(response.text)
        diag["parsed_jobs_before_limit"] = len(all_jobs)
        jobs = all_jobs[:max_jobs]
        diag["parsed_jobs"] = len(jobs)
        diag["truncated"] = max(0, len(all_jobs) - len(jobs))

        if enrich_detail:
            for job in jobs:
                diag["detail_attempts"] += 1
                detail, status = fetch_url_text(
                    job.get("url", ""),
                    timeout=(10, 45),
                    title_hint=_detail_title_hint(job.get("title", "")),
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
