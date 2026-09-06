from jobbot.dedupe import deduplicate
from tests.legacy_tools.probe_madrid_poem import _script_urls, _extract_path_literals, _extract_absolute_urls


def _job(jid: str):
    return {
        "source": "Madrid I+D+i",
        "title": "Investigador/a",
        "company": "Example Foundation",
        "location": "Madrid, Spain",
        "url": f"https://gestiona.comunidad.madrid/poem_webapp/#/ver-oferta/{jid}",
        "id": jid,
        "full_detail": "",
        "detail_status": "EMPTY_DETAIL",
    }


def test_hash_routed_poem_ids_are_not_collapsed_by_global_dedupe():
    unique, removed = deduplicate([_job("63661"), _job("63762")])
    assert len(unique) == 2
    assert removed == 0


def test_identical_hash_routed_poem_url_still_dedupes():
    a, b = _job("63661"), _job("63661")
    unique, removed = deduplicate([a, b])
    assert len(unique) == 1
    assert removed == 1


def test_probe_extracts_script_urls_and_offer_api_hints():
    html = '<html><script src="runtime.abc.js"></script><script src="main.xyz.js"></script></html>'
    scripts = _script_urls(html, "https://example.org/app/")
    assert scripts == ["https://example.org/app/runtime.abc.js", "https://example.org/app/main.xyz.js"]
    js = 'const api="/poem-api/ofertas/"; const u="https://api.example.org/oferta/detail";'
    assert "/poem-api/ofertas/" in _extract_path_literals(js)
    assert "https://api.example.org/oferta/detail" in _extract_absolute_urls(js)
