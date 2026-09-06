from __future__ import annotations
from io import BytesIO
import re
import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
from pypdf import PdfReader
from urllib3.util.retry import Retry
from urllib.parse import urljoin, urlparse


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def make_retry_session(total_retries: int = 3, backoff_factor: float = 1.0) -> requests.Session:
    """Create a requests Session that retries only transient HTTP/network failures.

    This does not bypass access controls. It is only intended to make public-source
    collection less brittle when a site briefly times out or returns a 429/5xx.
    """
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
        respect_retry_after_header=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(DEFAULT_HEADERS)
    return session


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()




COMMON_TITLE_TOKENS = {
    "postdoc", "postdoctoral", "research", "researcher", "position", "positions",
    "fellow", "assistant", "technician", "technical", "junior", "senior",
    "manager", "coordinator", "laboratory", "lab", "project", "group", "officer",
    "scientist", "science", "study", "head", "lead", "leading", "role", "job",
}

GENERIC_JOB_INDEX_MARKERS = (
    "job opportunities",
    "applications are always welcome",
    "submit a general application",
    "external jobs",
    "currently hiring:",
    "create an account",
    "forgot password",
)

ATTACHMENT_SHELL_MARKERS = (
    "documento adjunto",
    "document adjunt",
    "attached document",
    "bases y requisitos",
    "bases i requisits",
    "descarregar",
    "download is available",
    "mida del fitxer",
    "file size",
    "recompte de fitxers",
)

NEGATIVE_ATTACHMENT_MARKERS = (
    "privacy", "privacitat", "privacidad", "cookie", "legal", "proteccion de datos",
    "protecció de dades", "data protection", "equal opportunities", "equality",
)


def _title_tokens(title: str) -> list[str]:
    text = _clean(title).lower()
    toks = re.findall(r"[a-z0-9À-ÿ]+", text)
    return [t for t in toks if len(t) >= 4 and t not in COMMON_TITLE_TOKENS]


def _looks_like_generic_job_index(text: str) -> bool:
    low = _clean(text).lower()
    return any(m in low for m in GENERIC_JOB_INDEX_MARKERS)


def _looks_like_attachment_shell(text: str) -> bool:
    low = _clean(text).lower()
    return any(m in low for m in ATTACHMENT_SHELL_MARKERS)


def _detail_matches_title(title: str, text: str) -> bool:
    """Conservative content-integrity check for a fetched detail page.

    We only reject when evidence strongly suggests a generic job index/login page or a
    short page unrelated to a sufficiently specific title. Generic role titles such as
    "Laboratory Technician" are intentionally not rejected on token overlap alone.
    """
    clean = _clean(text)
    if not clean:
        return False
    toks = _title_tokens(title)
    if not toks:
        return len(clean) >= 400 or not _looks_like_generic_job_index(clean)
    low = clean.lower()
    matched = sum(1 for t in toks if t in low)
    ratio = matched / len(toks)
    if _looks_like_generic_job_index(clean) and ratio < 0.50:
        return False
    if len(clean) < 700 and len(toks) >= 2 and ratio < 0.40:
        return False
    return True


def _attachment_links(html: str, base_url: str, title_hint: str = "") -> list[str]:
    """Return likely job-description PDF/document links, best candidate first."""
    soup = BeautifulSoup(html, "html.parser")
    title_tokens = set(_title_tokens(title_hint))
    scored = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href", ""))
        label = _clean(a.get_text(" ", strip=True))
        combined = f"{label} {href}".lower()
        if not href or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        if any(x in combined for x in NEGATIVE_ATTACHMENT_MARKERS):
            continue
        is_pdf = ".pdf" in urlparse(href).path.lower()
        cue = any(x in combined for x in ("download", "descarregar", "descargar", "oferta", "offer", "convoc", "bases", "requisit", "annex", "anexo"))
        if not (is_pdf or cue):
            continue
        score = 4 if is_pdf else 0
        score += 2 if cue else 0
        score += sum(1 for t in title_tokens if t in combined)
        # Same-host attachments are preferred, but cross-host CDN links remain allowed.
        try:
            if urlparse(href).netloc == urlparse(base_url).netloc:
                score += 1
        except Exception:
            pass
        scored.append((score, href))
    scored.sort(key=lambda x: (-x[0], x[1]))
    seen=[]
    for _, href in scored:
        if href not in seen:
            seen.append(href)
    return seen


