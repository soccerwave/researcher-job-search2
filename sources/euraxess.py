from __future__ import annotations
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import time
from bs4 import BeautifulSoup
from .common import JobRecord
from .fetch_detail import fetch_url_text, make_retry_session

# EURAXESS Spain's official "Search Jobs" link currently points to the shared
# EURAXESS jobs search with the Spain country facet job_country:788.
SEARCH_BASES = [
    "https://www.euraxess.es",
    "https://euraxess.ec.europa.eu",
]
SPAIN_FACET_VALUE = "job_country:788"
DEFAULT_PAGES = 8
DEFAULT_MAX_CANDIDATES = 80

CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache"
DETAIL_CACHE_PATH = CACHE_DIR / "euraxess_details.json"
FEED_CACHE_DIR = CACHE_DIR / "euraxess_feeds"


def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _feed_disk_path(pages: int, cutoff_date: date) -> Path:
    return FEED_CACHE_DIR / f"spain_{cutoff_date.isoformat()}_{max(1, pages)}p.json"


def _is_rate_limited_status(status: str) -> bool:
    s = (status or "").lower()
    return "429" in s or "too many requests" in s



# V1.8 card-level discovery is taxonomy-based rather than exact-query based.
# EURAXESS currently gives us a reliable Spain facet, but its free-text query
# behavior is not reliable enough to use as the first precision gate.
CARD_ROLE_PATTERNS = [
    r"\bpostdoc(?:toral)?\b", r"\bresearcher\b", r"\bresearch fellow\b",
    r"\bresearch scientist\b", r"\bresearch associate\b", r"\bscientist\b",
    r"\bresearch assistant\b", r"\bresearch manager\b", r"\bresearch officer\b",
    r"\bresearch management\b", r"\bresearch administrat(?:ion|or|ive)\b",
    r"\bproject manager\b", r"\bproject coordinator\b", r"\bproject officer\b",
    r"\bprogramme officer\b", r"\bprogram officer\b", r"\bgrants? (?:manager|officer)\b",
    r"\bscientific coordinator\b", r"\bclinical research coordinator\b",
    r"\bstudy coordinator\b", r"\btrial coordinator\b", r"\bclinical operations\b",
    r"\br&d&i officer\b", r"\br\s*&\s*d\s*&\s*i officer\b",
    r"\bresearch and innovation officer\b", r"\bknowledge transfer officer\b",
    r"\bmethodological support\b", r"\bmethodology support\b", r"\binnovation project\b",
    r"\binvestigador(?:a)?\b", r"\bgestor(?:a)? de proyectos?\b",
    r"\bcoordinador(?:a)? de proyectos?\b", r"\btecnico(?:a)? de proyectos?\b",
    r"\btecnic(?:a)? de projectes?\b", r"\bgestor(?:a)? de projectes?\b",
]

CARD_DOMAIN_PATTERNS = [
    r"\bexercise\b", r"\bphysical activity\b", r"\bactividad fisica\b",
    r"\bactivitat fisica\b", r"\bsport(?:s)? science\b", r"\bciencias? del deporte\b",
    r"\bciencies? de l esport\b", r"\bfitness\b", r"\bmovement science\b",
    r"\brehabilitation\b", r"\brehabilitacion\b", r"\brehabilitacio\b",
    r"\bhealthy (?:ageing|aging)\b", r"\bsarcopenia\b", r"\bbrain health\b",
    r"\bneuroscience\b", r"\bneurology\b", r"\bcognition\b", r"\bcognitive\b",
    r"\bmental health\b", r"\bpsychological wellbeing\b", r"\bmental wellbeing\b",
    r"\bpsychobiolog", r"\bcortisol\b", r"\bstress[- ]related\b",
    r"\bbehavio.?ral medicine\b", r"\bbehavio.?ral health\b", r"\bbehavio.?r change\b",
    r"\blifestyle intervention\b", r"\blifestyle medicine\b", r"\bhealth promotion\b",
    r"\bpublic health\b", r"\bdigital health\b", r"\behealth\b", r"\bmhealth\b",
    r"\bobesity\b", r"\bhuman performance\b", r"\bclinical exercise\b",
    r"\bhealth sciences?\b", r"\bhealth innovation\b", r"\binnovacion en salud\b",
    r"\binnovacio en salut\b",
]

