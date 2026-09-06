from __future__ import annotations

import argparse
import json
import re
import secrets
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from sources.fetch_detail import make_retry_session

ROOT = Path(__file__).resolve().parent
SPA_ROOT = "https://gestiona.comunidad.madrid/poem_webapp/"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _script_urls(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[str] = []
    for tag in soup.find_all("script", src=True):
        u = urljoin(base, tag.get("src", ""))
        if u and u not in out:
            out.append(u)
    return out


def _contexts(text: str, needle: str, before: int = 700, after: int = 900, limit: int = 8) -> list[str]:
    out: list[str] = []
    start = 0
    while len(out) < limit:
        pos = text.find(needle, start)
        if pos < 0:
            break
        out.append(_clean(text[max(0, pos-before): min(len(text), pos+len(needle)+after)]))
        start = pos + max(1, len(needle))
    return out


def _extract_api_bases(js: str) -> list[str]:
    """Collect likely POEM API bases without assuming the service split."""
    out: list[str] = []

    # Exact property literals when the build embeds API_URL directly.
    for m in re.finditer(r'API_URL\s*[:=]\s*(["\'])(https://[^"\']+)\1', js or ""):
        u = m.group(2).rstrip("/") + "/"
        if u not in out:
            out.append(u)

    # Public Comunidad de Madrid POEM-related gateways seen in current bundles.
    pats = [
        r'https://apiscm\.comunidad\.madrid/t/ciudadanos\.comunidad\.madrid/educacion/portal-empleo/v[0-9.]+/?',
        r'https://apiscm\.comunidad\.madrid/t/ciudadanos\.comunidad\.madrid/educacion/ofertas-portal-empleo/v[0-9.]+/?',
    ]
    for pat in pats:
        for u in re.findall(pat, js or ""):
            u = u.rstrip("/") + "/"
            if u not in out:
                out.append(u)
    return out


def _candidate_urls(bases: list[str], offer_id: str) -> list[str]:
    out: list[str] = []
    for base in bases:
        base = base.rstrip("/") + "/"
        for suffix in (f"ofertas/{offer_id}", offer_id):
            u = base + suffix
            if u not in out:
                out.append(u)
    return out


def _headers(profile: str) -> dict[str, str]:
    base = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://gestiona.comunidad.madrid",
        "Referer": SPA_ROOT,
        "User-Agent": "Mozilla/5.0",
    }
    if profile == "angular_anonymous":
        # Mirrors getHeaders() in the current POEM Angular service for anonymous users.
        base["x-trace-id"] = secrets.token_hex(16)
        base["application-credentials"] = "true"
    elif profile == "trace_only":
        base["x-trace-id"] = secrets.token_hex(16)
    return base


def _probe(session, url: str, profile: str, timeout=(10, 35)) -> dict:
    hdrs = _headers(profile)
    try:
        r = session.get(url, headers=hdrs, timeout=timeout, allow_redirects=True)
        text = r.text or ""
        rec = {
            "url": url,
            "header_profile": profile,
            "sent_special_headers": {k: hdrs[k] for k in ("application-credentials", "x-trace-id") if k in hdrs},
            "status": r.status_code,
            "content_type": (r.headers.get("content-type") or "").lower(),
            "length": len(text),
            "json": False,
            "top_level_keys": [],
            "response_auth_hints": {
                k: v for k, v in r.headers.items()
                if k.lower() in {"www-authenticate", "x-wso2-request-id", "x-correlation-id", "x-trace-id", "allow"}
            },
            "preview": _clean(text[:700]),
        }
        try:
            data = r.json()
            rec["json"] = True
            if isinstance(data, dict):
                rec["top_level_keys"] = list(data.keys())[:40]
                rec["preview"] = _clean(json.dumps(data, ensure_ascii=False)[:1600])
            elif isinstance(data, list):
                rec["top_level_keys"] = [f"list[{len(data)}]"]
                rec["preview"] = _clean(json.dumps(data[:1], ensure_ascii=False)[:1600])
        except Exception:
            pass
        return rec
    except Exception as exc:
        return {"url": url, "header_profile": profile, "error": f"{type(exc).__name__}: {exc}"}


