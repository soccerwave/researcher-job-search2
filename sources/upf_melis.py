from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "UPF MELIS Job Offers"
COMPANY = "Universitat Pompeu Fabra (UPF) - MELIS"
DEFAULT_LOCATION = "Barcelona, Spain"
BOARD_URL = "https://www.upf.edu/en/web/biomed/job-offers"

_REF_RE = re.compile(r"\bMELIS-[A-Z0-9.]+(?:-[A-Z0-9.]+)*-20\d{2}(?:-[A-Z0-9.]+)+\b", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/(?:20)?\d{2}|\d{4}-\d{1,2}-\d{1,2})\b")
_DEADLINE_RE = re.compile(
    r"(?:Termini\s+de\s+presentaci[oó]\s+de\s+sol[·l]licituds|"
    r"Deadline\s+to\s+submit\s+applications|Application\s+deadline|"
    r"Deadline|Data\s+l[ií]mit|Fecha\s+l[ií]mite)\s*:?\s*"
    r"(\d{1,2}/\d{1,2}/(?:20)?\d{2}|\d{4}-\d{1,2}-\d{1,2})",
    re.I,
)
_YEAR_HEADING_RE = re.compile(r"^20\d{2}$")

# These labels indicate that the application phase has already progressed beyond submission.
_CLOSED_PROCESS_CUES = (
    "llista provisional", "llista definitiva", "admesos", "exclosos", "admitidos", "excluidos",
    "proposta de provis", "proposta d'adjudic", "proposta contract", "resoluci\u00f3 d'adjudic",
    "resolucion de adjudic", "resultats", "results", "selection results",
)