CARD_DISTANT_TITLE_PATTERNS = [
    r"\bquantum\b", r"\bmaterials? science\b", r"\bion[- ]exchange membrane",
    r"\belectrodialysis\b", r"\bcomputational linguistics\b", r"\bnatural language processing\b",
    r"\bsoftware engineer\b", r"\bdata engineer\b", r"\bchemical engineering\b",
    r"\bcivil engineering\b", r"\bconstruction\b", r"\brenewable energy\b",
    r"\bprotein engineering\b", r"\brna decay\b", r"\bcell signaling\b",
    r"\boncology\b", r"\bcancer\b", r"\bmedical imaging simulation\b",
    r"\bsmall modular reactors?\b", r"\bnuclear reactors?\b", r"\boffshore energy hubs?\b",
    r"\bagricultural ecosystems?\b", r"\bgame species conservation\b",
    r"\bcarbonate geochemistry\b", r"\bcritical raw materials\b", r"\bwater treatment\b",
    r"\bwastewater treatment\b", r"\becological succession\b", r"\bprebiotic chemistry\b", r"\borigin of life\b",
]


# High-recall transferable roles must reach the full-JD evaluator even when the title also
# contains a specialist disease/domain word (e.g. "Study Coordinator for Cancer Clinical
# Trials"). The full evaluator, not the cheap card gate, decides whether the required
# experience makes the role a practical fit. Generic academic postdocs are not protected.
CARD_PROTECTED_TRANSFERABLE_ROLE_PATTERNS = [
    r"\bstudy coordinator\b", r"\btrial coordinator\b", r"\bclinical research coordinator\b",
    r"\bproject manager\b", r"\bproject coordinator\b", r"\bproject officer\b",
    r"\bresearch manager\b", r"\bresearch officer\b", r"\bresearch management\b",
    r"\bresearch administrat(?:ion|or|ive)\b", r"\bgrants? (?:manager|officer)\b",
    r"\br&d&i officer\b", r"\br\s*&\s*d\s*&\s*i officer\b",
    r"\bresearch and innovation officer\b", r"\bknowledge transfer officer\b",
    r"\bclinical operations\b", r"\bmethodological support\b", r"\bmethodology support\b",
]


def _card_candidate(job: dict) -> tuple[bool, list[str]]:
    """Cheap, high-recall triage before fetching a full EURAXESS JD.

    Exact query phrases are intentionally *not* required. A generic postdoc title can
    hide a relevant domain in the full JD, while a job such as 'Researcher in Quantum
    Materials' should still be rejected early.
    """
    title = _norm(job.get("title", ""))
    card_text = _norm(f"{job.get('title','')} {job.get('description','')}")

    # The user is not searching for doctoral-student positions. Do not confuse
    # 'postdoctoral' with a PhD/doctoral-candidate vacancy.
    if re.search(
        r"\bpre[- ]?doctoral\b|\bpredoctoral\b|\bphd (?:position|student|candidate|fellowship|researcher)\b|"
        r"\bdoctoral (?:candidate|student|fellow|network)\b|\bresearch staff in training\b|\bdoctorand",
        title, re.I
    ):
        return False, ["doctoral_student_position"]

    role_hits = [p for p in CARD_ROLE_PATTERNS if re.search(p, title, re.I)]
    domain_hits = [p for p in CARD_DOMAIN_PATTERNS if re.search(p, card_text, re.I)]
    distant_title = any(re.search(p, title, re.I) for p in CARD_DISTANT_TITLE_PATTERNS)
    protected_transferable_role = any(re.search(p, title, re.I) for p in CARD_PROTECTED_TRANSFERABLE_ROLE_PATTERNS)

    if distant_title and not domain_hits and not protected_transferable_role:
        return False, ["obvious_distant_title"]

    reasons = []
    if role_hits:
        reasons.append("target_or_transferable_role_title")
    if domain_hits:
        reasons.append("target_or_adjacent_domain_on_card")

    # A domain keyword alone is usually useful only if the title still looks like a
    # research/project/scientific/clinical/innovation role. One exception is an opaque
    # public-research call title made mostly of a reference number/acronyms (for example
    # "2026/120: 1 T4A ICI 22 ISCIII"). If the card itself has a target/adjacent domain
    # signal, fetch the full JD rather than silently losing a potentially relevant call.
    roleish = bool(re.search(r"research|scient|postdoc|project|coordinat|manager|officer|investig|innov|clinical|study|programme|program|grant|technician|technical|tecnico|tecnic", title, re.I))
    opaque_call_title = bool(
        re.search(r"^\s*\d{4}[/-]\d+", title, re.I)
        or (re.search(r"\b(?:ref|ici|isciii|t\d+[a-z]?)\b", title, re.I) and len(title.split()) <= 10)
    )
    keep = bool(role_hits) or (bool(domain_hits) and (roleish or opaque_call_title))
    if bool(domain_hits) and opaque_call_title and "opaque_research_call_with_domain_signal" not in reasons:
        reasons.append("opaque_research_call_with_domain_signal")
    return keep, reasons or ["no_card_level_fit_signal"]

