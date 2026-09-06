from __future__ import annotations

import os
import re
import time
import uuid
import unicodedata
import requests
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

BOARD_URL = "https://www.comunidad.madrid/info/servicios/educacion/ciencia-e-investigacion/buscador-empleo-idi"
POEM_BASE = "https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/"
POEM_API_BASE = "https://apiscm.comunidad.madrid/t/ciudadanos.comunidad.madrid/educacion/portal-empleo/v1.1/"
POEM_OFFERS_API = POEM_API_BASE + "ofertas"

_OK_DETAIL_STATUSES = {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "OK", "CACHE"}
_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+", re.I)
_EXTERNAL_DETAIL_CUES = (
    "descripción de este puesto está disponible aquí",
    "descripcion de este puesto esta disponible aqui",
    "job description is available here",
    "full description is available",
    "see the full job description",
)

_EXTERNAL_GENERIC_TITLE_TOKENS = {
    "investigador", "investigadora", "researcher", "research", "postdoctoral", "postdoc",
    "doctor", "doctora", "contratado", "contratada", "contrato", "position", "puesto",
    "project", "proyecto", "manager", "gestor", "gestora", "support", "apoyo", "senior",
    "junior", "assistant", "ayudante", "tecnico", "tecnica", "scientist", "fellow", "2026",
}

_EXTERNAL_JOB_CUE_PATTERNS = (
    r"\b(?:deadline|closing date|fecha limite|fecha límite|fin del plazo|plazo de solicitud|termini)\b",
    r"\b(?:responsibilities|responsabilidades|funciones|functions|tasques|duties)\b",
    r"\b(?:requirements|requisitos|qualifications|perfil que buscamos|experiencia requerida|experience required)\b",
    r"\b(?:how to apply|apply for this job|solicitudes|candidaturas|presentacion de solicitudes|presentación de solicitudes)\b",
    r"\b(?:salary|salario|retribucion|retribución|contract type|tipo de contrato|duracion|duración|jornada)\b",
)

