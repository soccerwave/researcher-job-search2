from __future__ import annotations

import re
from datetime import date, datetime
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

OPEN_DATA_SEARCH_URL = "https://datos.juntadeandalucia.es/api/v0/job-offering-public-sector/search"
FPS_ORGANISM_SLUG = "saludyfamilias_adscritos_fps2"
DETAIL_URL_TEMPLATE = (
    "https://www.juntadeandalucia.es/organismos/fps/estructura/transparencia/"
    "empleo-publico/ofertas-empleo/detalle/{id}.html"
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


def _html_text(value: Any) -> str:
    if value is None:
        return ""
    return _clean(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))


def _parse_api_date(value: Any) -> date | None:
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _api_location(row: dict) -> str:
    parts: list[str] = []
    provinces: list[str] = []
    for loc in row.get("job_location") or []:
        locality = _clean((loc or {}).get("locality"))
        if locality and locality not in parts:
            parts.append(locality)
        for p in (loc or {}).get("field_lugar_provincia") or []:
            province = _clean((p or {}).get("provinces"))
            if province and province not in provinces:
                provinces.append(province)
    label = ", ".join(parts or provinces)
    if provinces and parts:
        extra = [p for p in provinces if p not in label]
        if extra:
            label = f"{label} ({', '.join(extra)})"
    return f"{label}, Spain" if label else DEFAULT_LOCATION


def _api_full_detail(row: dict) -> str:
    fields = [
        ("Oferta de empleo", row.get("job_name")),
        ("Tipo de convocatoria", row.get("announcement_type")),
        ("Estado del proceso", row.get("announcement_status")),
        ("Código", row.get("job_code")),
        ("Fecha de publicación", row.get("publish_date")),
        ("Plazo de solicitud", row.get("deadline_application")),
        ("Número de plazas", row.get("job_number_places")),
        ("Lugar de trabajo", _api_location(row).removesuffix(", Spain")),
        ("Tipo de contrato", row.get("job_agreement")),
        ("Titulación oficial requerida", row.get("job_official_degree_requirements")),
        ("Titulación específica requerida", _html_text(row.get("job_specific_degree_requirements"))),
        ("Otros requisitos", _html_text(row.get("job_other_requirements"))),
        ("Funciones", _html_text(row.get("functions"))),
    ]
    return _clean(" ".join(f"{label}: {_clean(value)}" for label, value in fields if _clean(value)))


def _api_row_to_job(row: dict) -> dict:
    record_id = _clean(row.get("id"))
    title = _clean(row.get("job_name"))
    deadline = _clean(row.get("deadline_application"))
    url = DETAIL_URL_TEMPLATE.format(id=record_id)
    job = JobRecord(
        source=SOURCE_NAME,
        title=title,
        company=COMPANY,
        location=_api_location(row),
        date=_clean(row.get("publish_date")),
        url=url,
        id=f"junta-{record_id}",
        description=f"Portal state: {_clean(row.get('announcement_status'))}. Application deadline: {deadline}",
        search_query="junta_open_data_fps_current_deadline",
    ).to_dict()
    job["portal_detail_id"] = record_id
    job["job_code"] = _clean(row.get("job_code")) or _code_from_title(title)
    job["portal_state"] = _clean(row.get("announcement_status"))
    job["source_listing_active"] = True
    job["application_window_end"] = deadline
    job["full_detail"] = _api_full_detail(row)
    job["detail_status"] = "OK_API"
    return job


def collect(
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    diagnostics: dict | None = None,
    max_jobs: int = 50,
) -> list[dict]:
    """Collect current FPS calls from the official Junta Open Data API.

    The legacy HTML board remains documented above for provenance/canonical links,
    but production discovery and Full JD content come from the official open-data API.
    The API En curso state contains stale historical rows, so current availability is
    determined from deadline_application.
    """
    del enrich_detail
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "board_url": BOARD_URL,
        "api_url": OPEN_DATA_SEARCH_URL,
        "feed_mode": "official_junta_open_data_api_deadline_filtered",
        "board_fetched": False,
        "api_fetched": False,
        "api_hits": 0,
        "api_total_hits": 0,
        "api_stale_filtered": 0,
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

    timeout_tuple = timeout if isinstance(timeout, tuple) else (10, int(timeout))
    params = {
        "announcement_status": "En curso",
        "job_official_degree_requirements": "-",
        "announcement_type": "-",
        "provinces": "-",
        "job_agreement": "-",
        "order_by": "id",
        "mode": "DESC",
        "format": "json",
        "size": 500,
        "organism": FPS_ORGANISM_SLUG,
    }

    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    try:
        try:
            r = session.get(
                OPEN_DATA_SEARCH_URL,
                params=params,
                timeout=timeout_tuple,
                allow_redirects=True,
            )
            r.raise_for_status()
            payload = r.json()
            rows = payload.get("results") or []
            if not isinstance(rows, list):
                raise ValueError("Junta Open Data API returned no results list")
            diag["api_fetched"] = True
            diag["board_fetched"] = True
            diag["api_hits"] = int(payload.get("hits", len(rows)) or 0)
            diag["api_total_hits"] = int(payload.get("total_hits", len(rows)) or 0)
        except Exception as exc:
            diag["coverage_warning"] = (
                f"FPS/Junta Open Data API fetch/parse failed: {type(exc).__name__}: {exc}"
            )
            return []

        today = date.today()
        current_rows: list[dict] = []
        stale = 0
        for row in rows:
            deadline = _parse_api_date((row or {}).get("deadline_application"))
            if deadline is not None and deadline < today:
                stale += 1
                continue
            current_rows.append(row)
        diag["api_stale_filtered"] = stale
        diag["parsed_jobs"] = len(current_rows)

        unique: list[dict] = []
        seen: set[str] = set()
        for row in current_rows:
            record_id = _clean((row or {}).get("id"))
            if not record_id or record_id in seen:
                continue
            seen.add(record_id)
            unique.append(_api_row_to_job(row))
        diag["unique_jobs"] = len(unique)

        if len(unique) > max_jobs:
            diag["truncated"] = len(unique) - max_jobs
            unique = unique[:max_jobs]
            diag["coverage_warning"] = (
                f"FPS/Junta current API set truncated by max_jobs={max_jobs}; "
                f"{diag['truncated']} listing(s) not processed"
            )

        diag["detail_attempts"] = len(unique)
        diag["detail_success"] = sum(1 for j in unique if j.get("full_detail"))
        diag["detail_failed"] = len(unique) - diag["detail_success"]
        diag["detail_status_counts"] = {"OK_API": diag["detail_success"]} if unique else {}

        api_complete = diag["api_hits"] == len(rows) == diag["api_total_hits"]
        if not api_complete and not diag["coverage_warning"]:
            diag["coverage_warning"] = (
                f"FPS/Junta API response incomplete: hits={diag['api_hits']}, "
                f"total_hits={diag['api_total_hits']}, rows={len(rows)}"
            )
        diag["coverage_complete"] = bool(
            diag["api_fetched"]
            and api_complete
            and diag["truncated"] == 0
            and diag["detail_failed"] == 0
        )
        return unique
    finally:
        try:
            session.close()
        except Exception:
            pass
