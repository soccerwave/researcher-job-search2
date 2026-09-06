from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from sources.fetch_detail import make_retry_session

ROOT = Path(__file__).resolve().parent
SPA_ROOT = "https://gestiona.comunidad.madrid/poem_webapp/"
KNOWN_API_BASE = "https://apiscm.comunidad.madrid/t/ciudadanos.comunidad.madrid/educacion/ofertas-portal-empleo/v1/"


def _script_urls(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[str] = []
    for tag in soup.find_all("script", src=True):
        u = urljoin(base, tag.get("src", ""))
        if u and u not in out:
            out.append(u)
    return out


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _context(text: str, needle: str, before: int = 700, after: int = 1100) -> str:
    idx = text.find(needle)
    if idx < 0:
        return ""
    return _clean(text[max(0, idx-before): min(len(text), idx+len(needle)+after)])


def _quoted_literals(text: str) -> list[str]:
    vals = []
    for m in re.finditer(r'(["\'])(.*?)(?<!\\)\1', text or ""):
        v = m.group(2)
        if v and v not in vals:
            vals.append(v)
    return vals


def _extract_method_suffix(context: str) -> str:
    """Best-effort extraction of the literal suffix appended to this.url in getOfertaById."""
    pats = [
        r'getOfertaById=function\([^)]*\)\{.*?this\.url\+(["\'])([^"\']+)\1\+[^;,)]+',
        r'getOfertaById=function\([^)]*\).*?this\.url\+(["\'])([^"\']+)\1',
    ]
    for pat in pats:
        m = re.search(pat, context or "")
        if m:
            return m.group(2)
    return ""


def _extract_service_prefix(main_js: str, method_pos: int) -> str:
    """Look backwards for `this.url=...+\"prefix\"` in the service containing the method."""
    if method_pos < 0:
        return ""
    window = main_js[max(0, method_pos-9000):method_pos]
    candidates = []
    for m in re.finditer(r'this\.url\s*=\s*[^;]{0,500}?\+\s*(["\'])([^"\']{1,120})\1', window):
        candidates.append(m.group(2))
    return candidates[-1] if candidates else ""


def _extract_getheaders_context(main_js: str, method_pos: int) -> str:
    if method_pos < 0:
        return ""
    # In minified bundles methods for the same service are usually close together.
    window = main_js[max(0, method_pos-14000): min(len(main_js), method_pos+5000)]
    idx = window.rfind("getHeaders=function")
    if idx < 0:
        idx = window.find("getHeaders=function")
    if idx < 0:
        return ""
    return _clean(window[max(0, idx-500): min(len(window), idx+1800)])


def _candidate_urls(api_base: str, service_prefix: str, method_suffix: str, offer_id: str) -> list[str]:
    base = api_base.rstrip("/") + "/"
    pieces = []
    if service_prefix and method_suffix:
        pieces.append(service_prefix.strip("/") + "/" + method_suffix.strip("/") + "/" + offer_id)
    if method_suffix:
        pieces.append(method_suffix.strip("/") + "/" + offer_id)
    if service_prefix:
        pieces.append(service_prefix.strip("/") + "/" + offer_id)

    # Conservative fallbacks based on static literals in the public bundle. They are
    # probes only; nothing is scored from them unless a JSON-like offer response is found.
    pieces += [
        f"ofertas/getOfertaById/{offer_id}",
        f"getOfertaById/{offer_id}",
        f"oferta-completa/{offer_id}",
        f"ofertas/oferta-completa/{offer_id}",
        f"ofertas/{offer_id}",
    ]
    out=[]
    for p in pieces:
        u = base + p.lstrip("/")
        if u not in out:
            out.append(u)
    return out


def _response_probe(session, url: str, timeout=(10, 35)) -> dict:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": SPA_ROOT,
        "Origin": "https://gestiona.comunidad.madrid",
    }
    try:
        r = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        ctype = (r.headers.get("content-type") or "").lower()
        text = r.text or ""
        rec = {
            "url": url,
            "status": r.status_code,
            "content_type": ctype,
            "length": len(text),
            "json": False,
            "top_level_keys": [],
            "preview": _clean(text[:500]),
        }
        try:
            data = r.json()
            rec["json"] = True
            if isinstance(data, dict):
                rec["top_level_keys"] = list(data.keys())[:30]
                rec["preview"] = _clean(json.dumps(data, ensure_ascii=False)[:1200])
            elif isinstance(data, list):
                rec["top_level_keys"] = [f"list[{len(data)}]"]
                rec["preview"] = _clean(json.dumps(data[:1], ensure_ascii=False)[:1200])
        except Exception:
            pass
        return rec
    except Exception as exc:
        return {"url": url, "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Focused Madrid POEM API endpoint discovery probe")
    ap.add_argument("--id", required=True, help="Public POEM offer id, e.g. 63661")
    ap.add_argument("--out", default="live_output/madrid_poem_api_probe.json")
    args = ap.parse_args()

    offer_id = re.sub(r"\D", "", args.id)
    if not offer_id:
        raise SystemExit("--id must contain a numeric POEM offer id")

    result = {
        "probe": "Madrid POEM API focused discovery",
        "offer_id": offer_id,
        "shell_fetch": "FAILED",
        "main_bundle": "",
        "main_bundle_status": None,
        "main_bundle_length": 0,
        "api_base": KNOWN_API_BASE,
        "getOfertaById_context": "",
        "service_prefix": "",
        "method_suffix": "",
        "getHeaders_context": "",
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
            result["errors"].append("No main.*.js bundle found in POEM shell")
        else:
            main_url = mains[-1]
            result["main_bundle"] = main_url
            jr = session.get(main_url, timeout=(10, 75), allow_redirects=True)
            result["main_bundle_status"] = jr.status_code
            jr.raise_for_status()
            js = jr.text or ""
            result["main_bundle_length"] = len(js)

            pos = js.find("getOfertaById=function")
            if pos < 0:
                pos = js.find("getOfertaById")
            if pos >= 0:
                context = _clean(js[max(0, pos-1800): min(len(js), pos+2600)])
                result["getOfertaById_context"] = context
                result["method_suffix"] = _extract_method_suffix(context)
                result["service_prefix"] = _extract_service_prefix(js, pos)
                result["getHeaders_context"] = _extract_getheaders_context(js, pos)
            else:
                result["errors"].append("getOfertaById not found in main bundle")

            # Discover the API base directly from the same bundle if the build changes.
            api_hits = re.findall(r'https://apiscm\.comunidad\.madrid/t/ciudadanos\.comunidad\.madrid/educacion/ofertas-portal-empleo/v[0-9.]+/?', js)
            if api_hits:
                result["api_base"] = api_hits[-1].rstrip("/") + "/"

            candidates = _candidate_urls(result["api_base"], result["service_prefix"], result["method_suffix"], offer_id)
            for u in candidates:
                rec = _response_probe(session, u)
                result["candidate_requests"].append(rec)
                if rec.get("status") == 200 and rec.get("json") and int(rec.get("length", 0) or 0) > 50:
                    preview = str(rec.get("preview") or "").lower()
                    if offer_id in preview or any(k in preview for k in ("oferta", "puesto", "titulo", "empresa", "descripcion")):
                        result["successful_candidate"] = u
                        break

        if result["successful_candidate"]:
            result["next_step"] = "Public JSON offer endpoint resolved. Implement it in sources/madrid_idi.py and rerun the Madrid holdout."
        elif result["candidate_requests"]:
            result["next_step"] = "No public candidate succeeded yet. Use getOfertaById/getHeaders contexts and HTTP statuses to determine the required exact path or anonymous headers/token."
        else:
            result["next_step"] = "Bundle parsing did not yield enough endpoint information."
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["next_step"] = "Probe failed before API discovery; inspect connectivity/TLS."
    finally:
        session.close()

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # Terminal output deliberately contains enough information for the normal next step,
    # so the user should not need to upload the JSON file.
    compact = {
        "offer_id": result["offer_id"],
        "shell_fetch": result["shell_fetch"],
        "main_bundle": result["main_bundle"],
        "main_bundle_status": result["main_bundle_status"],
        "main_bundle_length": result["main_bundle_length"],
        "api_base": result["api_base"],
        "service_prefix": result["service_prefix"],
        "method_suffix": result["method_suffix"],
        "getOfertaById_context": result["getOfertaById_context"][:2400],
        "getHeaders_context": result["getHeaders_context"][:1800],
        "candidate_requests": result["candidate_requests"],
        "successful_candidate": result["successful_candidate"],
        "errors": result["errors"],
        "next_step": result["next_step"],
        "full_probe_file": str(out),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
