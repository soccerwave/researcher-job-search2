from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

SOURCE_NAME = "Fundación Progreso y Salud"
COMPANY = "Fundación Pública Andaluza Progreso y Salud, M.P."
DEFAULT_LOCATION = "Andalucía, Spain"

# Official Junta de Andalucía transparency board, scoped to FPS and filtered to
# calls whose application period is listed as current by the portal.  A generous
# page size keeps the current set on one request without title/domain prefiltering.
BOARD_URL = (
    "https://www.juntadeandalucia.es/organismos/fps/estructura/transparencia/"
    "empleo-publico/ofertas-empleo.html?combine=&field_lugar_localidad_value="
    "&field_lugar_provincia_target_id=All&field_ofem_estado_proceso_value_1=All"
    "&field_ofem_fecha_fin_value%5B1%5D=1&field_ofem_tipo_contrato_value=All"
    "&field_ofem_tipo_convocatoria_value=All&field_ofem_titulacion_esp_value="
    "&field_ofem_titulacion_oficial_value=All&items_per_page=50"
    "&sort_by=field_ofem_fecha_ini_value"
)

DETAIL_RE = re.compile(r"/ofertas-empleo/detalle/(\d+)\.html(?:[/?#]|$)", re.I)
TOTAL_RE = re.compile(r"\b([\d.]+)\s+recursos?\s+disponibles?\b", re.I)
CODE_RE = re.compile(r"(?:^|\s)[-–—]?\s*((?:\d{1,2}-)?\d{4}|\d{4})\s*$")
WINDOW_RE = re.compile(
    r"plazo\s+de\s+solicitud\s+(\d{1,2}/\d{1,2}/\d{4})\s*[-–—]\s*(\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)
LOCATION_RE = re.compile(
    r"lugar\s+de\s+trabajo\s+(.{2,120}?)(?=\s+(?:tipo\s+de\s+contrato|titulaci[oó]n\s+oficial|otros\s+requisitos|funciones)\b|$)",
    re.I | re.S,
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical(url: str) -> str:
    return str(url or "").split("#", 1)[0].rstrip("/")


def _code_from_title(title: str) -> str:
    # FPS titles commonly end in 2451, 2467, 08-2026, etc.  This is metadata only;
    # the Junta detail numeric id remains the stable record identity.
    t = _clean(title)
    m = re.search(r"\b(\d{2}-\d{4}|\d{4})\b\s*$", t)
    return m.group(1) if m else ""


def _portal_state_from_row(row) -> str:
    if row is None:
        return ""
    text = _clean(row.get_text(" ", strip=True))
    for state in (
        "En curso", "Concluido", "Cerrado", "Cerrada", "Abierto", "Abierta",
        "Pendiente", "Cancelado", "Cancelada",
    ):
        if re.search(rf"\b{re.escape(state)}\b", text, re.I):
            return state
    return ""


def parse_board_html(html: str, board_url: str = BOARD_URL) -> tuple[list[dict], int | None]:
    """Parse the official FPS-scoped Junta employment result page.

    There is deliberately no relevance/title filter here.  Every current portal row is
    carried to full-detail resolution so the frozen scorer sees the complete holdout.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    text = _clean(soup.get_text(" ", strip=True))
    total_match = TOTAL_RE.search(text)
    total = int(total_match.group(1).replace(".", "")) if total_match else None

    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(board_url, a.get("href", ""))
        match = DETAIL_RE.search(urlparse(href).path)
        if not match:
            continue
        url = _canonical(href)
        if url in seen:
            continue
        title = _clean(a.get_text(" ", strip=True))
        if not title:
            continue
        seen.add(url)
        row = a.find_parent("tr")
        state = _portal_state_from_row(row)
        desc = f"Portal state: {state}" if state else ""
        out.append(JobRecord(
            source=SOURCE_NAME,
            title=title,
            company=COMPANY,
            location=DEFAULT_LOCATION,
            date="",
            url=url,
            id=f"junta-{match.group(1)}",
            description=desc,
            search_query="junta_fps_current_application_window",
        ).to_dict())
        out[-1]["portal_detail_id"] = match.group(1)
        out[-1]["job_code"] = _code_from_title(title)
        out[-1]["portal_state"] = state
        out[-1]["source_listing_active"] = True
    return out, total


def _enrich_metadata_from_detail(job: dict) -> None:
    text = _clean(job.get("full_detail", ""))
    if not text:
        return
    m = WINDOW_RE.search(text)
    if m:
        job["application_window_start"] = m.group(1)
        job["application_window_end"] = m.group(2)
        existing = _clean(job.get("description", ""))
        deadline_note = f"Application deadline: {m.group(2)}"
        job["description"] = ". ".join(x for x in (existing, deadline_note) if x)
    loc = LOCATION_RE.search(text)
    if loc:
        location = _clean(loc.group(1))
        if location:
            job["location"] = f"{location}, Spain" if "spain" not in location.lower() else location


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 50,
) -> list[dict]:
    """Collect FPS calls from the official Junta de Andalucía employment portal.

    The board query is source-scoped and asks the portal for calls in the application
    window.  Explicit deadlines from each detail page still determine availability;
    the portal's own "En curso" label is not treated as proof that applications remain
    open.  No scoring or relevance logic lives in this collector.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "feed_mode": "official_junta_fps_current_application_window",
        "board_fetched": False,
        "total_reported": None,
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
            r = session.get(BOARD_URL, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
            diag["board_fetched"] = True
            jobs, total = parse_board_html(r.text, r.url)
            diag["total_reported"] = total
        except Exception as exc:
            diag["coverage_warning"] = f"FPS/Junta board fetch/parse failed: {type(exc).__name__}: {exc}"
            return []

        diag["parsed_jobs"] = len(jobs)
        unique: list[dict] = []
        seen: set[str] = set()
        for job in jobs:
            key = _canonical(job.get("url", ""))
            if key and key not in seen:
                seen.add(key)
                unique.append(job)
        diag["unique_jobs"] = len(unique)

        reported = diag.get("total_reported")
        if isinstance(reported, int) and reported != len(unique):
            diag["coverage_warning"] = (
                f"FPS/Junta current board reported {reported} resource(s) but parser found {len(unique)} unique detail rows"
            )

        if len(unique) > max_jobs:
            diag["truncated"] = len(unique) - max_jobs
            unique = unique[:max_jobs]
            diag["coverage_warning"] = (
                f"FPS/Junta current listing set truncated by max_jobs={max_jobs}; "
                f"{diag['truncated']} listing(s) not processed"
            )

        if enrich_detail:
            ok_statuses = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK"}
            for job in unique:
                diag["detail_attempts"] += 1
                detail, status = fetch_url_text(
                    job.get("url", ""),
                    timeout=(10, 45),
                    title_hint=job.get("title", ""),
                    session=session,
                    follow_job_attachments=True,
                )
                job["full_detail"] = detail
                job["detail_status"] = status
                counts = diag["detail_status_counts"]
                counts[status] = int(counts.get(status, 0)) + 1
                if detail and status in ok_statuses:
                    diag["detail_success"] += 1
                    _enrich_metadata_from_detail(job)
                else:
                    diag["detail_failed"] += 1

        count_ok = not isinstance(reported, int) or reported == diag["unique_jobs"]
        diag["coverage_complete"] = bool(
            diag["board_fetched"] and diag["truncated"] == 0 and count_ok
        )
        return unique
    finally:
        try:
            session.close()
        except Exception:
            pass
