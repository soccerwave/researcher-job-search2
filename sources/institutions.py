from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

# Direct career boards chosen because they are high-value health/research employers and
# expose public Teamtailor job pages. This collector is deliberately source-only: it
# applies no fit filter and sends every discovered vacancy to the frozen evaluator.
BOARDS = [
    {"name": "ISGlobal", "url": "https://jobs.isglobal.org/jobs", "default_location": "Barcelona, Spain"},
    {"name": "VHIR", "url": "https://jobs.vhir.org/jobs", "default_location": "Barcelona, Spain"},
    {"name": "IRB Barcelona", "url": "https://recruitment.irbbarcelona.org/jobs", "default_location": "Barcelona, Spain"},
    {"name": "Fundació Sant Joan de Déu", "url": "https://careers.fsjd.org/jobs", "default_location": "Barcelona, Spain"},
]

JOB_PATH_RE = re.compile(r"/jobs/\d+(?:[-/?#]|$)", re.I)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/")


def _best_title(a, block) -> str:
    # Teamtailor cards normally expose the job name in a heading. Prefer that over the
    # whole anchor text, which can also contain department/location labels.
    for root in (a, block):
        if root is None:
            continue
        h = root.find(["h1", "h2", "h3", "h4", "h5"])
        if h:
            t = _clean(h.get_text(" ", strip=True))
            if t:
                return t
    return _clean(a.get_text(" ", strip=True))




def _trim_teamtailor_boilerplate(text: str, company: str) -> str:
    """Remove repeated employer/about-page chrome from a fetched Teamtailor vacancy.

    The public Teamtailor pages append institutional mission text and related-job
    navigation after the actual vacancy. Those sections can contain generic topic words
    (e.g. ageing or mental health) that must not be treated as the scientific domain of
    every vacancy at that institution. The markers below are stable board-level section
    headings, not job-specific keywords.
    """
    value = str(text or "")
    markers = {
        "Fundació Sant Joan de Déu": ["Sobre Fundació Sant Joan de Déu"],
        "IRB Barcelona": ["ABOUT IRB BARCELONA", "About IRB Barcelona"],
        "ISGlobal": ["About Barcelona Institute for Global Health (ISGlobal)"],
    }.get(company, [])
    cut = len(value)
    for marker in markers:
        idx = value.find(marker)
        if idx > 0:
            cut = min(cut, idx)
    return value[:cut].strip()