COUNTRY_NAMES = {
    "spain", "france", "germany", "italy", "portugal", "ireland", "norway", "sweden",
    "finland", "denmark", "netherlands", "belgium", "austria", "poland", "greece",
    "croatia", "romania", "czech republic", "slovakia", "slovenia", "hungary", "malta",
    "cyprus", "estonia", "latvia", "lithuania", "luxembourg", "bulgaria", "serbia",
    "switzerland", "united kingdom", "uk", "iceland", "turkey"
}

QUERY_EXPANSIONS = {
    "exercise physiology": [r"\bexercise physiology\b", r"\bfisiologia del ejercicio\b", r"\bfisiologia de l exercici\b"],
    "physical activity": [r"\bphysical activity\b", r"\bactividad fisica\b", r"\bactivitat fisica\b"],
    "sport science": [
        r"\bsport science\b", r"\bsports science\b", r"\bsport sciences\b",
        r"\bsport and exercise science\b", r"\bciencias? del deporte\b", r"\bciencies? de l esport\b"
    ],
    "exercise neuroscience": [
        r"\bexercise neuroscience\b", r"\bexercise.{0,40}brain\b", r"\bphysical activity.{0,40}brain\b",
        r"\bbrain.{0,40}exercise\b"
    ],
    "brain health exercise": [r"\bbrain health\b.{0,80}\bexercise\b", r"\bexercise\b.{0,80}\bbrain health\b"],
    "healthy ageing physical activity": [
        r"\bhealthy (?:ageing|aging)\b.{0,120}\bphysical activity\b",
        r"\bphysical activity\b.{0,120}\bhealthy (?:ageing|aging)\b"
    ],
    "rehabilitation exercise": [r"\brehabilitation\b.{0,100}\bexercise\b", r"\bexercise\b.{0,100}\brehabilitation\b"],
    "behavioural health physical activity": [
        r"\bbehavio.?ral health\b.{0,120}\bphysical activity\b",
        r"\bphysical activity\b.{0,120}\bbehavio.?ral health\b"
    ],
}

# In-process caches keep repeated queries from re-downloading the same EURAXESS
# Spain feed and the same job details during one live run.
_FEED_CACHE: dict[tuple[int, str], tuple[list[dict], dict]] = {}
_DETAIL_CACHE: dict[str, tuple[str, str]] = {}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _norm(value: str | None) -> str:
    text = _clean(value).lower()
    repl = str.maketrans("áéíóúàèìòùäëïöüñç", "aeiouaeiouaeiounc")
    return text.translate(repl)


