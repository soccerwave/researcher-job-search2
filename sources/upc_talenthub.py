from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "UPC Talent Hub"
COMPANY = "Universitat Politècnica de Catalunya (UPC)"
DEFAULT_LOCATION = "Catalonia, Spain"

# Production scope deliberately excludes R0/R1 because those are predominantly
# initiation/predoctoral opportunities and are low-value for this target profile.
# We collect open research-support and postdoctoral/researcher tracks only.
BOARD_URLS = {
    "PSR": "https://talenthub.upc.edu/en/jobs/psr/psr-open-folder/research-support-staff",
    "R2": "https://talenthub.upc.edu/en/jobs/r2/r2-jobs/r2-jobs",
    "R3": "https://talenthub.upc.edu/en/jobs/r3/r3-jobs/r3-jobs",
    "R4": "https://talenthub.upc.edu/en/jobs/r4/r4-jobs",
}

_DEADLINE_RE = re.compile(
    r"\bDeadline\s*:\s*"
    r"([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{1,2}-\d{1,2})",
    re.I,
)
_CODE_RE = re.compile(r"\bCodi\s*:?[ ]*([A-Za-z0-9][A-Za-z0-9 _./-]{2,40})", re.I)
_RESOLUTION_RE = re.compile(r"\bRESOLUCI[ÓO]\s+([^\n]{5,180}?)(?=\s+(?:T[eè]cnic|Investigador|Postdoc|Deadline|$))", re.I)
_DETAIL_PATH_RE = re.compile(r"/en/jobs/(?:psr|r2|r3|r4)/", re.I)
_PROFILE_CUES = (
    "perfil professional",
    "professional profile",
    "job profile",
    "perfil profesional",
)
_NEGATIVE_DOC_CUES = (
    "bases del concurs",
    "formulari",
    "inscripci",
    "admes",
    "exclos",
    "criteris de valoraci",
    "resultat",
    "tribunal",
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _canonical(url: str) -> str:
    return (url or "").split("#", 1)[0].strip()


def _is_upc_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "upc.edu" or host.endswith(".upc.edu")


def _section_state(anchor) -> str:
    """Best-effort Open/Closed section classification from the listing DOM."""
    for node in anchor.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6"], limit=12):
        txt = _clean(node.get_text(" ", strip=True)).lower()
        if txt in {"open jobs", "open job", "ofertes obertes", "jobs obertes"} or txt.startswith("open jobs"):
            return "OPEN"
        if txt in {"closed jobs", "closed job", "ofertes tancades", "jobs tancades"} or txt.startswith("closed jobs"):
            return "CLOSED"
    return ""


def _nearest_job_block(anchor):
    node = anchor
    for _ in range(8):
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if _DEADLINE_RE.search(text) and len(text) <= 3200:
            return node
        node = node.parent
    return anchor.parent or anchor


def _candidate_title(anchor) -> str:
    label = _clean(anchor.get_text(" ", strip=True))
    if not label or len(label) < 8:
        return ""
    if not re.search(r"\bCodi\b", label, re.I):
        return ""
    return label


def parse_board_html(html: str, board_url: str, track: str) -> list[dict]:
    """Parse current open UPC Talent Hub vacancy cards from one official track page."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = _canonical(urljoin(board_url, a.get("href", "")))
        if not _is_upc_host(href) or not _DETAIL_PATH_RE.search(urlparse(href).path):
            continue
        title = _candidate_title(a)
        if not title:
            continue
        state = _section_state(a)
        # Dedicated PSR open page may omit a nearby heading on some renders; for the
        # other tracks only retain links demonstrably under the Open jobs section.
        if track != "PSR" and state != "OPEN":
            continue
        if track == "PSR" and state == "CLOSED":
            continue

        key = href.rstrip("/").lower()
        if key in seen:
            continue
        block = _nearest_job_block(a)
        block_text = _clean(block.get_text(" ", strip=True))
        dm = _DEADLINE_RE.search(block_text)
        deadline = _clean(dm.group(1)) if dm else ""
        cm = _CODE_RE.search(title)
        code = _clean(cm.group(1)) if cm else ""
        # Strip trailing punctuation accidentally captured in the code.
        code = re.sub(r"[.;,:]+$", "", code).strip()
        rm = _RESOLUTION_RE.search(block_text)
        resolution = _clean(rm.group(1)) if rm else ""

        desc = [f"Official UPC Talent Hub {track} open-job listing."]
        if deadline:
            desc.append(f"Deadline: {deadline}.")
        if resolution:
            desc.append(f"Resolution: {resolution}.")
        row = JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=deadline,
            url=href,
            id=code,
            description=" ".join(desc),
            search_query=f"upc_talenthub_{track.lower()}_open",
        ).to_dict()
        row["upc_track"] = track
        row["portal_status"] = "OPEN"
        row["resolution_reference"] = resolution
        rows.append(row)
        seen.add(key)
    return rows


def _find_profile_candidates(html: str, detail_url: str) -> list[str]:
    """Return official UPC professional-profile documents for the vacancy.

    The Talent Hub detail page separates generic contest bases from the actual
    professional profile. Scoring should use the profile because it contains the
    vacancy-specific duties, qualifications and required experience.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    scored: list[tuple[int, int, str]] = []
    for idx, a in enumerate(soup.find_all("a", href=True)):
        label = _clean(a.get_text(" ", strip=True)).lower()
        href = _canonical(urljoin(detail_url, a.get("href", "")))
        if not href or not _is_upc_host(href):
            continue
        if any(cue in label for cue in _NEGATIVE_DOC_CUES):
            continue
        score = 0
        if any(cue in label for cue in _PROFILE_CUES):
            score += 20
        low_href = href.lower()
        if "fitxa" in low_href or "perfil" in low_href or "profile" in low_href:
            score += 7
        if low_href.endswith(".pdf") or ".pdf?" in low_href:
            score += 3
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
    h1 = root.find("h1") or soup.find("h1")
    title = _clean(h1.get_text(" ", strip=True)) if h1 else ""

    # Talent Hub event pages expose a start/end window; the last date is the deadline.
    deadline = ""
    dm = _DEADLINE_RE.search(text)
    if dm:
        deadline = _clean(dm.group(1))
    if not deadline:
        iso_dates = re.findall(r"(20\d{2}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}", text)
        if len(iso_dates) >= 2:
            deadline = iso_dates[-1]

    location = ""
    wm = re.search(r"\bWhere\s+([^#]{2,100}?)(?=\s+(?:Contact Name|Add event|Bases del concurs|Perfil Professional|$))", text, re.I)
    if wm:
        location = _clean(wm.group(1))

    code = ""
    cm = _CODE_RE.search(title or text)
    if cm:
        code = re.sub(r"[.;,:]+$", "", _clean(cm.group(1))).strip()

    return {
        "title": title,
        "deadline": deadline,
        "location": location,
        "code": code,
        "profile_urls": _find_profile_candidates(html, detail_url),
    }


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 80,
) -> list[dict]:
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_urls": dict(BOARD_URLS),
        "feed_mode": "official_upc_talenthub_open_psr_r2_r3_r4",
        "boards_requested": len(BOARD_URLS),
        "boards_fetched": 0,
        "board_errors": [],
        "board_job_counts": {},
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_page_attempts": 0,
        "detail_page_success": 0,
        "detail_page_failed": 0,
        "profile_links_found": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "coverage_complete": False,
        "coverage_warning": "",
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    try:
        jobs: list[dict] = []
        seen: set[str] = set()
        for track, board_url in BOARD_URLS.items():
            try:
                response = session.get(board_url, timeout=timeout, allow_redirects=True)
                response.raise_for_status()
                diag["boards_fetched"] += 1
                parsed = parse_board_html(response.text, response.url, track)
                diag["board_job_counts"][track] = len(parsed)
                for job in parsed:
                    key = str(job.get("url") or "").rstrip("/").lower()
                    if key and key not in seen:
                        seen.add(key)
                        jobs.append(job)
            except Exception as exc:
                diag["board_errors"].append({"track": track, "url": board_url, "error": f"{type(exc).__name__}: {exc}"})
                diag["board_job_counts"][track] = 0

        diag["parsed_jobs"] = len(jobs)
        diag["unique_jobs"] = len(jobs)
        if len(jobs) > max_jobs:
            diag["truncated"] = len(jobs) - max_jobs
            jobs = jobs[:max_jobs]

        if enrich_detail:
            good = {"OK_PDF", "OK_HTML", "OK", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT"}
            for job in jobs:
                diag["detail_page_attempts"] += 1
                try:
                    page = session.get(job.get("url", ""), timeout=(10, 45), allow_redirects=True)
                    page.raise_for_status()
                    diag["detail_page_success"] += 1
                    meta = parse_detail_html(page.text, page.url)
                except Exception as exc:
                    diag["detail_page_failed"] += 1
                    status = f"UPC_DETAIL_PAGE_FETCH_FAILED: {type(exc).__name__}: {exc}"
                    job["full_detail"] = ""
                    job["detail_status"] = status
                    diag["detail_failed"] += 1
                    diag["detail_status_counts"][status] = int(diag["detail_status_counts"].get(status, 0)) + 1
                    continue

                if meta.get("deadline"):
                    job["date"] = meta["deadline"]
                    job["description"] = f"Official UPC Talent Hub {job.get('upc_track', '')} open-job listing. Deadline: {meta['deadline']}."
                if meta.get("location"):
                    loc = meta["location"]
                    if "spain" not in loc.lower():
                        loc = f"{loc}, Spain"
                    job["location"] = loc
                if meta.get("code") and not job.get("id"):
                    job["id"] = meta["code"]

                profile_urls = meta.get("profile_urls") or []
                if profile_urls:
                    diag["profile_links_found"] += 1
                diag["detail_attempts"] += 1
                detail = ""
                raw_status = "UPC_PROFILE_LINK_NOT_FOUND"
                trusted = ""
                for candidate in profile_urls[:3]:
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
                    public_status = "OK_PDF_ATTACHMENT" if raw_status in {"OK_PDF", "OK_PDF_ATTACHMENT"} else "OK_ATTACHMENT"
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

        complete = (
            diag["boards_fetched"] == diag["boards_requested"]
            and not diag["board_errors"]
            and diag["truncated"] == 0
        )
        diag["coverage_complete"] = bool(complete)
        if diag["board_errors"]:
            diag["coverage_warning"] = f"UPC Talent Hub board coverage incomplete: {len(diag['board_errors'])} track(s) failed"
        elif diag["truncated"]:
            diag["coverage_warning"] = f"UPC Talent Hub listing set truncated by max_jobs={max_jobs}; {diag['truncated']} listing(s) not processed"
        return jobs
    finally:
        try:
            session.close()
        except Exception:
            pass
