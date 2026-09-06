from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from sources.fetch_detail import make_retry_session

ROOT = Path(__file__).resolve().parent
SPA_ROOT = "https://gestiona.comunidad.madrid/poem_webapp/"

KEYWORDS = (
    "ver-oferta", "oferta", "ofertas", "api", "rest", "endpoint", "service",
    "detalle", "detail", "vacante", "empleo", "poem",
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _script_urls(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[str] = []
    for tag in soup.find_all("script", src=True):
        u = urljoin(base, tag.get("src", ""))
        if u and u not in out:
            out.append(u)
    return out


def _extract_absolute_urls(js: str) -> list[str]:
    out = []
    for u in re.findall(r"https?://[^\"'\\\s<>]{6,240}", js or ""):
        u = u.rstrip(")]}.,;")
        if any(k in u.lower() for k in KEYWORDS) and u not in out:
            out.append(u)
    return out[:80]


def _extract_path_literals(js: str) -> list[str]:
    # Quoted URL/path-like strings only. This intentionally avoids dumping large JS bodies.
    out = []
    pattern = re.compile(r"[\"']([^\"'\\]{3,220})[\"']")
    for m in pattern.finditer(js or ""):
        v = _clean(m.group(1))
        low = v.lower()
        if not any(k in low for k in KEYWORDS):
            continue
        if ("/" not in v and "http" not in low) or len(v) > 220:
            continue
        if v not in out:
            out.append(v)
        if len(out) >= 120:
            break
    return out


def _keyword_snippets(js: str, limit: int = 35) -> list[str]:
    out = []
    low = (js or "").lower()
    positions = []
    for kw in KEYWORDS:
        start = 0
        while True:
            idx = low.find(kw, start)
            if idx < 0:
                break
            positions.append(idx)
            start = idx + len(kw)
            if len(positions) > 500:
                break
    for idx in sorted(set(positions)):
        a = max(0, idx - 180)
        b = min(len(js), idx + 260)
        snippet = _clean(js[a:b])
        if len(snippet) < 20:
            continue
        if snippet not in out:
            out.append(snippet)
        if len(out) >= limit:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnostic probe for the Madrid POEM SPA detail resolver")
    ap.add_argument("--id", required=True, help="A public POEM offer id, e.g. 63661")
    ap.add_argument("--out", default="live_output/madrid_poem_probe.json")
    ap.add_argument("--max-scripts", type=int, default=12)
    args = ap.parse_args()

    offer_id = re.sub(r"\D", "", args.id)
    if not offer_id:
        raise SystemExit("--id must contain a numeric POEM offer id")

    session = make_retry_session(total_retries=2, backoff_factor=0.8)
    result = {
        "probe": "Madrid POEM SPA static-discovery",
        "offer_id": offer_id,
        "spa_root": SPA_ROOT,
        "hash_offer_url": SPA_ROOT + "#/ver-oferta/" + offer_id,
        "shell_fetch": "FAILED",
        "shell_status_code": None,
        "shell_length": 0,
        "script_urls": [],
        "scripts_fetched": [],
        "absolute_url_hints": [],
        "path_hints": [],
        "keyword_snippets": [],
        "errors": [],
        "next_step": "",
    }
    try:
        r = session.get(SPA_ROOT, timeout=(10, 45), allow_redirects=True)
        result["shell_status_code"] = r.status_code
        r.raise_for_status()
        html = r.text
        result["shell_fetch"] = "OK"
        result["shell_length"] = len(html)
        scripts = _script_urls(html, r.url)
        result["script_urls"] = scripts

        abs_hints: list[str] = []
        path_hints: list[str] = []
        snippets: list[str] = []
        for u in scripts[: max(1, args.max_scripts)]:
            try:
                jr = session.get(u, timeout=(10, 60), allow_redirects=True)
                rec = {"url": u, "status": jr.status_code, "length": len(jr.text or "")}
                result["scripts_fetched"].append(rec)
                if jr.status_code >= 400:
                    continue
                txt = jr.text or ""
                for x in _extract_absolute_urls(txt):
                    if x not in abs_hints:
                        abs_hints.append(x)
                for x in _extract_path_literals(txt):
                    if x not in path_hints:
                        path_hints.append(x)
                for x in _keyword_snippets(txt):
                    if x not in snippets:
                        snippets.append(x)
            except Exception as exc:
                result["errors"].append(f"script {u}: {type(exc).__name__}: {exc}")

        result["absolute_url_hints"] = abs_hints[:80]
        result["path_hints"] = path_hints[:120]
        result["keyword_snippets"] = snippets[:35]
        if abs_hints or path_hints or snippets:
            result["next_step"] = "Static bundle hints found; use them to implement the POEM API/detail resolver."
        else:
            result["next_step"] = "No useful static endpoint hints found; browser-network capture may be required."
    except Exception as exc:
        result["errors"].append(f"shell: {type(exc).__name__}: {exc}")
        result["next_step"] = "POEM shell could not be fetched; inspect connectivity/TLS before API discovery."
    finally:
        session.close()

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print a compact but useful terminal version so no upload is needed in the normal case.
    compact = {
        "offer_id": result["offer_id"],
        "shell_fetch": result["shell_fetch"],
        "shell_status_code": result["shell_status_code"],
        "shell_length": result["shell_length"],
        "script_urls": result["script_urls"],
        "scripts_fetched": result["scripts_fetched"],
        "absolute_url_hints": result["absolute_url_hints"][:20],
        "path_hints": result["path_hints"][:35],
        "keyword_snippets": result["keyword_snippets"][:12],
        "errors": result["errors"],
        "next_step": result["next_step"],
        "full_probe_file": str(out),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