def _parse_posted_date(value: str | None) -> date | None:
    """Parse the EURAXESS card date (for example ``27 August 2026``).

    Returns ``None`` rather than guessing when a card has no parseable date.
    """
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _resolve_as_of(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    return date.today()


def _history_cutoff(history_days: int, as_of: str | date | None = None) -> date:
    # Inclusive window: history_days=60 on Aug 27 includes Jun 29 through Aug 27.
    days = max(1, int(history_days))
    return _resolve_as_of(as_of) - timedelta(days=days - 1)


def parse_search_html(html: str, search_query: str = "") -> list[dict]:
    """Parse EURAXESS result cards without treating dates as employers or descriptions as dates."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        title = _clean(link.get_text(" ", strip=True))
        m_id = re.search(r"/jobs/(\d+)(?:$|[/?#])", href)
        if not m_id or not title or len(title) < 8:
            continue
        job_id = m_id.group(1)
        url = f"https://euraxess.ec.europa.eu/jobs/{job_id}"
        if url in seen:
            continue

        # Find the smallest ancestor that looks like a complete result card.
        card = link
        card_text = ""
        for _ in range(8):
            if card.parent is None:
                break
            card = card.parent
            txt = _clean(card.get_text(" ", strip=True))
            if "Posted on:" in txt and ("JOB" in txt or "Work Locations:" in txt or "Research Field:" in txt):
                card_text = txt
                break
        if not card_text:
            continue

        posted = ""
        m = re.search(r"\bPosted on:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", card_text, re.I)
        if m:
            posted = _clean(m.group(1))

        # Parse the pre-'Posted on' header: JOB | country | organisation.
        prefix = card_text.split("Posted on:", 1)[0]
        prefix = re.sub(r"^.*?\bJOB\b\s*", "", prefix, flags=re.I)
        company = ""
        location = ""
        for country in sorted(COUNTRY_NAMES, key=len, reverse=True):
            cm = re.search(rf"\b{re.escape(country)}\b", prefix, re.I)
            if cm:
                location = prefix[cm.start():cm.end()].strip().title()
                company = _clean(prefix[cm.end():])
                break

        jobs.append(JobRecord(
            source="EURAXESS",
            title=title,
            company=company,
            location=location,
            date=posted,
            url=url,
            id=job_id,
            description=card_text[:3500],
            search_query=search_query,
        ).to_dict())
        seen.add(url)

    return jobs


def _extract_labeled_value(text: str, label: str, following_labels: list[str]) -> str:
    if not text:
        return ""
    lookahead = "|".join(re.escape(x) for x in following_labels)
    m = re.search(rf"\b{re.escape(label)}\s+(.+?)(?=\s+(?:{lookahead})\b|$)", text, re.I)
    return _clean(m.group(1)) if m else ""


def _enrich_from_detail(job: dict, detail: str) -> None:
    company = _extract_labeled_value(detail, "Organisation/Company", [
        "Department", "Research Field", "Researcher Profile", "Positions", "Application Deadline", "Country", "Type of Contract"
    ])
    country = _extract_labeled_value(detail, "Country", [
        "Type of Contract", "Job Status", "Hours Per Week", "Offer Starting Date", "Is the job funded", "Reference Number", "Offer Description"
    ])
    if company:
        job["company"] = company
    if country:
        job["location"] = country


def _query_relevant(job: dict, query: str) -> bool:
    text = _norm(f"{job.get('title','')} {job.get('description','')} {job.get('full_detail','')}")
    pats = QUERY_EXPANSIONS.get(query.lower())
    if pats:
        return any(re.search(p, text, re.I) for p in pats)
    # Conservative generic fallback: all meaningful query tokens must appear.
    tokens = [t for t in _norm(query).split() if len(t) >= 4]
    return bool(tokens) and all(re.search(rf"\b{re.escape(t)}\b", text, re.I) for t in tokens)


def _is_spain(job: dict) -> bool:
    text = _norm(f"{job.get('location','')} {job.get('description','')} {job.get('full_detail','')}")
    return bool(re.search(r"\bspain\b|\bespana\b", text, re.I))


def _page_params(page: int, use_spain_facet: bool) -> dict[str, str]:
    params: dict[str, str] = {"page": str(page)}
    if use_spain_facet:
        params["f[0]"] = SPAIN_FACET_VALUE
    return params


def _fetch_mode(
    base: str,
    pages: int,
    timeout: tuple[int, int],
    use_spain_facet: bool,
    *,
    cutoff_date: date | None = None,
    request_delay: float = 0.0,
) -> tuple[list[dict], dict]:
    """Fetch public result pages and locally validate country metadata.

    When ``cutoff_date`` is provided, page traversal stops once a complete dated page
    is older than the requested historical window. Cards older than the cutoff are
    excluded. Undated cards are retained rather than silently dropped.
    """
    session = make_retry_session(total_retries=4, backoff_factor=1.25)
    search_url = f"{base}/jobs/search"
    all_cards: dict[str, dict] = {}
    page_errors: list[str] = []
    pages_fetched = 0
    parsed_total = 0
    dated_cards_seen = 0
    undated_cards_seen = 0
    newest_seen: date | None = None
    oldest_seen: date | None = None
    stop_reason = "page_limit"
    page_fingerprints: set[tuple[str, ...]] = set()
    pagination_repeat_detected = False
    repeated_pages: list[int] = []

    try:
        for page in range(max(1, pages)):
            try:
                r = session.get(
                    search_url,
                    params=_page_params(page, use_spain_facet),
                    timeout=timeout,
                    allow_redirects=True,
                )
                r.raise_for_status()
                page_jobs = parse_search_html(r.text)
                pages_fetched += 1
                if not page_jobs:
                    # A later empty page means we likely reached the end; an empty first
                    # page is still recorded so another base/mode can be attempted.
                    if page > 0:
                        break
                    continue

                # A transient EURAXESS/CDN regression can return page 1 repeatedly for
                # different ?page=N URLs. Count transport as fetched, but do not count or
                # trust duplicate card pages as coverage.
                fingerprint = tuple(sorted(
                    str(job.get("id") or job.get("url") or "")
                    for job in page_jobs
                    if job.get("id") or job.get("url")
                ))
                if fingerprint and fingerprint in page_fingerprints:
                    pagination_repeat_detected = True
                    repeated_pages.append(page)
                    stop_reason = "pagination_repeat"
                    break
                if fingerprint:
                    page_fingerprints.add(fingerprint)

                parsed_total += len(page_jobs)
                page_dates: list[date] = []
                for job in page_jobs:
                    posted = _parse_posted_date(job.get("date"))
                    if posted is None:
                        undated_cards_seen += 1
                    else:
                        dated_cards_seen += 1
                        page_dates.append(posted)
                        newest_seen = posted if newest_seen is None or posted > newest_seen else newest_seen
                        oldest_seen = posted if oldest_seen is None or posted < oldest_seen else oldest_seen

                    # Historical mode filters out dated cards older than the cutoff.
                    # Undated cards are kept so the audit can expose them.
                    if cutoff_date is not None and posted is not None and posted < cutoff_date:
                        continue
                    key = job.get("url") or f"{job.get('title','')}::{job.get('company','')}"
                    all_cards.setdefault(key, job)

                # EURAXESS newest-jobs pages are reverse chronological. Once an entire
                # parsed page is older than cutoff, later pages cannot add in-window jobs.
                if cutoff_date is not None and page_dates and max(page_dates) < cutoff_date:
                    stop_reason = "cutoff_reached"
                    break

                # Historical calibration deliberately paces requests so a long backfill
                # is less likely to trip transient rate limiting. Normal/live mode keeps
                # the old fast behavior because request_delay defaults to zero.
                if request_delay > 0 and page < max(1, pages) - 1:
                    time.sleep(request_delay)
            except Exception as exc:
                page_errors.append(f"page {page}: {type(exc).__name__}: {exc}")
                # Do not skip a failed page during historical calibration: doing so would
                # create an invisible hole in the backfill. Retry happens inside the
                # session; if it still fails, stop and report incomplete coverage.
                stop_reason = "first_page_error" if page == 0 else "page_fetch_error"
                break
    finally:
        session.close()

    cards = list(all_cards.values())
    spain_cards = [j for j in cards if _is_spain(j)]
    ratio = (len(spain_cards) / len(cards)) if cards else 0.0
    # The Spain facet is advisory only. If it returns mostly non-Spain cards,
    # treat it as not honored and force the generic-feed fallback.
    facet_honored = (
        not use_spain_facet
        or parsed_total == 0
        or ratio >= 0.75
    )

    if cutoff_date is None:
        coverage_complete = (
            not page_errors
            and not pagination_repeat_detected
            and facet_honored
            and stop_reason in {"page_limit", "cutoff_reached"}
        )
    else:
        historical_window_reached = (
            stop_reason == "cutoff_reached"
            or (oldest_seen is not None and oldest_seen <= cutoff_date)
        )
        coverage_complete = (
            historical_window_reached
            and not page_errors
            and not pagination_repeat_detected
            and facet_honored
        )

    coverage_warning = ""
    if not coverage_complete:
        reasons: list[str] = []
        if page_errors:
            reasons.append(f"page_errors={len(page_errors)}")
        if pagination_repeat_detected:
            reasons.append(f"pagination_repeat_pages={repeated_pages}")
        if use_spain_facet and not facet_honored:
            reasons.append(f"spain_facet_not_honored ratio={ratio:.3f}")
        if cutoff_date is not None and not (
            stop_reason == "cutoff_reached"
            or (oldest_seen is not None and oldest_seen <= cutoff_date)
        ):
            reasons.append(
                f"cutoff_not_reached cutoff={cutoff_date.isoformat()} "
                f"oldest_seen={oldest_seen.isoformat() if oldest_seen else 'unknown'}"
            )
        coverage_warning = "EURAXESS coverage incomplete: " + (
            "; ".join(reasons) if reasons else f"stop_reason={stop_reason}"
        )
    return spain_cards, {
        "base": base,
        "mode": "official_spain_facet" if use_spain_facet else "generic_feed_local_spain_filter",
        "pages_requested": max(1, pages),
        "pages_fetched": pages_fetched,
        "parsed_cards": parsed_total,
        "unique_cards": len(cards),
        "spain_cards": len(spain_cards),
        "spain_ratio": round(ratio, 3),
        "page_errors": page_errors,
        "cutoff_date": cutoff_date.isoformat() if cutoff_date else None,
        "newest_seen_date": newest_seen.isoformat() if newest_seen else None,
        "oldest_seen_date": oldest_seen.isoformat() if oldest_seen else None,
        "dated_cards_seen": dated_cards_seen,
        "undated_cards_seen": undated_cards_seen,
        "stop_reason": stop_reason,
        "pagination_repeat_detected": pagination_repeat_detected,
        "repeated_pages": repeated_pages,
        "facet_honored": facet_honored,
        "coverage_complete": coverage_complete,
        "coverage_warning": coverage_warning,
    }


def _get_spain_feed(
    pages: int, timeout: tuple[int, int], *, cutoff_date: date | None = None
) -> tuple[list[dict], dict, bool]:
    """Get a locally country-validated Spain feed, preferring the official Spain facet.

    The server-side facet is not blindly trusted. Even when the facet URL responds,
    every parsed card is checked locally for Spain before it can proceed.
    """
    cache_key = (max(1, pages), repr(timeout), cutoff_date.isoformat() if cutoff_date else "")
    if cache_key in _FEED_CACHE:
        cards, diag = _FEED_CACHE[cache_key]
        return deepcopy(cards), deepcopy(diag), True

    # Historical calibration is reproducibility-oriented. Persist the fetched Spain
    # feed so a second pass can resume detail retrieval without hammering the search
    # endpoint again. Live mode remains uncached on disk.
    if cutoff_date is not None:
        disk_path = _feed_disk_path(pages, cutoff_date)
        cached = _load_json(disk_path, None)
        if isinstance(cached, dict) and isinstance(cached.get("cards"), list) and isinstance(cached.get("diag"), dict):
            cards = cached["cards"]
            diag = cached["diag"]
            _FEED_CACHE[cache_key] = (deepcopy(cards), deepcopy(diag))
            return deepcopy(cards), deepcopy(diag), True

    attempts: list[dict] = []
    best_cards: list[dict] = []
    best_diag: dict = {}

    # First try the official Spain facet on the Spain site and the shared EC site.
    for base in SEARCH_BASES:
        cards, diag = _fetch_mode(base, pages, timeout, use_spain_facet=True, cutoff_date=cutoff_date, request_delay=0.8 if cutoff_date else 0.0)
        attempts.append(diag)
        # A high Spain ratio strongly suggests the facet is being honored.
        if cards and diag["spain_ratio"] >= 0.75:
            best_cards, best_diag = cards, diag
            break
        if len(cards) > len(best_cards):
            best_cards, best_diag = cards, diag

    # If the facet was blocked/ignored or yielded no Spain cards, fall back to a
    # generic public feed and apply the Spain filter locally. This sacrifices coverage
    # but avoids silently returning irrelevant countries.
    if not best_cards or best_diag.get("spain_ratio", 0) < 0.75 or not best_diag.get("coverage_complete", False):
        for base in ["https://euraxess.ec.europa.eu", "https://www.euraxess.es"]:
            cards, diag = _fetch_mode(
                base, pages, timeout, use_spain_facet=False,
                cutoff_date=cutoff_date, request_delay=0.8 if cutoff_date else 0.0
            )
            attempts.append(diag)

            # Prefer complete generic coverage. If every attempt is partial, retain
            # the one with the most locally validated Spain cards, then more unique
            # cards, so recall is preserved without claiming full coverage.
            current_key = (
                1 if best_diag.get("coverage_complete", False) else 0,
                len(best_cards),
                int(best_diag.get("unique_cards", 0) or 0),
            )
            candidate_key = (
                1 if diag.get("coverage_complete", False) else 0,
                len(cards),
                int(diag.get("unique_cards", 0) or 0),
            )
            if candidate_key > current_key:
                best_cards, best_diag = cards, diag
            if cards and diag.get("coverage_complete", False):
                break

    # A legitimately empty Spain result is not a transport failure. If at least
    # one attempt fetched pages, retain the strongest attempt diagnostics even when
    # it yielded zero Spain cards. Reserve mode=failed for total feed inaccessibility.
    if not best_diag:
        fetched_attempts = [a for a in attempts if int(a.get("pages_fetched", 0) or 0) > 0]
        if fetched_attempts:
            best_diag = max(
                fetched_attempts,
                key=lambda a: (
                    1 if a.get("coverage_complete", False) else 0,
                    1 if a.get("mode") == "generic_feed_local_spain_filter" else 0,
                    int(a.get("unique_cards", 0) or 0),
                    int(a.get("pages_fetched", 0) or 0),
                    int(a.get("parsed_cards", 0) or 0),
                ),
            )

    if not best_diag:
        best_diag = {
            "base": "",
            "mode": "failed",
            "pages_requested": max(1, pages),
            "pages_fetched": 0,
            "parsed_cards": 0,
            "unique_cards": 0,
            "spain_cards": 0,
            "spain_ratio": 0.0,
            "page_errors": [],
            "coverage_complete": False,
            "coverage_warning": "EURAXESS feed collection failed",
        }

    best_diag = {**best_diag, "attempts": attempts}
    _FEED_CACHE[cache_key] = (deepcopy(best_cards), deepcopy(best_diag))
    if cutoff_date is not None and best_diag.get("coverage_complete", False):
        _save_json(_feed_disk_path(pages, cutoff_date), {"cards": best_cards, "diag": best_diag})
    return deepcopy(best_cards), deepcopy(best_diag), False


def _valid_euraxess_detail(detail: str) -> bool:
    """Reject portal/search pages masquerading as a successful job-detail fetch."""
    t = _norm(detail)
    if not t:
        return False
    if "filter by search results" in t and "showing results" in t:
        return False
    # EURAXESS job-detail pages expose both the Job Information block and country.
    # A generic search/index page does not.
    return "job information" in t and bool(re.search(r"\bcountry\s+spain\b", t, re.I))


def collect(
    query: str = "taxonomy_scan",
    country: str = "Spain",
    timeout: int | tuple[int, int] = (10, 45),
    enrich_detail: bool = True,
    pages: int = DEFAULT_PAGES,
    diagnostics: dict | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    audit_rows: list[dict] | None = None,
    history_days: int | None = None,
    as_of: str | date | None = None,
    detail_request_delay: float | None = None,
) -> list[dict]:
    """Collect Spain-based EURAXESS jobs using taxonomy triage.

    V1.8 uses the reliable Spain feed as discovery and performs a high-recall card-level
    role/domain triage before fetching details. It does not require exact phrases such as
    'exercise physiology' to be present on the search card. Full-JD scoring remains the
    final precision gate.

    V1.10 adds an optional historical calibration window. This changes collection
    coverage only; the V1.9 scoring engine is intentionally frozen.
    """
    del country
    timeout_tuple = timeout if isinstance(timeout, tuple) else (10, int(timeout))
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    resolved_as_of = _resolve_as_of(as_of)
    cutoff = _history_cutoff(history_days, resolved_as_of) if history_days else None
    diag.update({
        "source": "EURAXESS",
        "mode": "taxonomy_scan",
        "query_tag": query,
        "history_days": int(history_days) if history_days else None,
        "as_of": resolved_as_of.isoformat() if history_days else None,
        "cutoff_date": cutoff.isoformat() if cutoff else None,
    })

    if cutoff is None:
        # Preserve the pre-V1.10 call shape in normal/live mode. This also keeps
        # older tests and integrations compatible while historical mode stays opt-in.
        cards, feed_diag, cache_hit = _get_spain_feed(pages=pages, timeout=timeout_tuple)
    else:
        cards, feed_diag, cache_hit = _get_spain_feed(
            pages=pages, timeout=timeout_tuple, cutoff_date=cutoff
        )
    diag["feed_cache_hit"] = cache_hit
    diag["feed"] = feed_diag
    diag["spain_feed_cards"] = len(cards)

    candidates = []
    rejected = 0
    reason_counts: dict[str, int] = {}
    local_audit = []
    for card in cards:
        j = dict(card)
        j["search_query"] = query
        keep, reasons = _card_candidate(j)
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        local_audit.append({
            "source": "EURAXESS",
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "location": j.get("location", ""),
            "date": j.get("date", ""),
            "url": j.get("url", ""),
            "card_candidate": keep,
            "card_reasons": "; ".join(reasons),
        })
        if keep:
            candidates.append(j)
        else:
            rejected += 1

    # Stable priority: cards with both a role and domain signal first, then domain, then role.
    def priority(job: dict) -> tuple[int, str]:
        keep, reasons = _card_candidate(job)
        del keep
        both = "target_or_transferable_role_title" in reasons and "target_or_adjacent_domain_on_card" in reasons
        domain = "target_or_adjacent_domain_on_card" in reasons
        return (0 if both else 1 if domain else 2, _norm(job.get("title", "")))

    candidates.sort(key=priority)
    candidate_count_before_limit = len(candidates)
    if max_candidates >= 0:
        candidates = candidates[:max_candidates]
    candidate_truncated = max(0, candidate_count_before_limit - len(candidates))

    if audit_rows is not None:
        audit_rows.extend(local_audit)

    # Legacy diagnostic name retained so older tooling/tests remain readable.
    diag["query_card_matches"] = len(candidates)
    diag["card_candidates"] = len(candidates)
    diag["card_candidates_before_limit"] = candidate_count_before_limit
    diag["candidate_truncated"] = candidate_truncated
    diag["max_candidates"] = max_candidates
    diag["card_rejected"] = rejected
    diag["candidate_reason_counts"] = reason_counts

    detail_attempts = 0
    detail_cache_hits = 0
    detail_persistent_cache_hits = 0
    detail_network_requests = 0
    detail_success = 0
    detail_failed = 0
    detail_mismatch = 0
    detail_deferred = 0
    rate_limited = False

    # Historical backfills generate many more requests than daily operation. Pace
    # detail requests by default and persist every resolved page immediately. This
    # lets a rerun resume rather than refetching successful JDs.
    if detail_request_delay is None:
        detail_request_delay = 2.5 if cutoff is not None else 0.0
    persistent_detail_cache = _load_json(DETAIL_CACHE_PATH, {})
    if not isinstance(persistent_detail_cache, dict):
        persistent_detail_cache = {}

    if enrich_detail:
        session = make_retry_session(total_retries=3, backoff_factor=1.5)
        try:
            for idx, job in enumerate(candidates):
                url = job.get("url", "")
                detail_attempts += 1
                detail = ""
                status = ""
                if url in _DETAIL_CACHE:
                    detail, status = _DETAIL_CACHE[url]
                    detail_cache_hits += 1
                elif url in persistent_detail_cache:
                    entry = persistent_detail_cache.get(url) or {}
                    if isinstance(entry, dict):
                        detail = str(entry.get("detail") or "")
                        status = str(entry.get("status") or "")
                    detail_persistent_cache_hits += 1
                    _DETAIL_CACHE[url] = (detail, status)
                elif rate_limited:
                    status = "DEFERRED_RATE_LIMIT"
                    detail_deferred += 1
                else:
                    detail, status = fetch_url_text(
                        url, timeout=timeout_tuple, title_hint=job.get("title", ""), session=session
                    )
                    detail_network_requests += 1

                    # If the shared endpoint returns a portal/search page, try the
                    # Spain-domain equivalent once before giving up on the detail.
                    if detail and status in {"OK_HTML", "OK_PDF", "OK", "CACHE"} and not _valid_euraxess_detail(detail):
                        alt = re.sub(r"^https://euraxess\.ec\.europa\.eu", "https://www.euraxess.es", url)
                        if alt != url:
                            alt_detail, alt_status = fetch_url_text(
                                alt, timeout=timeout_tuple, title_hint=job.get("title", ""), session=session
                            )
                            detail_network_requests += 1
                            if alt_detail and alt_status in {"OK_HTML", "OK_PDF", "OK", "CACHE"} and _valid_euraxess_detail(alt_detail):
                                detail, status = alt_detail, alt_status

                    if _is_rate_limited_status(status):
                        # Do not keep firing dozens of requests after a persistent 429.
                        # Save progress and defer the rest to the next run.
                        rate_limited = True
                    elif detail and status in {"OK_HTML", "OK_PDF", "OK", "CACHE"}:
                        persistent_detail_cache[url] = {"detail": detail, "status": status}
                        _save_json(DETAIL_CACHE_PATH, persistent_detail_cache)
                    elif status == "DETAIL_MISMATCH":
                        persistent_detail_cache[url] = {"detail": "", "status": status}
                        _save_json(DETAIL_CACHE_PATH, persistent_detail_cache)

                    if detail_request_delay and not rate_limited and idx < len(candidates) - 1:
                        time.sleep(max(0.0, float(detail_request_delay)))

                if detail and status in {"OK_HTML", "OK_PDF", "OK", "CACHE"} and not _valid_euraxess_detail(detail):
                    detail = ""
                    status = "DETAIL_MISMATCH"

                if detail:
                    job["full_detail"] = detail
                    _enrich_from_detail(job, detail)
                job["detail_status"] = status
                if detail and status in {"OK_HTML", "OK_PDF", "OK", "CACHE"}:
                    detail_success += 1
                else:
                    detail_failed += 1
                    if status == "DETAIL_MISMATCH":
                        detail_mismatch += 1
        finally:
            session.close()

    # Country remains a hard collection constraint. Relevance is decided by the full
    # deterministic evaluator, not by an exact query phrase.
    kept = [j for j in candidates if _is_spain(j)]

    diag.update({
        "detail_attempts": detail_attempts,
        "detail_cache_hits": detail_cache_hits,
        "detail_persistent_cache_hits": detail_persistent_cache_hits,
        "detail_network_requests": detail_network_requests,
        "detail_success": detail_success,
        "detail_failed": detail_failed,
        "detail_mismatch": detail_mismatch,
        "detail_deferred": detail_deferred,
        "detail_rate_limited": rate_limited,
        "detail_resolution_rate": round(detail_success / len(candidates), 4) if candidates else 1.0,
        "detail_resolution_complete": detail_failed == 0,
        "post_detail_spain": len(kept),
        "kept": len(kept),
    })

    attempts = feed_diag.get("attempts", [])
    parsed_any = any(int(a.get("parsed_cards", 0)) > 0 for a in attempts)
    fetched_any = any(int(a.get("pages_fetched", 0)) > 0 for a in attempts)
    if not parsed_any and not fetched_any:
        errors = []
        for a in attempts:
            errors.extend(a.get("page_errors", []))
        raise RuntimeError("EURAXESS feed inaccessible: " + ("; ".join(errors) if errors else "no pages fetched"))

    return kept