def _looks_successful(rec: dict, offer_id: str) -> bool:
    if rec.get("status") != 200 or not rec.get("json") or int(rec.get("length", 0) or 0) < 50:
        return False
    p = str(rec.get("preview") or "").lower()
    return offer_id in p or any(k in p for k in ("oferta", "puesto", "titulo", "empresa", "descripcion", "requisitos"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Madrid POEM anonymous-header/API-base probe")
    ap.add_argument("--id", required=True, help="Public POEM offer id, e.g. 63661")
    ap.add_argument("--out", default="live_output/madrid_poem_auth_probe.json")
    args = ap.parse_args()

    offer_id = re.sub(r"\D", "", args.id)
    if not offer_id:
        raise SystemExit("--id must contain a numeric POEM offer id")

    result = {
        "probe": "Madrid POEM API base + anonymous header discovery",
        "offer_id": offer_id,
        "shell_fetch": "FAILED",
        "main_bundle": "",
        "main_bundle_status": None,
        "api_bases": [],
        "api_url_contexts": [],
        "application_credentials_occurrences": 0,
        "application_credentials_contexts": [],
        "auth_keyword_contexts": {},
        "candidate_requests": [],
        "successful_candidate": None,
        "errors": [],
        "next_step": "",
    }

    session = make_retry_session(total_retries=2, backoff_factor=0.7)
    try:
        shell = session.get(SPA_ROOT, timeout=(10, 40), allow_redirects=True)
        shell.raise_for_status()
        result["shell_fetch"] = "OK"
        scripts = _script_urls(shell.text, shell.url)
        mains = [u for u in scripts if re.search(r"/main\.[^/]+\.js(?:\?|$)", u)]
        if not mains:
            result["errors"].append("No main.*.js bundle found")
        else:
            main_url = mains[-1]
            result["main_bundle"] = main_url
            r = session.get(main_url, timeout=(10, 75), allow_redirects=True)
            result["main_bundle_status"] = r.status_code
            r.raise_for_status()
            js = r.text or ""

            result["api_bases"] = _extract_api_bases(js)
            result["api_url_contexts"] = _contexts(js, "API_URL", before=900, after=1200, limit=6)
            result["application_credentials_occurrences"] = js.count("application-credentials")
            result["application_credentials_contexts"] = _contexts(js, "application-credentials", before=1000, after=1400, limit=8)
            for kw in ("mv-wso2-token", "Authorization", "Bearer ", "client_id", "client_secret", "apikey", "api-key"):
                ctx = _contexts(js, kw, before=600, after=900, limit=3)
                if ctx:
                    result["auth_keyword_contexts"][kw] = ctx

            urls = _candidate_urls(result["api_bases"], offer_id)
            # Try exact Angular anonymous semantics first; minimal profiles are only diagnostic.
            for url in urls:
                for profile in ("angular_anonymous", "trace_only", "minimal"):
                    rec = _probe(session, url, profile)
                    result["candidate_requests"].append(rec)
                    if _looks_successful(rec, offer_id):
                        result["successful_candidate"] = rec
                        break
                if result["successful_candidate"]:
                    break

        if result["successful_candidate"]:
            result["next_step"] = "Anonymous public offer JSON resolved. Implement this exact base/path/header profile in sources/madrid_idi.py."
        elif result["candidate_requests"]:
            statuses = sorted({str(x.get("status")) for x in result["candidate_requests"] if x.get("status") is not None})
            result["next_step"] = (
                "No anonymous JSON success yet. Compare API_URL/application-credentials contexts and status changes across header profiles. "
                f"Observed statuses: {', '.join(statuses)}"
            )
        else:
            result["next_step"] = "No API candidates discovered from the current bundle."
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["next_step"] = "Probe failed before API/header discovery."
    finally:
        session.close()

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    compact = {
        "offer_id": result["offer_id"],
        "shell_fetch": result["shell_fetch"],
        "main_bundle": result["main_bundle"],
        "main_bundle_status": result["main_bundle_status"],
        "api_bases": result["api_bases"],
        "api_url_contexts": result["api_url_contexts"][:3],
        "application_credentials_occurrences": result["application_credentials_occurrences"],
        "application_credentials_contexts": result["application_credentials_contexts"][:4],
        "auth_keyword_contexts": result["auth_keyword_contexts"],
        "candidate_requests": result["candidate_requests"],
        "successful_candidate": result["successful_candidate"],
        "errors": result["errors"],
        "next_step": result["next_step"],
        "full_probe_file": str(out),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
