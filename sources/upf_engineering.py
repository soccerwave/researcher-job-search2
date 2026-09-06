from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "UPF Engineering PDI"
COMPANY = "Universitat Pompeu Fabra (UPF)"
DEFAULT_LOCATION = "Barcelona, Spain"
BOARD_URL = "https://www.upf.edu/en/web/enginyeria/convocatories-pdi"

_DETAIL_PATH_RE = re.compile(r"/web/enginyeria/convocatories-pdi/-/asset_publisher/", re.I)
_CALL_RE = re.compile(
    r"(?:Call|Convocat[oò]ria|Convocatoria)\s*:\s*(.+?)"
    r"(?=\s+(?:Application\s+deadline|Deadline|Termini\s+de\s+sol[·l]licituds|Data\s+l[ií]mit|Status|Estat|Estado)\s*:|$)",
    re.I,
)
_DEADLINE_RE = re.compile(
    r"(?:Application\s+deadline|Deadline|Termini\s+de\s+sol[·l]licituds|Data\s+l[ií]mit)\s*:\s*"
    r"(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[.-]\d{1,2}[.-]\d{4})",
    re.I,
)
_STATUS_RE = re.compile(r"(?:Status|Estat|Estado)\s*:\s*(OPEN|CLOSED|OBERTA|OBERT|TANCADA|TANCAT|ABIERTA|ABIERTO|CERRADA|CERRADO)", re.I)
_BAD_LINK_LABELS = {
    "bases de la convocatòria",
    "bases de la convocatoria",
    "resolució de la convocatòria",
    "resolucion de la convocatoria",
    "llista provisional d'admesos i exclosos",
    "provisional list of admitted and excluded candidates",
    "inscriu-t'hi",
    "apply",
    "apply here",
}
_BASES_CUES = (
    "bases de la convocatòria",
    "bases de la convocatoria",
    "call bases",
    "terms of the call",
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _canonical(url: str) -> str:
    return (url or "").split("#", 1)[0].strip()


def _is_upf(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "upf.edu" or host.endswith(".upf.edu")


def _nearest_offer_block(anchor):
    node = anchor
    for _ in range(8):
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if _DEADLINE_RE.search(text) and len(text) <= 2600:
            return node
        node = node.parent
    return anchor.parent or anchor


def _candidate_title(anchor) -> str:
    label = _clean(anchor.get_text(" ", strip=True))
    if not label or label.lower() in _BAD_LINK_LABELS:
        return ""
    if len(label) < 12:
        return ""
    return label


def parse_board_html(html: str, board_url: str = BOARD_URL) -> list[dict]:
    """Parse UPF School of Engineering PDI offer cards.

    No relevance filtering is done here. The frozen V1.36 scorer decides fit.
    The board metadata is used for availability; scoring requires official Bases.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = _canonical(urljoin(board_url, a.get("href", "")))
        if not _is_upf(href) or not _DETAIL_PATH_RE.search(urlparse(href).path):
            continue
        title = _candidate_title(a)
        if not title:
            continue
        key = href.rstrip("/").lower()
        if key in seen:
            continue
        block = _nearest_offer_block(a)
        block_text = _clean(block.get_text(" ", strip=True))
        deadline_m = _DEADLINE_RE.search(block_text)
        call_m = _CALL_RE.search(block_text)
        status_m = _STATUS_RE.search(block_text)
        deadline = deadline_m.group(1) if deadline_m else ""
        call_ref = _clean(call_m.group(1)) if call_m else ""
        portal_status = _clean(status_m.group(1)).upper() if status_m else ""
        desc = ["Official UPF School of Engineering PDI listing."]
        if deadline:
            desc.append(f"Application deadline: {deadline}.")
        if portal_status:
            desc.append(f"Portal status: {portal_status}.")
        rows.append(JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=deadline,
            url=href,
            id=call_ref,
            description=" ".join(desc),
            search_query="upf_engineering_pdi",
        ).to_dict())
        rows[-1]["portal_status"] = portal_status
        rows[-1]["call_reference"] = call_ref
        seen.add(key)
    return rows


def _find_bases_candidates(html: str, detail_url: str) -> list[str]:
    """Return official UPF call/base document links from one vacancy page.

    Later-stage process documents are intentionally ignored. The vacancy page itself
    is not treated as a Full JD when the official Bases are available/expected.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    scored: list[tuple[int, int, str]] = []
    for idx, a in enumerate(soup.find_all("a", href=True)):
        label = _clean(a.get_text(" ", strip=True)).lower()
        href = _canonical(urljoin(detail_url, a.get("href", "")))
        if not href or not _is_upf(href):
            continue
        score = 0
        if any(cue in label for cue in _BASES_CUES):
            score += 20
        if "bases" in label:
            score += 8
        low_href = href.lower()
        if low_href.endswith(".pdf") or "/documents/" in low_href or "download" in low_href:
            score += 2
        # Never use later process paperwork as a job description.
        if any(cue in label for cue in (
            "admes", "admit", "excluded", "exclos", "adjudic", "proposta", "proposal",
            "resultats", "results", "tribunal", "resolució d'adjudicació", "resolucion de adjudicacion",
        )):
            continue
        if score > 0:
            scored.append((score, -idx, href))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    out: list[str] = []
    for _, _, href in scored:
        if href not in out:
            out.append(href)
    return out


def parse_detail_html(html: str, detail_url: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = _clean(root.get_text(" ", strip=True))
    title_node = root.find(["h1", "h2"]) or soup.find(["h1", "h2"])
    title = _clean(title_node.get_text(" ", strip=True)) if title_node else ""
    deadline_m = _DEADLINE_RE.search(text)
    call_m = _CALL_RE.search(text)
    status_m = _STATUS_RE.search(text)
    return {
        "title": title,
        "deadline": deadline_m.group(1) if deadline_m else "",
        "call_reference": _clean(call_m.group(1)) if call_m else "",
        "portal_status": _clean(status_m.group(1)).upper() if status_m else "",
        "bases_urls": _find_bases_candidates(html, detail_url),
    }


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 40,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_upf_engineering_pdi",
        "board_fetch": "NOT_ATTEMPTED",
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_page_attempts": 0,
        "detail_page_success": 0,
        "detail_page_failed": 0,
        "bases_links_found": 0,
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
        except Exception as exc:
            diag["board_fetch"] = "FAILED"
            diag["coverage_warning"] = f"UPF Engineering PDI board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_jobs"] = len(jobs)
        diag["unique_jobs"] = len(jobs)
        if len(jobs) > max_jobs:
            diag["truncated"] = len(jobs) - max_jobs
            jobs = jobs[:max_jobs]
            diag["coverage_warning"] = (
                f"UPF Engineering PDI listing set truncated by max_jobs={max_jobs}; "
                f"{diag['truncated']} listing(s) not processed"
            )

        if enrich_detail:
            good = {"OK_PDF", "OK_HTML", "OK"}
            for job in jobs:
                diag["detail_page_attempts"] += 1
                try:
                    page = session.get(job.get("url", ""), timeout=(10, 45), allow_redirects=True)
                    page.raise_for_status()
                    diag["detail_page_success"] += 1
                    meta = parse_detail_html(page.text, page.url)
                except Exception as exc:
                    diag["detail_page_failed"] += 1
                    status = f"UPF_DETAIL_PAGE_FETCH_FAILED: {type(exc).__name__}: {exc}"
                    job["full_detail"] = ""
                    job["detail_status"] = status
                    diag["detail_failed"] += 1
                    diag["detail_status_counts"][status] = int(diag["detail_status_counts"].get(status, 0)) + 1
                    continue

                # Prefer detail-page authoritative metadata when present.
                if meta.get("deadline"):
                    job["date"] = meta["deadline"]
                    job["description"] = f"Official UPF School of Engineering PDI listing. Application deadline: {meta['deadline']}."
                if meta.get("call_reference") and not job.get("id"):
                    job["id"] = meta["call_reference"]
                if meta.get("portal_status"):
                    job["portal_status"] = meta["portal_status"]

                bases_urls = meta.get("bases_urls") or []
                if bases_urls:
                    diag["bases_links_found"] += 1
                diag["detail_attempts"] += 1
                detail = ""
                raw_status = "UPF_BASES_LINK_NOT_FOUND"
                trusted = ""
                for candidate in bases_urls[:3]:
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
                    diag["detail_success"] += 1
                else:
                    public_status = raw_status
                    job["full_detail"] = ""
                    job["detail_status"] = public_status
                    diag["detail_failed"] += 1
                diag["detail_status_counts"][public_status] = int(diag["detail_status_counts"].get(public_status, 0)) + 1

        diag["coverage_complete"] = bool(diag["board_fetch"] == "OK" and diag["truncated"] == 0)
        return jobs
    finally:
        try:
            session.close()
        except Exception:
            pass
