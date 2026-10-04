from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import time
from typing import Callable, Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

SEARCH_PATH = '/jobs/search'


def _clean(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _next_listing_url(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html or '', 'html.parser')
    base = urlparse(base_url)
    listing_path = (base.path or SEARCH_PATH).rstrip('/') or '/'
    preferred: list[str] = []
    fallback: list[str] = []
    for a in soup.find_all('a', href=True):
        label = ' '.join([
            a.get_text(' ', strip=True), str(a.get('aria-label') or ''), str(a.get('title') or '')
        ]).strip().lower()
        rel = a.get('rel') or []
        if 'next' not in rel and not re.search(r'\b(next|more jobs|suivant|suivante|volgende|weiter|nächste)\b|^[›»>]$', label):
            continue
        if a.get('aria-disabled') == 'true' or 'disabled' in (a.get('class') or []):
            continue
        href = str(a['href'])
        if href.startswith(('#', 'javascript:')):
            continue
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.netloc != base.netloc:
            continue
        candidate_path = (parsed.path or '/').rstrip('/') or '/'
        if candidate_path == listing_path:
            preferred.append(url)
        else:
            fallback.append(url)
    return preferred[0] if preferred else (fallback[0] if fallback else None)


def _discover_facets(html: str) -> tuple[str | None, str | None, str | None]:
    soup = BeautifulSoup(html or '', 'html.parser')
    country_select = soup.select_one('select[name="job_country[]"]')
    offer_select = soup.select_one('select[name="offer_type[]"]')
    spain = None
    offer = None
    if country_select:
        for option in country_select.find_all('option'):
            label = _clean(option.get_text(' ', strip=True)).lower()
            value = _clean(option.get('value'))
            if label in {'spain', 'españa', 'espana'} and value:
                spain = value if value.startswith('job_country:') else f'job_country:{value}'
                break
    if offer_select:
        for option in offer_select.find_all('option'):
            label = _clean(option.get_text(' ', strip=True)).lower()
            value = _clean(option.get('value'))
            if value and ('job' in label or 'job' in value.lower()):
                offer = value if value.startswith('offer_type:') else f'offer_type:{value}'
                break
    form = country_select.find_parent('form') if country_select else None
    action = str(form.get('action') or '') if form else ''
    return spain, offer, action or None


def _selected_values(html: str, select_name: str) -> set[str]:
    soup = BeautifulSoup(html or '', 'html.parser')
    select = soup.select_one(f'select[name="{select_name}"]')
    if select is None:
        return set()
    return {
        _clean(option.get('value'))
        for option in select.find_all('option')
        if option.has_attr('selected') and _clean(option.get('value'))
    }


def _facet_active(html: str, country_facet: str, offer_facet: str) -> bool:
    countries = _selected_values(html, 'job_country[]')
    offers = _selected_values(html, 'offer_type[]')
    country_value = country_facet.split(':', 1)[-1]
    offer_value = offer_facet.split(':', 1)[-1]
    return (
        (country_facet in countries or country_value in countries)
        and (offer_facet in offers or offer_value in offers)
    )


def _retry_after_seconds(response: Any, attempt: int, *, base: float, cap: float, minimum: float) -> float:
    exponential = min(max(0.0, base) * (2.0 ** attempt), max(0.0, cap))
    floor = max(0.0, minimum, exponential)
    raw = _clean((getattr(response, 'headers', {}) or {}).get('Retry-After'))
    if raw:
        try:
            return min(max(floor, float(raw)), cap)
        except ValueError:
            try:
                target = parsedate_to_datetime(raw)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                delta = max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
                return min(max(floor, delta), cap)
            except (TypeError, ValueError, OverflowError):
                pass
    return floor


def _request(session, method: str, url: str, *, timeout, params=None, attempts: int = 5,
             pace_seconds: float = 0.0, backoff_base: float = 5.0,
             backoff_cap: float = 60.0, minimum_backoff: float = 0.0):
    call = getattr(session, 'post', session.get) if method.upper() == 'POST' else session.get
    last = None
    for attempt in range(max(1, attempts)):
        if pace_seconds > 0:
            time.sleep(pace_seconds)
        kwargs = {'timeout': timeout, 'allow_redirects': True}
        if params is not None:
            kwargs['params'] = params
        response = call(url, **kwargs)
        last = response
        status = int(getattr(response, 'status_code', 0) or 0)
        if status not in {429, 500, 502, 503, 504}:
            return response
        if attempt + 1 < attempts:
            time.sleep(_retry_after_seconds(
                response, attempt, base=backoff_base, cap=backoff_cap, minimum=minimum_backoff
            ))
    return last


def _increment_page(url: str) -> str | None:
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    found = False
    current = 0
    out = []
    for key, value in pairs:
        if key == 'page' and not found:
            try:
                current = int(value)
            except ValueError:
                return None
            out.append((key, str(current + 1)))
            found = True
        else:
            out.append((key, value))
    if not found:
        out.append(('page', '1'))
    return urlunparse(parsed._replace(query=urlencode(out, doseq=True)))


def _fingerprint(rows: list[dict]) -> tuple[str, ...]:
    return tuple(sorted(
        str(row.get('id') or row.get('url') or '')
        for row in rows if row.get('id') or row.get('url')
    ))


def fetch_spain_pages(*, base: str, pages: int, timeout: tuple[int, int], use_spain_facet: bool,
                      parse_search_html: Callable[[str], list[dict]], is_spain: Callable[[dict], bool],
                      parse_posted_date: Callable[[str | None], Any], cutoff_date=None,
                      request_delay: float = 0.0, make_session=None) -> tuple[list[dict], dict]:
    session = make_session(total_retries=0, backoff_factor=0) if make_session else None
    if session is None:
        raise RuntimeError('EURAXESS session factory unavailable')
    search_url = base.rstrip('/') + SEARCH_PATH
    all_cards: dict[str, dict] = {}
    page_errors: list[str] = []
    pages_fetched = 0
    parsed_total = 0
    dated_cards_seen = 0
    undated_cards_seen = 0
    newest_seen = None
    oldest_seen = None
    stop_reason = 'page_limit'
    pagination_repeat_detected = False
    repeated_pages: list[int] = []
    semantic_duplicate_retries = 0
    facet_honored = not use_spain_facet
    filter_transport = 'GLOBAL_GET_POST' if not use_spain_facet else 'GET_FACET'
    country_facet = None
    offer_facet = None
    current_url = search_url
    visited: set[str] = set()
    seen_fingerprints: set[tuple[str, ...]] = set()
    first_fingerprint: tuple[str, ...] = ()

    try:
        if use_spain_facet:
            first = _request(session, 'GET', search_url, timeout=timeout, attempts=5, pace_seconds=request_delay)
            first.raise_for_status()
            country_facet, offer_facet, action = _discover_facets(first.text)
            if not country_facet or not offer_facet:
                raise RuntimeError('EURAXESS live Spain/Job Offer facets unavailable')
            current_url = urljoin(first.url, action or SEARCH_PATH)
            params = [('f[0]', country_facet), ('f[1]', offer_facet)]
            response = _request(session, 'GET', current_url, timeout=timeout, params=params,
                                attempts=5, pace_seconds=request_delay)
            response.raise_for_status()
            if not _facet_active(response.text, country_facet, offer_facet):
                raise RuntimeError('EURAXESS returned HTTP 200 but Spain/Job Offer facets were inactive')
            facet_honored = True
            current_url = response.url
            seeded_response = response
        else:
            seeded_response = None

        for page in range(max(1, pages)):
            try:
                if seeded_response is not None:
                    response = seeded_response
                    seeded_response = None
                else:
                    if current_url in visited:
                        advanced = _increment_page(current_url)
                        if advanced and advanced not in visited:
                            current_url = advanced
                        else:
                            stop_reason = 'repeated_page_url'
                            pagination_repeat_detected = True
                            repeated_pages.append(page)
                            break
                    method = 'GET' if use_spain_facet or page == 0 else 'POST'
                    response = _request(
                        session, method, current_url, timeout=timeout,
                        attempts=8 if not use_spain_facet else 5,
                        pace_seconds=max(request_delay, 2.5) if not use_spain_facet else request_delay,
                        backoff_base=15.0 if not use_spain_facet else 5.0,
                        backoff_cap=180.0 if not use_spain_facet else 60.0,
                        minimum_backoff=15.0 if not use_spain_facet else 0.0,
                    )
                    response.raise_for_status()

                visited.add(current_url)
                rows = parse_search_html(response.text)
                pages_fetched += 1
                next_url = _next_listing_url(response.text, getattr(response, 'url', current_url))

                if not rows and not use_spain_facet and page > 0:
                    probe = _request(
                        session, 'GET', current_url, timeout=timeout, attempts=4,
                        pace_seconds=max(request_delay, 2.5), backoff_base=15.0,
                        backoff_cap=180.0, minimum_backoff=15.0,
                    )
                    probe.raise_for_status()
                    probe_rows = parse_search_html(probe.text)
                    if probe_rows:
                        response = probe
                        rows = probe_rows
                        next_url = _next_listing_url(probe.text, getattr(probe, 'url', current_url))
                if not rows:
                    stop_reason = 'empty_page'
                    break

                fp = _fingerprint(rows)
                if not first_fingerprint:
                    first_fingerprint = fp
                if fp and fp in seen_fingerprints:
                    recovered = False
                    original_fp = fp
                    for retry_index in range(2):
                        semantic_duplicate_retries += 1
                        if request_delay > 0 or not use_spain_facet:
                            time.sleep(5.0 * (retry_index + 1))
                        method = 'GET' if use_spain_facet or page == 0 else 'POST'
                        retry = _request(
                            session, method, current_url, timeout=timeout, attempts=4,
                            pace_seconds=max(request_delay, 2.5) if not use_spain_facet else request_delay,
                            backoff_base=15.0, backoff_cap=180.0, minimum_backoff=15.0,
                        )
                        retry.raise_for_status()
                        retry_rows = parse_search_html(retry.text)
                        retry_fp = _fingerprint(retry_rows)
                        if retry_fp and retry_fp not in seen_fingerprints:
                            response = retry
                            rows = retry_rows
                            fp = retry_fp
                            next_url = _next_listing_url(retry.text, getattr(retry, 'url', current_url))
                            recovered = True
                            break
                    if not recovered:
                        if page >= 2 and original_fp == first_fingerprint:
                            stop_reason = 'last_page_reset'
                            break
                        pagination_repeat_detected = True
                        repeated_pages.append(page)
                        stop_reason = 'pagination_repeat'
                        break

                if fp:
                    seen_fingerprints.add(fp)
                parsed_total += len(rows)
                page_dates = []
                for job in rows:
                    posted = parse_posted_date(job.get('date'))
                    if posted is None:
                        undated_cards_seen += 1
                    else:
                        dated_cards_seen += 1
                        page_dates.append(posted)
                        newest_seen = posted if newest_seen is None or posted > newest_seen else newest_seen
                        oldest_seen = posted if oldest_seen is None or posted < oldest_seen else oldest_seen
                    if cutoff_date is not None and posted is not None and posted < cutoff_date:
                        continue
                    key = job.get('url') or f"{job.get('title','')}::{job.get('company','')}"
                    all_cards.setdefault(key, job)

                if cutoff_date is not None and page_dates and max(page_dates) < cutoff_date:
                    stop_reason = 'cutoff_reached'
                    break
                if not next_url:
                    stop_reason = 'last_page'
                    break
                if page + 1 >= max(1, pages):
                    stop_reason = 'page_limit'
                    break
                if next_url in visited:
                    advanced = _increment_page(getattr(response, 'url', current_url))
                    current_url = advanced or next_url
                else:
                    current_url = next_url
            except Exception as exc:
                page_errors.append(f'page {page}: {type(exc).__name__}: {exc}')
                stop_reason = 'first_page_error' if page == 0 else 'page_fetch_error'
                break
    except Exception as exc:
        page_errors.append(f'preflight: {type(exc).__name__}: {exc}')
        stop_reason = 'filter_validation_failed' if use_spain_facet else 'first_page_error'
    finally:
        session.close()

    cards = list(all_cards.values())
    spain_cards = [j for j in cards if is_spain(j)]
    ratio = (len(spain_cards) / len(cards)) if cards else 0.0
    if cutoff_date is None:
        coverage_complete = (
            not page_errors and not pagination_repeat_detected and facet_honored
            and stop_reason in {'page_limit', 'last_page', 'last_page_reset', 'empty_page'}
        )
    else:
        window_reached = stop_reason == 'cutoff_reached' or (oldest_seen is not None and oldest_seen <= cutoff_date)
        coverage_complete = window_reached and not page_errors and not pagination_repeat_detected and facet_honored

    reasons = []
    if page_errors:
        reasons.append(f'page_errors={len(page_errors)}')
    if pagination_repeat_detected:
        reasons.append(f'pagination_repeat_pages={repeated_pages}')
    if use_spain_facet and not facet_honored:
        reasons.append(f'spain_facet_not_honored ratio={ratio:.3f}')
    if cutoff_date is not None and not (stop_reason == 'cutoff_reached' or (oldest_seen is not None and oldest_seen <= cutoff_date)):
        reasons.append(f'cutoff_not_reached cutoff={cutoff_date.isoformat()} oldest_seen={oldest_seen.isoformat() if oldest_seen else "unknown"}')
    warning = '' if coverage_complete else 'EURAXESS coverage incomplete: ' + ('; '.join(reasons) if reasons else f'stop_reason={stop_reason}')

    return spain_cards, {
        'base': base,
        'mode': 'official_spain_facet' if use_spain_facet else 'generic_feed_local_spain_filter',
        'filter_transport': filter_transport,
        'country_facet': country_facet,
        'offer_type_facet': offer_facet,
        'pages_requested': max(1, pages),
        'pages_fetched': pages_fetched,
        'parsed_cards': parsed_total,
        'unique_cards': len(cards),
        'spain_cards': len(spain_cards),
        'spain_ratio': round(ratio, 3),
        'page_errors': page_errors,
        'cutoff_date': cutoff_date.isoformat() if cutoff_date else None,
        'newest_seen_date': newest_seen.isoformat() if newest_seen else None,
        'oldest_seen_date': oldest_seen.isoformat() if oldest_seen else None,
        'dated_cards_seen': dated_cards_seen,
        'undated_cards_seen': undated_cards_seen,
        'stop_reason': stop_reason,
        'pagination_repeat_detected': pagination_repeat_detected,
        'repeated_pages': repeated_pages,
        'semantic_duplicate_retries': semantic_duplicate_retries,
        'facet_honored': facet_honored,
        'coverage_complete': coverage_complete,
        'coverage_warning': warning,
    }


def fetch_detail_resilient(fetcher, url: str, *, timeout, title_hint: str, session,
                           pace_seconds: float = 3.0, attempts: int = 3):
    last_detail, last_status = '', ''
    requests_used = 0
    for attempt in range(max(1, attempts)):
        if pace_seconds > 0:
            time.sleep(pace_seconds)
        detail, status = fetcher(url, timeout=timeout, title_hint=title_hint, session=session)
        requests_used += 1
        last_detail, last_status = detail, status
        normalized = _clean(status).lower()
        if '429' not in normalized and 'too many requests' not in normalized:
            return detail, status, requests_used
        if attempt + 1 < attempts:
            time.sleep(min(90.0, max(30.0, 15.0 * (2.0 ** attempt))))
    return last_detail, last_status, requests_used