_COUNT_RE = re.compile(r"Mostrando\s+(\d+)\s*[-–]\s*(\d+)\s+de\s+([\d.]+)\s+ofertas\s+activas", re.I)
_POEM_ID_RE = re.compile(r"(?:poem_webapp/.+?ver-oferta/|ver-oferta/)(\d+)", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
_REL_DATE_RE = re.compile(r"\bhace\s+\d+\s+(?:d[ií]as?|horas?|semanas?)\b", re.I)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _canonical(url: str) -> str:
    return str(url or "").split("#", 1)[0].rstrip("/")


def _looks_like_offer_href(href: str) -> bool:
    low = str(href or "").lower()
    return "poem_webapp" in low and "ver-oferta" in low


def _candidate_rows(soup: BeautifulSoup):
    """Yield likely server-rendered result cards with broad Drupal-compatible fallbacks."""
    seen = set()
    selectors = [
        # Current Comunidad de Madrid Drupal renderer (confirmed against a live
        # 2026-08-27 capture). The offer link is an empty overlay anchor, while
        # title/company/date live in sibling elements.
        ".view-content .job-item",
        ".job-item",
        # Historical / defensive Drupal fallbacks.
        ".view-content .views-row",
        ".views-row",
        "article",
        ".search-result",
        ".result-item",
        ".card",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            ident = id(node)
            if ident in seen:
                continue
            seen.add(ident)
            txt = _clean(node.get_text(" ", strip=True))
            if len(txt) < 20:
                continue
            # Only keep blocks that look like an offer result, not filter panels.
            has_heading = node.find(["h2", "h3", "h4", "h5"]) is not None
            has_offer_link = any(_looks_like_offer_href(a.get("href", "")) for a in node.find_all("a", href=True))
            if has_heading or has_offer_link:
                yield node


def _best_title(node) -> str:
    tag = node.select_one(".job-title")
    if tag:
        txt = _clean(tag.get_text(" ", strip=True))
        if txt and len(txt) <= 300:
            return txt
    for tagname in ("h3", "h2", "h4", "h5"):
        tag = node.find(tagname)
        if tag:
            txt = _clean(tag.get_text(" ", strip=True))
            if txt and len(txt) <= 300:
                return txt
    # Prefer the offer-link label if present.
    for a in node.find_all("a", href=True):
        if _looks_like_offer_href(a.get("href", "")):
            txt = _clean(a.get_text(" ", strip=True))
            if txt:
                return txt
    return ""


def _extract_links(node, base_url: str) -> list[str]:
    links = []
    for a in node.find_all("a", href=True):
        href = _clean(a.get("href"))
        if not href or href.startswith(("mailto:", "javascript:")):
            continue
        u = urljoin(base_url, href)
        low = u.lower()
        # Ignore the board's own filter/pagination links.
        if "buscador-empleo-idi" in low and ("?" in u or "#" in u):
            continue
        if u not in links:
            links.append(u)
    return links


def _pick_offer_url(links: list[str]) -> tuple[str, str]:
    # Strongest evidence: official POEM offer id.
    for u in links:
        m = _POEM_ID_RE.search(u)
        if m:
            return POEM_BASE + m.group(1), m.group(1)
    # Some result cards may point straight to the employer vacancy page.
    for u in links:
        host = urlparse(u).netloc.lower()
        if host and "comunidad.madrid" not in host:
            return u, ""
    return "", ""


def _infer_company_and_location(node, title: str) -> tuple[str, str]:
    """Best-effort metadata only; evaluation is driven by the full JD, not these guesses."""
    # Current Madrid renderer uses explicit semantic classes. Prefer those so
    # we do not depend on prose order or accidentally absorb the whole card.
    company = ""
    location = ""
    current_company = node.select_one(".job-organization, .job-organisation, .job-company")
    current_location = node.select_one(".job-location")
    if current_company:
        company = _clean(current_company.get_text(" ", strip=True))
    if current_location:
        location = _clean(current_location.get_text(" ", strip=True))

    for tag in node.find_all(True):
        cls = " ".join(tag.get("class") or []).lower()
        txt = _clean(tag.get_text(" ", strip=True))
        if not txt:
            continue
        if not company and any(k in cls for k in ("company", "empresa", "entity", "entidad", "organisation", "organization")):
            if txt != title and len(txt) < 220:
                company = txt
        if not location and any(k in cls for k in ("location", "localidad", "province", "provincia")):
            if len(txt) < 120:
                location = txt

    # Conservative text fallback. Madrid is overwhelmingly the portal's current location,
    # but only infer it when it literally appears in the card text.
    text = _clean(node.get_text(" ", strip=True))
    if not location and re.search(r"\bMadrid\b", text, re.I):
        location = "Madrid, Spain"
    return company, location


def parse_listing_page(html: str, page_url: str = BOARD_URL) -> tuple[list[dict], dict]:
    """Parse one Madrid I+D+i results page.

    The public page is server-rendered by Comunidad de Madrid. We deliberately avoid
    source-specific relevance filtering: the newest result pages form a geographic/source
    holdout and every discovered vacancy is passed downstream if its full JD can be resolved.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    page_text = _clean(soup.get_text(" ", strip=True))
    mcount = _COUNT_RE.search(page_text)
    shown_start = int(mcount.group(1)) if mcount else None
    shown_end = int(mcount.group(2)) if mcount else None
    total_active = int(mcount.group(3).replace(".", "")) if mcount else None
    expected_cards = (shown_end - shown_start + 1) if mcount and shown_end >= shown_start else None

    rows = []
    seen_keys = set()
    for node in _candidate_rows(soup):
        title = _best_title(node)
        if not title:
            continue
        low_title = title.lower()
        if low_title in {"área", "titulación", "programa / tipo de oferta", "localidad", "filtros"}:
            continue

        links = _extract_links(node, page_url)
        url, jid = _pick_offer_url(links)
        text = _clean(node.get_text(" ", strip=True))
        # Result-card text is intentionally retained only as a snippet, never treated as
        # a full JD. This protects scoring integrity if the POEM SPA cannot be resolved.
        company, location = _infer_company_and_location(node, title)
        date = ""
        dm = _DATE_RE.search(text) or _REL_DATE_RE.search(text)
        if dm:
            date = dm.group(1) if hasattr(dm, "group") and dm.lastindex else dm.group(0)

        key = jid or url or f"{title}|{company}|{date}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        row = JobRecord(
            source="Madrid I+D+i",
            title=title,
            company=company,
            location=location or "Madrid, Spain",
            date=date,
            url=url,
            id=jid,
            description=text[:2200],
            search_query="newest_feed_holdout",
        ).to_dict()
        row["detail_candidates"] = links
        # This board explicitly labels the returned set as "ofertas activas". Preserve
        # that source-level fact separately from any employer application deadline.
        row["source_listing_active"] = True
        rows.append(row)

    # Fallback for unusual markup: anchors can be parsed even if no standard result
    # wrapper selector matched.
    if not rows:
        for a in soup.find_all("a", href=True):
            href = urljoin(page_url, a.get("href", ""))
            mm = _POEM_ID_RE.search(href)
            if not mm:
                continue
            title = _clean(a.get_text(" ", strip=True))
            if not title:
                continue
            jid = mm.group(1)
            if jid in seen_keys:
                continue
            seen_keys.add(jid)
            fallback = JobRecord(
                source="Madrid I+D+i", title=title, company="", location="Madrid, Spain",
                url=POEM_BASE + jid, id=jid, description="", search_query="newest_feed_holdout"
            ).to_dict()
            fallback["source_listing_active"] = True
            rows.append(fallback)

    return rows, {
        "total_active": total_active,
        "page_text_has_count": bool(mcount),
        "shown_start": shown_start,
        "shown_end": shown_end,
        "expected_cards": expected_cards,
    }


def _poem_api_headers() -> dict[str, str]:
    """Headers used by the public POEM Angular client for anonymous offer reads.

    The public client marks the request as application-credentials and the gateway
    handles the anonymous application token. No user/session credential is required.
    """
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "application-credentials": "true",
        "x-trace-id": uuid.uuid4().hex,
    }


def _iter_scalar_fields(value: Any, prefix: str = ""):
    """Yield useful scalar values from POEM's nested offer JSON."""
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _iter_scalar_fields(child, child_prefix)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from _iter_scalar_fields(child, f"{prefix}[{i}]")
    elif value not in (None, "", [], {}):
        yield prefix, value


def _pretty_api_label(path: str) -> str:
    key = str(path or "").split(".")[-1]
    key = re.sub(r"\[\d+\]", "", key)
    # Common POEM DTO/property names. Unknown fields are still preserved below.
    labels = {
        "dsPuesto": "Position",
        "dsReferencia": "Reference",
        "dsEmpresa": "Organisation",
        "dsOtros": "Additional information",
        "dsDescripcion": "Description",
        "dsFunciones": "Functions",
        "dsRequisitos": "Requirements",
        "dsExperiencia": "Experience",
        "dsConocimientos": "Knowledge and skills",
        "dsFormacion": "Training",
        "dsTitulacion": "Qualification",
        "dsTipo": "Type",
        "dsNombre": "Name",
        "fcPublicacionDesde": "Publication start",
        "fcPublicacionHasta": "Portal listing end",
        "nmNumPlazas": "Number of positions",
    }
    if key in labels:
        return labels[key]
    # Turn camelCase-ish names into a readable audit label without pretending to know semantics.
    key = re.sub(r"^(ds|fc|nm|id)", "", key)
    key = re.sub(r"(?<!^)(?=[A-ZÁÉÍÓÚÑ])", " ", key).replace("_", " ").strip()
    return key[:1].upper() + key[1:] if key else path


def _format_iso_deadline(value: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T", str(value or ""))
    if not m:
        return str(value or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"


def _render_poem_offer_data(data: dict) -> str:
    """Render public POEM JSON into deterministic text suitable for audit/scoring.

    We keep all human-readable scalar content but suppress opaque numeric IDs and obvious
    technical/null values. `fcPublicacionHasta` is preserved as a portal listing-end field;
    it is not treated as an application deadline because the live Madrid holdout showed
    that employer deadlines and POEM publication windows often differ.
    """
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for path, raw in _iter_scalar_fields(data):
        leaf = path.split(".")[-1]
        # IDs add noise but no job meaning. Keep nm* counts, dates and ds* descriptions.
        if re.match(r"^id[A-Z_]", leaf) or leaf in {"idOferta"}:
            continue
        if isinstance(raw, bool):
            continue
        value = _clean(raw)
        if not value:
            continue
        if leaf == "fcPublicacionHasta":
            value = _format_iso_deadline(value)
        label = _pretty_api_label(path)
        pair = (label.lower(), value.lower())
        if pair in seen:
            continue
        seen.add(pair)
        lines.append(f"{label}: {value}")
    return "\n".join(lines)[:50000]


def _extract_public_urls(value: Any) -> list[str]:
    urls: list[str] = []
    for _, raw in _iter_scalar_fields(value):
        if not isinstance(raw, str):
            continue
        for match in _URL_RE.findall(raw):
            u = match.rstrip(".,;:)")
            if u not in urls:
                urls.append(u)
    return urls


def _is_external_job_url(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    low = url.lower()
    if not host:
        return False
    # Exclude POEM/API/auth utility endpoints, but allow ordinary public
    # comunidad.madrid pages/PDFs if an offer explicitly points to one.
    if host == "apiscm.comunidad.madrid":
        return False
    if host == "gestiona.comunidad.madrid":
        return False
    if host.endswith("madrid.org") and any(x in low for x in ("portalapps/util", "mova_rest", "auto_rest")):
        return False
    if any(x in low for x in ("facebook.com", "linkedin.com", "twitter.com", "x.com")):
        return False
    return True


def _norm_match_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _clean(value).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _signature_tokens(value: Any) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", _norm_match_text(value))
    return [t for t in toks if len(t) >= 5 and t not in _EXTERNAL_GENERIC_TITLE_TOKENS]


def _external_job_cue_count(text: str) -> int:
    norm = _norm_match_text(text)
    return sum(bool(re.search(p, norm, re.I)) for p in _EXTERNAL_JOB_CUE_PATTERNS)


def _external_detail_matches_job(job: dict, text: str, url: str) -> bool:
    """Reject generic home/group/index pages returned by external POEM links.

    Madrid POEM sometimes links to a project/group homepage rather than the vacancy itself.
    A long generic page must not become a Full JD merely because it is on the employer site.
    We therefore require job-specific identity evidence (title/reference tokens) plus vacancy
    structure, or a strong vacancy-structure fallback for genuinely generic role titles.
    """
    clean = _clean(text)
    if len(clean) < 220:
        return False
    hay = _norm_match_text(f"{clean} {url}")
    title_tokens = _signature_tokens(job.get("title", ""))
    ref_tokens = _signature_tokens(job.get("poem_reference", ""))
    # Company words are not job identity; remove them from the reference/title signature.
    company_tokens = set(_signature_tokens(job.get("company", "")))
    sig = []
    for tok in title_tokens + ref_tokens:
        if tok not in company_tokens and tok not in sig:
            sig.append(tok)
    matched = [tok for tok in sig if tok in hay]
    cues = _external_job_cue_count(clean)

    # A specific vacancy/reference signature is strong evidence when the page also looks
    # like a vacancy rather than a general research-group or project page.
    if sig:
        ratio = len(matched) / len(sig)
        if cues >= 2 and (len(matched) >= 2 or ratio >= 0.50):
            return True
        if cues >= 2 and any(len(tok) >= 9 for tok in matched):
            return True
        return False

    # Generic titles (e.g. "Investigador contratado") have no usable identity tokens.
    # Accept only when the page contains several independent vacancy cues and mentions the
    # employer. This preserves real job pages such as generic Project Manager vacancies while
    # rejecting group homepages, project pages and broad institutional bulletins.
    company_sig = _signature_tokens(job.get("company", ""))
    company_match = not company_sig or any(tok in hay for tok in company_sig[:4])
    return cues >= 3 and company_match


def _api_has_substantive_detail(data: dict, rendered: str) -> bool:
    """Whether POEM structured fields themselves are enough to score defensibly."""
    strong_keys = {
        "dsfunciones", "dsfuncion", "dsrequisitos", "dsexperiencia", "dsconocimientos",
        "dsformacion", "dstitulacion", "dsperfil", "dsdescripcion", "dscompetencias",
    }
    hits = 0
    chars = 0
    for path, raw in _iter_scalar_fields(data):
        leaf = re.sub(r"[^a-z0-9]", "", _norm_match_text(path.split(".")[-1]))
        value = _clean(raw) if isinstance(raw, (str, int, float)) else ""
        if leaf in strong_keys and len(value) >= 40:
            hits += 1
            chars += len(value)
    # Some POEM records use less predictable field names but render clear job sections.
    cue_count = _external_job_cue_count(rendered)
    return hits >= 2 or (hits >= 1 and chars >= 220) or (len(_clean(rendered)) >= 1100 and cue_count >= 2)


def _api_looks_partial(rendered: str, external_urls: list[str]) -> bool:
    low = _clean(rendered).lower()
    if external_urls and any(cue in low for cue in _EXTERNAL_DETAIL_CUES):
        return True
    # Very short API records are metadata, not a defensible Full JD.
    return len(_clean(rendered)) < 650


def _poem_transport(job: dict) -> tuple[str, dict[str, str], int | tuple[int, int], str]:
    """Return the configured POEM transport without weakening the local direct path.

    GitHub-hosted runners currently time out against ``apiscm.comunidad.madrid`` while
    Cloudflare reaches the same anonymous public endpoint reliably.  When the relay URL
    is configured we therefore use the fixed-purpose Worker and never silently fall back
    to the slow direct API for that request.  Local runs without relay configuration keep
    the historical direct transport.
    """
    jid = _clean(job.get("id"))
    relay_url = _clean(os.environ.get("MADRID_RELAY_URL", "")).rstrip("/")
    relay_token = _clean(os.environ.get("MADRID_RELAY_TOKEN", ""))

    if relay_url or relay_token:
        if not (relay_url and relay_token):
            return "", {}, (5, 15), "relay_config_invalid"
        return (
            f"{relay_url}/offer/{jid}",
            {"Accept": "application/json", "Authorization": f"Bearer {relay_token}"},
            (5, 15),
            "cloudflare_relay",
        )

    return f"{POEM_OFFERS_API}/{jid}", _poem_api_headers(), (10, 45), "direct_api"


def _fetch_poem_api(job: dict, session, timeout) -> tuple[dict, str]:
    jid = _clean(job.get("id"))
    if not jid:
        return {}, "POEM_API_NO_ID"

    url, headers, transport_timeout, transport = _poem_transport(job)
    job["poem_transport"] = transport
    if transport == "relay_config_invalid":
        return {}, "POEM_RELAY_CONFIG_INVALID"

    # Caller-supplied timeouts remain authoritative for direct/local operation.  The
    # relay path deliberately uses a short bounded timeout because GitHub->Cloudflare is
    # the fast transport and repeated long waits would recreate the original bottleneck.
    request_timeout = transport_timeout if transport == "cloudflare_relay" else timeout
    try:
        # The Cloudflare Worker already owns the bounded upstream retry policy.  Do not
        # pass relay responses through urllib3's generic 5xx retry adapter as well: doing
        # so multiplied a single Worker 504 into up to four 12-second relay trips.
        # External employer pages still use the caller's retry-enabled session below.
        if transport == "cloudflare_relay":
            r = requests.get(url, headers=headers, timeout=request_timeout, allow_redirects=True)
        else:
            r = session.get(url, headers=headers, timeout=request_timeout, allow_redirects=True)
    except Exception as exc:
        prefix = "POEM_RELAY_FETCH_FAILED" if transport == "cloudflare_relay" else "POEM_API_FETCH_FAILED"
        return {}, f"{prefix}: {type(exc).__name__}: {exc}"
    if r.status_code != 200:
        prefix = "POEM_RELAY_HTTP" if transport == "cloudflare_relay" else "POEM_API_HTTP"
        return {}, f"{prefix}_{r.status_code}"
    try:
        payload = r.json()
    except Exception:
        return {}, "POEM_RELAY_NON_JSON" if transport == "cloudflare_relay" else "POEM_API_NON_JSON"
    if not isinstance(payload, dict):
        return {}, "POEM_RELAY_BAD_PAYLOAD" if transport == "cloudflare_relay" else "POEM_API_BAD_PAYLOAD"
    result = payload.get("result") or {}
    data = payload.get("data")
    if isinstance(result, dict) and result.get("status") is False:
        return {}, f"POEM_API_RESULT_ERROR_{result.get('http_code', '')}".rstrip("_")
    if not isinstance(data, dict) or not data:
        return {}, "POEM_API_EMPTY_DATA"
    return data, "POEM_API_OK"


def _apply_poem_metadata(job: dict, data: dict) -> None:
    """Use authoritative POEM metadata to improve identity/location/date fields."""
    if data.get("dsPuesto"):
        # Keep card title unless it was empty; card title is often cleaner for user-facing output.
        job.setdefault("poem_title", _clean(data.get("dsPuesto")))
    if data.get("dsEmpresa"):
        job["company"] = _clean(data.get("dsEmpresa")) or job.get("company", "")
    provincia = ""
    municipio = ""
    if isinstance(data.get("provinciaDto"), dict):
        provincia = _clean(data["provinciaDto"].get("dsNombre"))
    if isinstance(data.get("municipioDto"), dict):
        municipio = _clean(data["municipioDto"].get("dsNombre"))
    if municipio and provincia:
        job["location"] = f"{municipio}, {provincia}, Spain"
    elif provincia:
        job["location"] = f"{provincia}, Spain"
    if data.get("fcPublicacionHasta"):
        # POEM names this publication-window end. Keep it for audit/traceability, but do
        # not silently reinterpret it as the employer's application deadline.
        job["poem_publication_end"] = str(data.get("fcPublicacionHasta"))
        job["poem_listing_end"] = str(data.get("fcPublicacionHasta"))
    if data.get("fcPublicacionDesde"):
        job["poem_publication_start"] = str(data.get("fcPublicacionDesde"))
    if data.get("dsReferencia"):
        job["poem_reference"] = _clean(data.get("dsReferencia"))


def _fetch_detail_candidates(job: dict, session, timeout) -> tuple[str, str, str, str]:
    """Resolve Madrid Full JD with POEM-first short-circuiting.

    The public POEM JSON is authoritative for the exact offer id and is normally much
    faster and more reliable than arbitrary employer pages from cloud runners.  If its
    structured fields already contain enough substantive vacancy text to score
    defensibly, return it immediately and do not fetch external URLs.  External links are
    attempted only when the POEM record is genuinely partial or insufficient.

    Resolution order:
      1) public POEM JSON for the exact offer id;
      2) return POEM immediately when it is substantive enough for Full-JD scoring;
      3) otherwise try employer/public URLs exposed by POEM, then card-level external URLs;
      4) if no external page resolves, keep an insufficient POEM record as unresolved.

    Short card snippets and SPA shells are never scored as Full JDs.
    """
    api_data, api_status = _fetch_poem_api(job, session, timeout)
    rendered = ""
    api_external: list[str] = []
    if api_data:
        _apply_poem_metadata(job, api_data)
        rendered = _render_poem_offer_data(api_data)
        api_external = [u for u in _extract_public_urls(api_data) if _is_external_job_url(u)]
        job["poem_api_url"] = f"{POEM_OFFERS_API}/{_clean(job.get('id'))}"
        if api_external:
            job["poem_external_urls"] = api_external

    # V1.71: POEM-first fast path.  If the exact official API response already provides a
    # defensible Full JD, external employer pages add latency and failure modes without
    # improving scoring integrity.  This is intentionally evaluated before any external
    # fetches.  Truly redirect-style / metadata-only POEM records still fall through.
    if rendered and _api_has_substantive_detail(api_data, rendered):
        return rendered, "OK", job.get("poem_api_url", ""), "poem_api"
    if rendered and not _api_looks_partial(rendered, api_external):
        return rendered, "OK", job.get("poem_api_url", ""), "poem_api"

    candidates: list[str] = []
    for u in api_external:
        if u not in candidates:
            candidates.append(u)
    for u in job.get("detail_candidates") or []:
        if u and "poem_webapp" not in str(u).lower() and u not in candidates:
            candidates.append(u)

    best_external_status = "NO_EXTERNAL_DETAIL_URL"
    external_mismatches = 0
    for u in candidates[:8]:
        detail, status = fetch_url_text(
            u, timeout=timeout, title_hint=job.get("title", ""), session=session,
        )
        if detail and status in _OK_DETAIL_STATUSES:
            if _external_detail_matches_job(job, detail, u):
                return detail, status, u, "external_from_poem_api" if u in api_external else "external_from_card"
            external_mismatches += 1
            best_external_status = "EXTERNAL_DETAIL_MISMATCH"
            continue
        if status and status != "NO_URL":
            best_external_status = status

    if external_mismatches:
        job["external_detail_mismatch_count"] = external_mismatches
    if api_status != "POEM_API_OK":
        return "", api_status, "", "poem_api_failed"
    if rendered:
        return "", "POEM_API_PARTIAL_DETAIL", job.get("poem_api_url", ""), "poem_api_partial"
    return "", best_external_status, "", "unresolved"



_RELAY_RECOVERY_DELAY_SECONDS = 1.0


def _is_retryable_relay_failure(status: str) -> bool:
    status = _clean(status)
    if status.startswith("POEM_RELAY_FETCH_FAILED"):
        return True
    match = re.fullmatch(r"POEM_RELAY_HTTP_(\d{3})", status)
    if not match:
        return False
    code = int(match.group(1))
    return code == 429 or 500 <= code <= 599


def _resolve_detail_row(index: int, row: dict, timeout) -> tuple[int, str, str, str, str]:
    """Resolve one Madrid vacancy using an isolated retry session.

    Madrid can expose up to 100 current vacancies and some employer detail hosts are
    slow from cloud runners. Each row is independent, so bounded parallel resolution
    avoids one slow external host serially blocking the entire source while preserving
    the exact same Full-JD resolution rules for every vacancy.
    """
    detail_session = make_retry_session(total_retries=3, backoff_factor=1.0)
    try:
        detail, status, resolved_url, resolution_method = _fetch_detail_candidates(
            row, detail_session, timeout=timeout
        )
        return index, detail, status, resolved_url, resolution_method
    finally:
        try:
            detail_session.close()
        except Exception:
            pass


def _enrich_detail_rows(unique: list[dict], diag: dict, timeout, detail_workers: int) -> None:
    """Populate Madrid Full JDs with bounded concurrency and deterministic output order."""
    requested_workers = max(1, int(detail_workers or 1))
    relay_configured = bool(
        _clean(os.environ.get("MADRID_RELAY_URL", ""))
        and _clean(os.environ.get("MADRID_RELAY_TOKEN", ""))
    )
    # The Madrid API is fast through Cloudflare when queried gently, but the diagnostic
    # runs showed intermittent upstream 504s under six-way fan-out.  Apply modest
    # backpressure only to the relay transport; local/direct behavior is unchanged.
    workers = min(requested_workers, 3) if relay_configured else requested_workers
    diag["detail_workers_requested"] = requested_workers
    diag["detail_workers"] = workers
    diag["relay_detail_worker_cap"] = 3 if relay_configured else None
    diag["detail_attempts"] += len(unique)

    results: dict[int, tuple[str, str, str, str]] = {}
    if workers == 1 or len(unique) <= 1:
        # Preserve the historical single-session path for tests/callers that explicitly
        # request one worker. Production passes a bounded worker count via the CLI.
        detail_session = make_retry_session(total_retries=3, backoff_factor=1.0)
        try:
            for index, row in enumerate(unique):
                results[index] = _fetch_detail_candidates(row, detail_session, timeout=timeout)
        finally:
            try:
                detail_session.close()
            except Exception:
                pass
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(unique)), thread_name_prefix="madrid-detail") as pool:
            futures = {
                pool.submit(_resolve_detail_row, index, row, timeout): index
                for index, row in enumerate(unique)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    _, detail, status, resolved_url, resolution_method = future.result()
                except Exception as exc:
                    detail = ""
                    status = f"DETAIL_WORKER_FAILED: {type(exc).__name__}: {exc}"
                    resolved_url = ""
                    resolution_method = "worker_failed"
                results[index] = (detail, status, resolved_url, resolution_method)

    # V1.73: keep the same maximum of two relay attempts per affected offer, but avoid
    # making both attempts back-to-back inside one Worker invocation.  V1.72 showed that
    # immediate nested upstream retries shortened runtime but still produced many 504s.
    # Let the first pass finish, then retry only transient relay failures after a short
    # cooldown.  This gives the Madrid upstream time to recover without increasing the
    # relay timeout, concurrency cap, or per-offer attempt budget.
    recovery_candidates: list[int] = []
    if relay_configured:
        recovery_candidates = [
            index for index, result in results.items()
            if _is_retryable_relay_failure(result[1])
        ]
    diag["relay_recovery_candidates"] = len(recovery_candidates)
    diag["relay_recovery_attempts"] = 0
    diag["relay_recovery_success"] = 0
    diag["relay_recovery_failed"] = 0

    if recovery_candidates:
        time.sleep(_RELAY_RECOVERY_DELAY_SECONDS)
        diag["relay_recovery_attempts"] = len(recovery_candidates)
        recovery_workers = min(workers, len(recovery_candidates))
        with ThreadPoolExecutor(
            max_workers=recovery_workers, thread_name_prefix="madrid-detail-recovery"
        ) as pool:
            recovery_futures = {
                pool.submit(_resolve_detail_row, index, unique[index], timeout): index
                for index in recovery_candidates
            }
            for future in as_completed(recovery_futures):
                index = recovery_futures[future]
                try:
                    _, detail, status, resolved_url, resolution_method = future.result()
                except Exception as exc:
                    detail = ""
                    status = f"DETAIL_WORKER_FAILED: {type(exc).__name__}: {exc}"
                    resolved_url = ""
                    resolution_method = "worker_failed"
                results[index] = (detail, status, resolved_url, resolution_method)
                unique[index]["relay_recovery_attempted"] = True
                if detail and status in _OK_DETAIL_STATUSES:
                    diag["relay_recovery_success"] += 1
                else:
                    diag["relay_recovery_failed"] += 1

    counts = Counter()
    for index, row in enumerate(unique):
        detail, status, resolved_url, resolution_method = results.get(
            index, ("", "DETAIL_WORKER_MISSING_RESULT", "", "worker_failed")
        )
        row["full_detail"] = detail
        row["detail_status"] = status
        if resolved_url:
            row["detail_resolved_url"] = resolved_url
        row["detail_resolution_method"] = resolution_method
        diag["external_detail_mismatches"] += int(row.get("external_detail_mismatch_count") or 0)
        counts[status] += 1
        transport = _clean(row.get("poem_transport")) or "unknown"
        transport_counts = diag.setdefault("poem_transport_counts", {})
        transport_counts[transport] = int(transport_counts.get(transport, 0) or 0) + 1
        if row.get("poem_api_url"):
            diag["poem_api_success"] += 1
        if status == "POEM_API_PARTIAL_DETAIL":
            diag["poem_api_partial"] += 1
        elif str(status).startswith("POEM_API_") and status != "POEM_API_OK":
            diag["poem_api_failed"] += 1
        if detail and status in _OK_DETAIL_STATUSES:
            diag["detail_success"] += 1
            if resolution_method == "poem_api":
                diag["detail_resolved_via_poem_api"] += 1
                diag["detail_resolved_via_poem"] += 1
            elif resolution_method == "external_from_poem_api":
                diag["detail_resolved_via_external_api_link"] += 1
                diag["detail_resolved_via_external"] += 1
            else:
                diag["detail_resolved_via_external"] += 1
        else:
            diag["detail_failed"] += 1
    diag["detail_status_counts"] = dict(counts)

def collect(
    diagnostics: dict | None = None,
    max_pages: int = 10,
    max_jobs: int = 100,
    timeout: int | tuple[int, int] = (10, 60),
    enrich_detail: bool = True,
    detail_workers: int = 1,
    debug_html_path: str | None = None,
) -> list[dict]:
    """Collect the newest Madrid I+D+i public vacancies as a no-tuning holdout.

    No relevance prefilter is applied. We page newest-first through the official public
    search page, deduplicate the cards, and require a real detail page before scoring.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": "Madrid I+D+i",
        "board_url": BOARD_URL,
        "feed_mode": "official_public_newest_pages",
        "coverage_scope": "newest_requested_pages",
        "portal_full_coverage": False,
        "pages_requested": max_pages,
        "pages_fetched": 0,
        "page_errors": [],
        "total_active_reported": None,
        "parsed_cards": 0,
        "unique_cards": 0,
        "poem_ids_found": 0,
        "cards_without_detail_url": 0,
        "max_jobs": max_jobs,
        "truncated": 0,
        "detail_attempts": 0,
        "detail_workers": max(1, int(detail_workers or 1)),
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "detail_resolved_via_external": 0,
        "detail_resolved_via_poem": 0,
        "detail_resolved_via_poem_api": 0,
        "detail_resolved_via_external_api_link": 0,
        "poem_api_success": 0,
        "poem_api_failed": 0,
        "poem_api_partial": 0,
        "poem_relay_configured": bool(_clean(os.environ.get("MADRID_RELAY_URL", "")) and _clean(os.environ.get("MADRID_RELAY_TOKEN", ""))),
        "poem_transport_counts": {},
        "external_detail_mismatches": 0,
        "coverage_complete": True,
        "coverage_warning": "",
        "page_card_counts": [],
        "page_expected_counts": [],
        "card_count_mismatches": [],
        "first_page_parse_guard_triggered": False,
    })

    session = make_retry_session(total_retries=3, backoff_factor=1.0)
    all_rows = []
    first_html = ""
    try:
        for page in range(max_pages):
            try:
                params = {"search": ""}
                if page:
                    params["page"] = page
                r = session.get(BOARD_URL, params=params, timeout=timeout, allow_redirects=True)
                r.raise_for_status()
                diag["pages_fetched"] += 1
                if page == 0:
                    first_html = r.text
                parsed, pdiag = parse_listing_page(r.text, r.url)
                if pdiag.get("total_active") is not None and diag["total_active_reported"] is None:
                    diag["total_active_reported"] = pdiag["total_active"]
                    diag["portal_full_coverage"] = bool(pdiag["total_active"] <= max_pages * 10)

                expected = pdiag.get("expected_cards")
                diag["page_card_counts"].append(len(parsed))
                diag["page_expected_counts"].append(expected)

                # A successful HTTP response is not evidence of coverage if the portal
                # itself reports visible cards that our parser failed to extract.
                if expected is not None and len(parsed) != expected:
                    mismatch = {
                        "page": page,
                        "expected": expected,
                        "parsed": len(parsed),
                        "shown_start": pdiag.get("shown_start"),
                        "shown_end": pdiag.get("shown_end"),
                    }
                    diag["card_count_mismatches"].append(mismatch)
                    diag["coverage_complete"] = False
                    diag["coverage_warning"] = (
                        f"Madrid I+D+i parser coverage mismatch on page {page}: "
                        f"portal reports {expected} visible cards but parser extracted {len(parsed)}"
                    )
                    if page == 0 and (pdiag.get("total_active") or 0) > 0 and not parsed:
                        diag["first_page_parse_guard_triggered"] = True
                    break

                diag["parsed_cards"] += len(parsed)
                if not parsed:
                    # Only treat an empty page as natural exhaustion when the portal
                    # does not simultaneously report visible result rows.
                    if page == 0 and (pdiag.get("total_active") or 0) > 0:
                        diag["coverage_complete"] = False
                        diag["first_page_parse_guard_triggered"] = True
                        diag["coverage_warning"] = (
                            "Madrid I+D+i reports active vacancies but the first page parser returned zero cards"
                        )
                    break
                all_rows.extend(parsed)
            except Exception as exc:
                diag["page_errors"].append({"page": page, "error": f"{type(exc).__name__}: {exc}"})
                diag["coverage_complete"] = False
                diag["coverage_warning"] = f"Madrid I+D+i feed page {page} failed; stopped to avoid a silent coverage gap"
                break

        # Stable dedupe by POEM id, then URL, then normalized title/company.
        unique = []
        seen = set()
        for row in all_rows:
            key = row.get("id") or row.get("url") or f"{_clean(row.get('title')).lower()}|{_clean(row.get('company')).lower()}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        diag["unique_cards"] = len(unique)
        diag["poem_ids_found"] = sum(bool(r.get("id")) for r in unique)
        diag["cards_without_detail_url"] = sum(not bool(r.get("url") or r.get("detail_candidates")) for r in unique)

        if len(unique) > max_jobs:
            diag["truncated"] = len(unique) - max_jobs
            unique = unique[:max_jobs]

        if debug_html_path and first_html:
            try:
                from pathlib import Path
                dp = Path(debug_html_path)
                dp.parent.mkdir(parents=True, exist_ok=True)
                dp.write_text(first_html, encoding="utf-8")
            except Exception:
                pass

        if enrich_detail:
            _enrich_detail_rows(unique, diag, timeout=(10, 45), detail_workers=detail_workers)

        return unique
    finally:
        try:
            session.close()
        except Exception:
            pass
