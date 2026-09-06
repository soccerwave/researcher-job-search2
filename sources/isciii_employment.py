from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "ISCIII Employment"
COMPANY = "Instituto de Salud Carlos III (ISCIII)"
DEFAULT_LOCATION = "Madrid, Spain"
BOARD_URL = "https://www.isciii.es/trabaja-isciii"

_DETAIL_RE = re.compile(r"/(?:en/|es/)?l/(\d+)(?:[/?#]|$)", re.I)
_DATE_RE = re.compile(r"(?:fecha\s+de\s+inicio|start\s+date)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
_DEADLINE_RE = re.compile(r"(?:fecha\s+l[ií]mite|deadline)\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
_STATE_RE = re.compile(r"(?:estado|state)\s*:?\s*(inicial|initial|en\s+tramitaci[oó]n|processing|finalizado|ended)", re.I)

_BAD_DOC_CUES = (
    "anexo iii", "anexo iii solicitud", "admitid", "excluid", "tribunal", "cronograma",
    "resoluci[oó]n provisional", "resolucion provisional", "m[eé]ritos", "meritos",
    "modelo aceptaci", "nota informativa", "subsan", "adjudicaci", "adjudicacion",
)
_GOOD_DOC_CUES = (
    "boe convocatoria", "convocatoria", "bases de convocatoria", "bases convocatoria",
    "resoluci[oó]n de bases", "resolucion de bases",
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _canonical(url: str) -> str:
    return (url or "").split("#", 1)[0].strip()


def page_url(page_no: int, page_size: int = 15) -> str:
    # ISCIII uses a Liferay search-container. The page index (`start`) is only
    # honored reliably when the collection page size (`delta`) is supplied too.
    # The live board currently renders 15 records per page.
    return BOARD_URL if int(page_no) <= 1 else f"{BOARD_URL}?delta={int(page_size)}&start={int(page_no)}"


def _is_isciii_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "isciii.es" or host.endswith(".isciii.es")


def _nearest_card(anchor):
    node = anchor
    for _ in range(7):
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if ("Start date:" in text or "Fecha de inicio:" in text or "Deadline:" in text or "Fecha límite:" in text) and len(text) < 2200:
            return node
        node = node.parent
    return anchor.parent or anchor


def _title_from_card(anchor, card_text: str) -> str:
    label = _clean(anchor.get_text(" ", strip=True))
    # On ISCIII the entire card is often one anchor. Keep only the concept preceding metadata.
    label = re.split(r"\s+(?:Start date|Fecha de inicio|Deadline|Fecha límite)\s*:", label, maxsplit=1, flags=re.I)[0]
    if not label:
        label = re.split(r"\s+(?:Start date|Fecha de inicio|Deadline|Fecha límite)\s*:", card_text, maxsplit=1, flags=re.I)[0]
    return _clean(label)


def parse_board_html(html: str, board_url: str = BOARD_URL) -> list[dict]:
    """Parse official ISCIII employment cards from one Work-at-ISCIII page.

    No relevance filtering is applied here. Downstream frozen scoring decides fit.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = _canonical(urljoin(board_url, a.get("href", "")))
        m = _DETAIL_RE.search(urlparse(href).path)
        if not m or not _is_isciii_host(href):
            continue
        key = f"{urlparse(href).hostname}:{m.group(1)}"
        if key in seen:
            continue
        card = _nearest_card(a)
        card_text = _clean(card.get_text(" ", strip=True))
        title = _title_from_card(a, card_text)
        if not title or len(title) < 3:
            continue

        start_m = _DATE_RE.search(card_text)
        deadline_m = _DEADLINE_RE.search(card_text)
        state_m = _STATE_RE.search(card_text)
        deadline = deadline_m.group(1) if deadline_m else ""
        state = _clean(state_m.group(1)) if state_m else ""
        start_date = start_m.group(1) if start_m else ""
        desc = ["Official ISCIII employment listing."]
        if start_date:
            desc.append(f"Start date: {start_date}.")
        if deadline:
            desc.append(f"Fecha límite: {deadline}.")
        if state:
            desc.append(f"Portal state: {state}.")

        out.append(JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date=deadline,
            url=href,
            id=f"isciii-{m.group(1)}",
            description=" ".join(desc),
            search_query="isciii_employment_newest_pages",
        ).to_dict())
        out[-1].update({
            "portal_record_id": m.group(1),
            "portal_state": state,
            "start_date": start_date,
        })
        seen.add(key)
    return out


def _document_candidates(html: str, detail_url: str) -> list[str]:
    """Rank official ISCIII call/base documents, excluding later process paperwork."""
    soup = BeautifulSoup(html or "", "html.parser")
    scored: list[tuple[int, int, str]] = []
    for idx, a in enumerate(soup.find_all("a", href=True)):
        href = _canonical(urljoin(detail_url, a.get("href", "")))
        if not href or not _is_isciii_host(href):
            continue
        path = urlparse(href).path.lower()
        if not ("/documents/" in path or "download" in href.lower() or path.endswith(".pdf")):
            continue
        # The visible link is often merely "Descargar". Inspect its nearby document card.
        node = a
        nearby = _clean(a.get_text(" ", strip=True))
        for _ in range(5):
            if node is None or node.parent is None:
                break
            node = node.parent
            txt = _clean(node.get_text(" ", strip=True))
            if len(txt) >= 20:
                nearby = txt
            # ISCIII document cards are commonly section/div/li containers; do not
            # climb into the whole page where unrelated later documents add noise.
            if getattr(node, "name", "") in {"section", "article", "li"} or (getattr(node, "name", "") == "div" and len(txt) >= 35):
                break
        low = nearby.lower()
        # Later-stage process documents are not job descriptions.
        if any(re.search(cue, low, re.I) for cue in _BAD_DOC_CUES):
            continue
        score = 0
        if re.search(r"\bboe\s+convocatoria\b", low, re.I):
            score += 12
        elif re.search(r"\bconvocatoria\b", low, re.I):
            score += 10
        if re.search(r"\bbases?\b", low, re.I):
            score += 7
        if re.search(r"resoluci[oó]n.+convoca", low, re.I):
            score += 5
        if ".pdf" in path or "pdf" in low:
            score += 2
        if score <= 0:
            continue
        # Earlier qualifying documents are usually the actual call; use index as tie-breaker.
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
    h2 = root.find("h2") or soup.find("h2")
    title = _clean(h2.get_text(" ", strip=True)) if h2 else ""
    title = re.sub(r"^Convocatoria\s+", "", title, flags=re.I).strip()

    state = ""
    sm = re.search(r"(?:Estado|State)\s+([^#]{1,60}?)(?=\s+(?:Listado de documentos|List of documents|$))", text, re.I)
    if sm:
        state = _clean(sm.group(1))

    # Prefer the first application-window deadline, not later appeal/subsanation deadlines.
    deadline = ""
    dm = re.search(
        r"(?:Plazo|Deadline)\s*:\s*(?:Plazo de presentaci[oó]n de solicitudes\s*)?(?:del\s+)?"
        r"(\d{1,2})\s+(?:al|a)\s+(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚÀÈÒáéíóúàèòñÑçÇ]+)\s+de\s+(\d{4})",
        text,
        re.I,
    )
    if dm:
        deadline = f"{dm.group(2)} de {dm.group(3)} de {dm.group(4)}"
    else:
        dm2 = re.search(r"(?:Plazo|Deadline)\s*:\s*[^.]{0,120}?(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
        if dm2:
            deadline = dm2.group(1)

    docs = _document_candidates(html, detail_url)
    return {"title": title, "portal_state": state, "deadline": deadline, "document_urls": docs}


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_pages: int = 1,
    max_jobs: int = 60,
) -> list[dict]:
    """Collect newest requested ISCIII employment pages and resolve official call PDFs.

    The collector intentionally does not claim full historical coverage of the portal.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_isciii_employment_newest_pages",
        "coverage_scope": "newest_page_only" if int(max_pages) == 1 else "newest_requested_pages",
        "portal_full_coverage": False,
        "pages_requested": int(max_pages),
        "pages_fetched": 0,
        "page_errors": [],
        "page_job_counts": [],
        "page_unique_id_counts": [],
        "repeated_page_detected": False,
        "repeated_page_number": None,
        "parsed_jobs": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_page_attempts": 0,
        "detail_page_success": 0,
        "detail_page_failed": 0,
        "call_documents_found": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "coverage_complete": False,
        "coverage_warning": "",
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    try:
        rows: list[dict] = []
        prior_page_signatures: set[tuple[str, ...]] = set()
        for pageno in range(1, int(max_pages) + 1):
            url = page_url(pageno)
            try:
                r = session.get(url, timeout=timeout, allow_redirects=True)
                r.raise_for_status()
                page_rows = parse_board_html(r.text, r.url)
                diag["pages_fetched"] += 1
                diag["page_job_counts"].append(len(page_rows))
                page_ids = tuple(sorted(str(x.get("id") or x.get("url") or "") for x in page_rows if x.get("id") or x.get("url")))
                diag["page_unique_id_counts"].append(len(set(page_ids)))
                # A non-empty page identical to an earlier page means pagination was
                # ignored/redirected. Stop rather than pretending requested coverage.
                if page_ids and page_ids in prior_page_signatures:
                    diag["repeated_page_detected"] = True
                    diag["repeated_page_number"] = pageno
                    break
                if page_ids:
                    prior_page_signatures.add(page_ids)
                rows.extend(page_rows)
            except Exception as exc:
                diag["page_errors"].append({"page": pageno, "error": f"{type(exc).__name__}: {exc}"})
                # If page 1 fails, later pages are not trustworthy or useful to attempt.
                if pageno == 1:
                    break

        diag["parsed_jobs"] = len(rows)
        unique: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            key = str(row.get("id") or row.get("url") or "")
            if key and key not in seen:
                seen.add(key)
                unique.append(row)
        diag["unique_jobs"] = len(unique)
        if len(unique) > int(max_jobs):
            diag["truncated"] = len(unique) - int(max_jobs)
            unique = unique[: int(max_jobs)]

        if enrich_detail:
            good = {"OK_PDF", "OK_HTML", "OK", "OK_ATTACHMENT", "OK_PDF_ATTACHMENT"}
            for job in unique:
                diag["detail_page_attempts"] += 1
                meta = {}
                try:
                    r = session.get(job.get("url", ""), timeout=timeout, allow_redirects=True)
                    r.raise_for_status()
                    meta = parse_detail_html(r.text, r.url)
                    diag["detail_page_success"] += 1
                    if meta.get("title"):
                        job["title"] = meta["title"]
                    if meta.get("portal_state"):
                        job["portal_state"] = meta["portal_state"]
                    if meta.get("deadline"):
                        job["date"] = meta["deadline"]
                        job["description"] = f"Official ISCIII employment listing. Fecha límite: {meta['deadline']}. Portal state: {meta.get('portal_state','')}."
                except Exception as exc:
                    diag["detail_page_failed"] += 1
                    job["detail_page_error"] = f"{type(exc).__name__}: {exc}"

                doc_urls = meta.get("document_urls") or []
                if doc_urls:
                    diag["call_documents_found"] += 1
                if not doc_urls:
                    job["full_detail"] = ""
                    job["detail_status"] = "ATTACHMENT_UNRESOLVED"
                    diag["detail_attempts"] += 1
                    diag["detail_failed"] += 1
                    diag["detail_status_counts"]["ATTACHMENT_UNRESOLVED"] = int(diag["detail_status_counts"].get("ATTACHMENT_UNRESOLVED", 0)) + 1
                    continue

                diag["detail_attempts"] += 1
                detail = ""
                status = "ATTACHMENT_UNRESOLVED"
                trusted_url = ""
                for candidate in doc_urls[:3]:
                    detail, status = fetch_url_text(
                        candidate,
                        timeout=(10, 45),
                        title_hint=job.get("title", ""),
                        session=session,
                        follow_job_attachments=False,
                    )
                    if detail and status in good:
                        trusted_url = candidate
                        break
                public_status = "OK_PDF_ATTACHMENT" if status == "OK_PDF" else ("OK_ATTACHMENT" if status in {"OK_HTML", "OK"} else status)
                job["full_detail"] = detail
                job["detail_status"] = public_status
                if trusted_url:
                    job["trusted_full_detail_url"] = trusted_url
                    job["trusted_full_detail_source"] = SOURCE_NAME
                diag["detail_status_counts"][public_status] = int(diag["detail_status_counts"].get(public_status, 0)) + 1
                if detail and status in good:
                    diag["detail_success"] += 1
                else:
                    diag["detail_failed"] += 1

        coverage_ok = (
            diag["pages_fetched"] == int(max_pages)
            and not diag["page_errors"]
            and not diag["repeated_page_detected"]
            and diag["truncated"] == 0
        )
        diag["coverage_complete"] = bool(coverage_ok)
        if diag["page_errors"]:
            diag["coverage_warning"] = f"ISCIII employment page coverage incomplete: {len(diag['page_errors'])} requested page(s) failed"
        elif diag["repeated_page_detected"]:
            diag["coverage_warning"] = f"ISCIII pagination did not advance at requested page {diag['repeated_page_number']}; repeated listing page detected"
        elif diag["truncated"]:
            diag["coverage_warning"] = f"ISCIII newest-page set truncated by max_jobs={max_jobs}: {diag['truncated']} listing(s) omitted"
        elif diag["pages_fetched"] == int(max_pages) and diag["page_job_counts"] and diag["page_job_counts"][0] == 0:
            diag["coverage_complete"] = False
            diag["coverage_warning"] = "ISCIII first requested page parsed zero employment records; page structure may have changed"
        return unique
    finally:
        try:
            session.close()
        except Exception:
            pass