def parse_teamtailor_jobs(html: str, board_url: str, company: str) -> list[dict]:
    """Parse public Teamtailor job links from a career-board page.

    We identify actual vacancy URLs by Teamtailor's numeric ``/jobs/<id>-slug`` path,
    not by CSS classes. This makes the parser less dependent on theme changes.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(board_url, a.get("href", ""))
        path = urlparse(href).path
        if not JOB_PATH_RE.search(path):
            continue
        url = _canonical(href)
        if url in seen:
            continue
        seen.add(url)

        block = a
        for _ in range(4):
            if block.parent is None:
                break
            candidate = block.parent
            text = _clean(candidate.get_text(" ", strip=True))
            block = candidate
            if len(text) >= 60:
                break
        title = _best_title(a, block)
        if not title:
            # Last-resort readable title from the slug.
            slug = path.rstrip("/").split("/")[-1]
            slug = re.sub(r"^\d+-", "", slug)
            title = _clean(slug.replace("-", " "))
        card_text = _clean(block.get_text(" ", strip=True)) if block else ""

        # Teamtailor sometimes exposes location/department as small labels. These are
        # optional metadata; full-detail evaluation never depends on them.
        location = ""
        for sel in ("[class*='location']", "[data-testid*='location']", "[class*='job-location']"):
            tag = block.select_one(sel) if block else None
            if tag:
                location = _clean(tag.get_text(" ", strip=True))
                if location:
                    break

        jid_match = re.search(r"/jobs/(\d+)", path)
        row = JobRecord(
            source="Institutions",
            title=title,
            company=company,
            location=location,
            url=url,
            id=jid_match.group(1) if jid_match else "",
            description=card_text[:1800],
            search_query="teamtailor_direct",
        ).to_dict()
        # A vacancy discovered on the current Teamtailor /jobs board is source-
        # authoritative evidence that applications are still open. The frozen generic
        # availability parser retains precedence when the Full JD contains an explicit
        # deadline or closed marker, so this only removes false UNKNOWN statuses.
        row["source_application_status"] = "OPEN"
        row["source_status_evidence"] = "Listed on current Teamtailor jobs board"
        out.append(row)
    return out


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_pages: int = 4,
    max_jobs_per_board: int = 100,
) -> list[dict]:
    """Collect direct vacancies from selected public institutional Teamtailor boards.

    Fail-soft behavior is per board: one unavailable institution does not suppress the
    others, but diagnostics mark board coverage incomplete. No role/domain prefilter is
    applied so this remains an independent generalization/coverage source.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": "Institutions",
        "feed_mode": "teamtailor_direct",
        "boards_requested": len(BOARDS),
        "boards_fetched": 0,
        "board_errors": [],
        "parsed_jobs": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "truncated": 0,
        "boards": {},
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    all_jobs: list[dict] = []
    try:
        for board in BOARDS:
            name, board_url = board["name"], board["url"]
            default_location = board.get("default_location", "")
            bdiag = {"url": board_url, "pages_fetched": 0, "parsed_jobs": 0, "truncated": 0, "error": ""}
            board_jobs: list[dict] = []
            seen_urls: set[str] = set()
            try:
                for page in range(1, max_pages + 1):
                    params = {} if page == 1 else {"page": page}
                    r = session.get(board_url, params=params, timeout=timeout, allow_redirects=True)
                    r.raise_for_status()
                    bdiag["pages_fetched"] += 1
                    parsed = parse_teamtailor_jobs(r.text, r.url, name)
                    if default_location:
                        for item in parsed:
                            if not _clean(item.get("location")):
                                item["location"] = default_location
                    new = [j for j in parsed if j.get("url") not in seen_urls]
                    for j in new:
                        seen_urls.add(j.get("url", ""))
                    board_jobs.extend(new)
                    # If the next page yields no new job links, the listing is exhausted.
                    if page > 1 and not new:
                        break
                    # Most Teamtailor boards expose all jobs on the first page. Avoid
                    # speculative pagination unless the HTML explicitly points to page 2.
                    if page == 1:
                        soup = BeautifulSoup(r.text or "", "html.parser")
                        has_next = any(
                            re.search(r"(?:[?&]page=2(?:&|$))", str(a.get("href") or ""))
                            for a in soup.find_all("a", href=True)
                        )
                        if not has_next:
                            break
                diag["boards_fetched"] += 1
            except Exception as exc:
                bdiag["error"] = f"{type(exc).__name__}: {exc}"
                diag["board_errors"].append({"board": name, "error": bdiag["error"]})

            # Stable de-duplication and safety limit per institution.
            unique = []
            seen = set()
            for j in board_jobs:
                u = j.get("url", "")
                if u and u not in seen:
                    seen.add(u); unique.append(j)
            if len(unique) > max_jobs_per_board:
                bdiag["truncated"] = len(unique) - max_jobs_per_board
                diag["truncated"] += bdiag["truncated"]
                unique = unique[:max_jobs_per_board]
            bdiag["parsed_jobs"] = len(unique)
            diag["boards"][name] = bdiag
            all_jobs.extend(unique)

        # Cross-board duplicate URLs should be rare but are cheap to remove before detail.
        unique_all = []
        seen = set()
        for j in all_jobs:
            u = _canonical(str(j.get("url") or ""))
            if u and u not in seen:
                seen.add(u); unique_all.append(j)
        all_jobs = unique_all
        diag["parsed_jobs"] = len(all_jobs)

        if enrich_detail:
            for job in all_jobs:
                diag["detail_attempts"] += 1
                detail, status = fetch_url_text(
                    job.get("url", ""), timeout=(10, 45), title_hint=job.get("title", ""), session=session
                )
                if detail:
                    detail = _trim_teamtailor_boilerplate(detail, str(job.get("company") or ""))
                job["full_detail"] = detail
                job["detail_status"] = status
                if detail and status in {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}:
                    diag["detail_success"] += 1
                else:
                    diag["detail_failed"] += 1
        return all_jobs
    finally:
        try:
            session.close()
        except Exception:
            pass