# Strong candidates for the original vacancy description / call bases.
_DETAIL_CUES = (
    "bases de la convocat\u00f2ria", "bases de la convocatoria", "call bases", "terms of the call",
    "job opening", "job offer", "oferta", "web offer",
)
_BAD_DETAIL_CUES = (
    "llista provisional", "llista definitiva", "admes", "exclos", "admit", "exclude",
    "proposta", "adjudic", "resultat", "result", "tribunal", "esmena", "correction",
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _canonical(url: str) -> str:
    return (url or "").split("#", 1)[0].strip()


def _is_upf(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "upf.edu" or host.endswith(".upf.edu")


def _normalize_date(raw: str) -> str:
    raw = _clean(raw)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", raw)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{int(d):02d}/{int(mo):02d}/{y}"
    return raw


def _direct_li_text(li: Tag) -> str:
    """Text for the vacancy line itself, excluding nested process-document lists."""
    parts: list[str] = []
    for child in li.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name in {"ul", "ol"}:
                continue
            parts.append(child.get_text(" ", strip=True))
    return _clean(" ".join(parts))


def _latest_year_root(soup: BeautifulSoup) -> tuple[int | None, list[Tag]]:
    headings: list[tuple[int, Tag]] = []
    for h in soup.find_all(["h2", "h3", "h4"]):
        text = _clean(h.get_text(" ", strip=True))
        if _YEAR_HEADING_RE.fullmatch(text):
            headings.append((int(text), h))
    if not headings:
        return None, []
    year, heading = max(headings, key=lambda x: x[0])
    nodes: list[Tag] = []
    for sib in heading.next_siblings:
        if isinstance(sib, Tag) and sib.name in {"h2", "h3", "h4"}:
            txt = _clean(sib.get_text(" ", strip=True))
            if _YEAR_HEADING_RE.fullmatch(txt):
                break
        if isinstance(sib, Tag):
            nodes.append(sib)
    return year, nodes


def _job_nodes_for_latest_year(soup: BeautifulSoup) -> tuple[int | None, list[Tag]]:
    year, roots = _latest_year_root(soup)
    if year is None:
        # Defensive fallback for simplified fixtures / future markup changes.
        roots = [soup]
    out: list[Tag] = []
    seen_ids: set[int] = set()
    for root in roots:
        candidates = root.find_all("li") if root.name != "li" else [root]
        for li in candidates:
            direct = _direct_li_text(li)
            if not _REF_RE.search(direct):
                continue
            ident = id(li)
            if ident not in seen_ids:
                out.append(li)
                seen_ids.add(ident)
    return year, out


def _candidate_detail_urls(li: Tag, board_url: str) -> list[str]:
    scored: list[tuple[int, int, str]] = []
    for idx, a in enumerate(li.find_all("a", href=True)):
        label = _clean(a.get_text(" ", strip=True)).lower()
        href = _canonical(urljoin(board_url, a.get("href", "")))
        if not href or not _is_upf(href):
            continue
        if any(cue in label for cue in _BAD_DETAIL_CUES):
            continue
        score = 0
        if any(cue in label for cue in _DETAIL_CUES):
            score += 20
        low = href.lower()
        if "/documents/" in low or "/documents/d/" in low or low.endswith(".pdf"):
            score += 8
        if _REF_RE.search(label):
            score += 6
        # Direct child anchors are more likely to be the original vacancy link than nested paperwork.
        parent = a.parent
        if parent is li:
            score += 4
        if score > 0:
            scored.append((score, -idx, href))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    out: list[str] = []
    for _, _, href in scored:
        if href not in out:
            out.append(href)
    return out


def _portal_status(li: Tag) -> str:
    nested_text = " ".join(
        _clean(node.get_text(" ", strip=True)).lower()
        for node in li.find_all(["ul", "ol"], recursive=False)
    )
    if any(cue in nested_text for cue in _CLOSED_PROCESS_CUES):
        return "CLOSED"
    return ""


def parse_board_html(html: str, board_url: str = BOARD_URL) -> list[dict]:
    """Parse the newest-year official MELIS vacancies without relevance filtering."""
    soup = BeautifulSoup(html or "", "html.parser")
    year, nodes = _job_nodes_for_latest_year(soup)
    rows: list[dict] = []
    seen: set[str] = set()
    for li in nodes:
        line = _direct_li_text(li)
        ref_m = _REF_RE.search(line)
        if not ref_m:
            continue
        ref = ref_m.group(0).upper()
        if ref in seen:
            continue
        title = _clean(line[:ref_m.start()].rstrip("( [-,:"))
        if not title:
            title = ref
        pub_m = _DATE_RE.search(line[ref_m.end():])
        publication_date = _normalize_date(pub_m.group(1)) if pub_m else ""
        detail_urls = _candidate_detail_urls(li, board_url)
        url = detail_urls[0] if detail_urls else f"{board_url}#{ref}"
        portal_status = _portal_status(li)
        desc = ["Official UPF MELIS job listing."]
        if publication_date:
            desc.append(f"Publication date: {publication_date}.")
        if portal_status:
            desc.append(f"Portal status: {portal_status}.")
            if portal_status == "CLOSED":
                desc.append("Applications closed.")
        job = JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date="",  # publication date is not an application deadline
            url=url,
            id=ref,
            description=" ".join(desc),
            search_query="upf_melis_job_offers",
        ).to_dict()
        job["call_reference"] = ref
        job["publication_date"] = publication_date
        job["portal_status"] = portal_status
        job["detail_candidates"] = detail_urls
        job["listing_year"] = year
        rows.append(job)
        seen.add(ref)
    return rows


def extract_deadline(text: str) -> str:
    m = _DEADLINE_RE.search(_clean(text))
    return _normalize_date(m.group(1)) if m else ""


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 100,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_upf_melis_latest_year",
        "coverage_scope": "latest_year_section_on_official_melis_job_board",
        "board_fetch": "NOT_ATTEMPTED",
        "latest_year": None,
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
            response = session.get(BOARD_URL, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            diag["board_fetch"] = "OK"
            diag["final_url"] = response.url
            jobs = parse_board_html(response.text, response.url)
            soup = BeautifulSoup(response.text or "", "html.parser")
            latest_year, _ = _latest_year_root(soup)
            diag["latest_year"] = latest_year
        except Exception as exc:
            diag["board_fetch"] = "FAILED"
            diag["coverage_warning"] = f"UPF MELIS job board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_jobs"] = len(jobs)
        diag["unique_jobs"] = len(jobs)
        if len(jobs) > max_jobs:
            diag["truncated"] = len(jobs) - max_jobs
            jobs = jobs[:max_jobs]
            diag["coverage_warning"] = (
                f"UPF MELIS latest-year listing set truncated by max_jobs={max_jobs}; "
                f"{diag['truncated']} listing(s) not processed"
            )

        if enrich_detail:
            good = {"OK_PDF", "OK_HTML", "OK"}
            for job in jobs:
                candidates = list(job.pop("detail_candidates", []) or [])
                diag["detail_attempts"] += 1
                detail = ""
                raw_status = "UPF_MELIS_DETAIL_LINK_NOT_FOUND"
                trusted = ""
                for candidate in candidates[:3]:
                    detail, raw_status = fetch_url_text(
                        candidate,
                        timeout=(10, 45),
                        title_hint=job.get("title", ""),
                        session=session,
                        follow_job_attachments=False,
                    )
                    if detail and raw_status in good:
                        trusted = candidate
                        break
                if detail and raw_status in good:
                    public_status = "OK_PDF_ATTACHMENT" if raw_status == "OK_PDF" else "OK_ATTACHMENT"
                    job["full_detail"] = detail
                    job["detail_status"] = public_status
                    job["trusted_full_detail_url"] = trusted
                    job["trusted_full_detail_source"] = SOURCE_NAME
                    deadline = extract_deadline(detail)
                    if deadline:
                        job["date"] = deadline
                        job["description"] = _clean(job.get("description", "") + f" Application deadline: {deadline}.")
                    diag["detail_success"] += 1
                else:
                    public_status = raw_status
                    job["full_detail"] = ""
                    job["detail_status"] = public_status
                    diag["detail_failed"] += 1
                diag["detail_status_counts"][public_status] = int(diag["detail_status_counts"].get(public_status, 0)) + 1
        else:
            for job in jobs:
                job.pop("detail_candidates", None)

        diag["coverage_complete"] = bool(diag["board_fetch"] == "OK" and diag["truncated"] == 0)
        return jobs
    finally:
        try:
            session.close()
        except Exception:
            pass