def _extract_html_text(html: str, title_hint: str = "") -> str:
    """Extract the job body while discarding common site-wide navigation noise.

    Job pages frequently include menus, related jobs, footer links and internship links.
    Those strings must not be treated as requirements of the current vacancy.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "aside"]):
        tag.decompose()

    # Prefer the semantic job body when available.
    root = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body or soup

    # If the title can be found, prefer the closest reasonably-sized container around it.
    # This is useful on sites where <main> also contains large job/filter indexes.
    if title_hint:
        target_norm = _clean(title_hint).lower()
        candidate = None
        for tag in root.find_all(["h1", "h2", "h3", "div", "section"]):
            txt = _clean(tag.get_text(" ", strip=True))
            if not txt or target_norm not in txt.lower():
                continue
            parent = tag
            for _ in range(5):
                block = _clean(parent.get_text(" ", strip=True))
                if 500 <= len(block) <= 30000:
                    candidate = parent
                    break
                if parent.parent is None:
                    break
                parent = parent.parent
            if candidate is not None:
                break
        if candidate is not None:
            root = candidate

    # Forms/buttons can inject unrelated application UI text.
    for tag in root.find_all(["form", "button"]):
        tag.decompose()

    return _clean(root.get_text(" ", strip=True))


def fetch_url_text(
    url: str,
    timeout: int | tuple[int, int] = (10, 45),
    max_chars: int = 50000,
    title_hint: str = "",
    session: requests.Session | None = None,
    follow_job_attachments: bool = True,
) -> tuple[str, str]:
    """Fetch a public job-detail URL and return plain text plus status.

    Supports HTML and PDF. For thin HTML shells that point to an attached vacancy PDF,
    the best job-like attachment is followed once. Generic job indexes/login pages are
    rejected as DETAIL_MISMATCH rather than being scored as if they were a full JD.
    """
    if not url:
        return "", "NO_URL"

    own_session = session is None
    s = session or make_retry_session()
    try:
        try:
            r = s.get(url, timeout=timeout, allow_redirects=True)
            r.raise_for_status()
        except Exception as exc:
            return "", f"FETCH_FAILED: {exc}"

        ctype = (r.headers.get("content-type") or "").lower()
        try:
            content_disposition = (r.headers.get("content-disposition") or "").lower()
            is_pdf_bytes = bytes(r.content[:5]) == b"%PDF-"
            is_pdf_download = (
                "pdf" in ctype
                or r.url.lower().endswith(".pdf")
                or ".pdf" in content_disposition
                or is_pdf_bytes
            )
            if is_pdf_download:
                reader = PdfReader(BytesIO(r.content))
                text = _clean("\n".join((page.extract_text() or "") for page in reader.pages))[:max_chars]
                if not text:
                    return "", "EMPTY_DETAIL"
                if title_hint and not _detail_matches_title(title_hint, text):
                    return "", "DETAIL_MISMATCH"
                return text, "OK_PDF"

            text = _extract_html_text(r.text, title_hint=title_hint)[:max_chars]

            # Some institutions publish only a short landing page and keep the actual
            # vacancy requirements in an attached PDF. Follow the best likely attachment.
            if follow_job_attachments and (_looks_like_attachment_shell(text) or len(text) < 700):
                for attachment_url in _attachment_links(r.text, r.url, title_hint=title_hint)[:3]:
                    if attachment_url == r.url:
                        continue
                    attachment_text, attachment_status = fetch_url_text(
                        attachment_url,
                        timeout=timeout,
                        max_chars=max_chars,
                        title_hint=title_hint,
                        session=s,
                        follow_job_attachments=False,
                    )
                    if attachment_text and attachment_status in {"OK_PDF", "OK_HTML", "OK"}:
                        return attachment_text, "OK_PDF_ATTACHMENT" if attachment_status == "OK_PDF" else "OK_ATTACHMENT"

            if not text:
                return "", "EMPTY_DETAIL"
            if title_hint and not _detail_matches_title(title_hint, text):
                return "", "DETAIL_MISMATCH"
            if _looks_like_attachment_shell(text) and len(text) < 1200:
                return "", "ATTACHMENT_UNRESOLVED"
            return text, "OK_HTML"
        except Exception as exc:
            return "", f"PARSE_FAILED: {exc}"
    finally:
        if own_session:
            try:
                s.close()
            except Exception:
                pass

